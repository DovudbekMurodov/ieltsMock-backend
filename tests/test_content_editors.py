import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.common.models import PublishStatus
from apps.dashboard.forms import parse_words
from apps.speaking.models import SpeakingItem, SpeakingItemKind, SpeakingTopic
from apps.vocabulary.models import VocabularySection, VocabularyWord
from apps.writing.models import WritingModelAnswer, WritingTask

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff_client(client, db):
    staff = User.objects.create_user(
        email="editor2@example.com", password="pw-test-1234", is_staff=True
    )
    client.force_login(staff)
    return client


@pytest.fixture
def section(db):
    return VocabularySection.objects.create(slug="sec", title="Section", order=1)


# --- the bulk word parser ------------------------------------------------------


def test_parser_accepts_pipe_and_tab_separated_rows():
    piped, _ = parse_words("Substantial | adjective | Fairly large. | A **substantial** drop.")
    tabbed, _ = parse_words("Mitigate\tverb\tMake less severe.\tSteps to **mitigate** damage.")

    assert piped[0]["headword"] == "Substantial"
    assert tabbed[0]["pos"] == "verb"


def test_parser_reports_rows_it_cannot_use_rather_than_dropping_them():
    rows, rejected = parse_words(
        "Good | noun | A definition. | An **example** here.\n"
        "Broken row with no separators\n"
        "Missing | noun | Bold marker absent. | no bold here\n"
    )

    assert len(rows) == 1
    assert len(rejected) == 2
    assert any("bold" in line for line in rejected)


def test_parser_keeps_pipes_inside_the_example():
    rows, _ = parse_words("Word | noun | Def. | A **word** with | a pipe.")

    assert rows[0]["example"] == "A **word** with | a pipe."


# --- vocabulary ----------------------------------------------------------------


def test_importing_words_creates_them_in_order(staff_client, section):
    response = staff_client.post(
        reverse("dashboard:hx-word-import", args=[section.slug]),
        {
            "text": (
                "Substantial | adjective | Fairly large. | A **substantial** drop.\n"
                "Mitigate | verb | Make less severe. | Steps to **mitigate** damage.\n"
            )
        },
    )

    assert response.status_code == 200
    assert list(section.words.order_by("order").values_list("headword", flat=True)) == [
        "Substantial",
        "Mitigate",
    ]


def test_import_surfaces_rejected_lines_in_the_response(staff_client, section):
    response = staff_client.post(
        reverse("dashboard:hx-word-import", args=[section.slug]),
        {"text": "Good | noun | Def. | An **example**.\nnonsense line\n"},
    )

    assert "1 line skipped" in response.content.decode()
    assert section.words.count() == 1


def test_reimporting_the_same_word_updates_rather_than_duplicates(staff_client, section):
    for definition in ("First definition.", "Second definition."):
        staff_client.post(
            reverse("dashboard:hx-word-import", args=[section.slug]),
            {"text": f"Word | noun | {definition} | An **example**."},
        )

    assert section.words.count() == 1
    assert section.words.get().definition == "Second definition."


def test_a_word_example_must_carry_exactly_one_bold_span(staff_client, section):
    word = VocabularyWord.objects.create(
        section=section, headword="Test", pos="noun", definition="d",
        example="A **bold** span.", order=1,
    )

    response = staff_client.post(
        reverse("dashboard:hx-word", args=[word.pk]),
        {"headword": "Test", "pos": "noun", "definition": "d", "example": "no bold at all"},
    )
    word.refresh_from_db()

    assert response.status_code == 400
    assert word.example == "A **bold** span."


def test_publishing_a_section_makes_it_reachable_over_the_api(staff_client, client, section):
    staff_client.post(
        reverse("dashboard:hx-word-import", args=[section.slug]),
        {"text": "Word | noun | Def. | An **example**."},
    )
    assert client.get(reverse("api:vocabulary-detail", args=[section.slug])).status_code == 404

    staff_client.post(reverse("dashboard:vocabulary-publish", args=[section.slug]), follow=True)
    response = client.get(reverse("api:vocabulary-detail", args=[section.slug]))

    assert response.status_code == 200
    assert response.json()["words"][0]["exampleParts"][1]["bold"] is True


def test_publishing_an_empty_section_is_refused(staff_client, section):
    staff_client.post(reverse("dashboard:vocabulary-publish", args=[section.slug]), follow=True)
    section.refresh_from_db()

    assert section.status == PublishStatus.DRAFT


# --- writing -------------------------------------------------------------------


def test_creating_a_writing_task_starts_it_as_a_draft(staff_client):
    staff_client.post(
        reverse("dashboard:writing-create"),
        {
            "slug": "new-task", "task_number": 2, "type": "agree_disagree",
            "prompt": "Discuss.", "suggested_time_minutes": 40, "target_words": 250,
            "status": PublishStatus.DRAFT, "reveal_policy": "always",
        },
    )

    assert WritingTask.objects.get(slug="new-task").status == PublishStatus.DRAFT


def test_a_model_answer_keeps_its_blank_lines_exactly(seeded_content, staff_client):
    """The frontend splits on '\\n\\n', so normalising whitespace destroys layout."""
    task = WritingTask.objects.get(slug="remote-work")
    answer = task.model_answers.get()
    body = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

    staff_client.post(
        reverse("dashboard:hx-writing-answer", args=[answer.pk]),
        {f"a{answer.pk}-band": "8.0", f"a{answer.pk}-body": body},
    )
    answer.refresh_from_db()

    assert answer.body == body
    assert len(answer.paragraphs) == 3


def test_adding_and_deleting_model_answers(seeded_content, staff_client):
    task = WritingTask.objects.get(slug="plastic-waste")
    before = task.model_answers.count()

    staff_client.post(reverse("dashboard:hx-writing-answer-create", args=[task.slug]))
    assert task.model_answers.count() == before + 1

    newest = task.model_answers.order_by("-order").first()
    staff_client.delete(reverse("dashboard:hx-writing-answer", args=[newest.pk]))
    assert task.model_answers.count() == before


def test_model_answers_are_withheld_when_the_reveal_policy_says_so(
    seeded_content, staff_client, client
):
    task = WritingTask.objects.get(slug="online-degrees")
    staff_client.post(
        reverse("dashboard:hx-writing-meta", args=[task.slug]),
        {
            "slug": task.slug, "task_number": task.task_number, "type": task.type,
            "prompt": task.prompt, "suggested_time_minutes": task.suggested_time_minutes,
            "target_words": task.target_words, "status": task.status,
            "reveal_policy": "after_submission",
        },
    )

    payload = client.get(reverse("api:writing-detail", args=[task.slug])).json()

    assert "modelAnswers" not in payload
    assert payload["revealPolicy"] == "after_submission"


# --- speaking ------------------------------------------------------------------


def test_creating_a_topic_also_creates_its_cue_card(staff_client):
    staff_client.post(
        reverse("dashboard:speaking-create"),
        {"title": "Music", "slug": "music", "order": 9, "status": PublishStatus.DRAFT},
    )

    topic = SpeakingTopic.objects.get(slug="music")
    assert topic.cue_card is not None


@pytest.mark.parametrize(
    "part,kind",
    [
        (1, SpeakingItemKind.QUESTION),
        (2, SpeakingItemKind.BULLET),
        (3, SpeakingItemKind.QUESTION),
        (3, SpeakingItemKind.PHRASE),
    ],
)
def test_each_slot_adds_items_independently(seeded_content, staff_client, part, kind):
    topic = SpeakingTopic.objects.get(slug="travel")
    before = topic.items.filter(part=part, kind=kind).count()

    staff_client.post(
        reverse("dashboard:hx-speaking-item-create", args=[topic.slug, part, kind])
    )

    assert topic.items.filter(part=part, kind=kind).count() == before + 1


def test_an_unknown_slot_is_rejected(seeded_content, staff_client):
    topic = SpeakingTopic.objects.get(slug="travel")

    response = staff_client.post(
        reverse("dashboard:hx-speaking-item-create", args=[topic.slug, 3, "monologue"])
    )

    assert response.status_code == 404


def test_editing_and_deleting_a_speaking_item(seeded_content, staff_client):
    topic = SpeakingTopic.objects.get(slug="hobbies")
    item = topic.items.filter(part=1).first()

    staff_client.post(reverse("dashboard:hx-speaking-item", args=[item.pk]), {"text": "Reworded?"})
    item.refresh_from_db()
    assert item.text == "Reworded?"

    staff_client.delete(reverse("dashboard:hx-speaking-item", args=[item.pk]))
    assert not SpeakingItem.objects.filter(pk=item.pk).exists()


def test_the_cue_card_timings_are_editable(seeded_content, staff_client):
    topic = SpeakingTopic.objects.get(slug="technology")

    staff_client.post(
        reverse("dashboard:hx-speaking-cue", args=[topic.slug]),
        {"title": "Describe a gadget.", "prep_seconds": 45, "speak_seconds": 90},
    )
    topic.cue_card.refresh_from_db()

    assert topic.cue_card.prep_seconds == 45
    assert topic.cue_card.speak_seconds == 90


# --- no page still defers to Django admin --------------------------------------


@pytest.mark.parametrize(
    "name,args",
    [
        ("dashboard:vocabulary-list", []),
        ("dashboard:writing-list", []),
        ("dashboard:speaking-list", []),
    ],
)
def test_list_pages_link_to_the_dashboard_editors_not_django_admin(
    seeded_content, staff_client, name, args
):
    html = staff_client.get(reverse(name, args=args)).content.decode()

    assert "/admin/" not in html
    assert "/dashboard/" in html


def test_every_model_answer_survived_the_editor_rewrite(seeded_content):
    assert WritingModelAnswer.objects.count() == 5
