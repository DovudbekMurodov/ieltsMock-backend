import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.common.models import PublishStatus
from apps.content.enums import QuestionType, Skill
from apps.content.models import AnswerKey, Block, Option, Question, QuestionGroup, Section, Test

pytestmark = pytest.mark.django_db
User = get_user_model()

PAGES = [
    "dashboard:overview",
    "dashboard:test-list",
    "dashboard:listening-list",
    "dashboard:writing-list",
    "dashboard:speaking-list",
    "dashboard:vocabulary-list",
    "dashboard:user-list",
    "dashboard:attempt-list",
    "dashboard:band-scale-list",
]


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        email="editor@example.com", password="pw-test-1234", is_staff=True
    )


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


@pytest.fixture
def draft(db):
    test = Test.objects.create(
        skill=Skill.READING, slug="draft-test", title="Draft Test", time_limit_minutes=20
    )
    Section.objects.create(test=test, order=1, title="Passage")
    return test


# --- access --------------------------------------------------------------------


@pytest.mark.parametrize("name", PAGES)
def test_anonymous_visitors_are_sent_to_the_login_page(client, name):
    response = client.get(reverse(name))

    assert response.status_code == 302
    assert reverse("dashboard:login") in response["Location"]


@pytest.mark.parametrize("name", PAGES)
def test_signed_in_non_staff_get_404_not_403(client, user, name):
    """403 would confirm the dashboard is really there."""
    client.force_login(user)

    assert client.get(reverse(name)).status_code == 404


def test_login_rejects_a_non_staff_account(client, user):
    response = client.post(
        reverse("dashboard:login"), {"email": user.email, "password": "pw-test-1234"}
    )

    assert response.status_code == 200
    assert "Incorrect email or password" in response.content.decode()


def test_login_message_does_not_reveal_that_the_account_exists(client, user):
    message = "Incorrect email or password."

    real = client.post(
        reverse("dashboard:login"), {"email": user.email, "password": "wrong-password"}
    ).content.decode()
    fake = client.post(
        reverse("dashboard:login"), {"email": "nobody@example.com", "password": "wrong-password"}
    ).content.decode()

    assert message in real and message in fake
    assert "no account" not in real.lower()
    assert "not staff" not in real.lower()


def test_staff_can_sign_in(client, staff):
    response = client.post(
        reverse("dashboard:login"), {"email": staff.email, "password": "pw-test-1234"}
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("dashboard:overview")


# --- pages render --------------------------------------------------------------


@pytest.mark.parametrize("name", PAGES)
def test_pages_render_for_staff(seeded_content, staff_client, name):
    assert staff_client.get(reverse(name)).status_code == 200


def test_overview_renders_charts_without_a_js_library(seeded_content, staff_client):
    """Charts are markup the server produced, not a canvas a library fills in.

    An HTMX-swapped canvas needs its library re-initialised after every swap,
    which is a steady source of blank charts.
    """
    html = staff_client.get(reverse("dashboard:overview")).content.decode()

    assert 'role="img"' in html, "charts should render as labelled graphics"
    for library in ("chart.js", "d3.", "plotly", "highcharts", "<canvas"):
        assert library not in html.lower()


def test_editor_renders_the_seeded_structure(seeded_content, staff_client):
    test = Test.objects.get(slug="twilight-zone")

    html = staff_client.get(reverse("dashboard:test-edit", args=[test.pk])).content.decode()

    assert "Twilight Zone" in html
    assert "Shared option pool" in html, "the matching group should expose its pool"
    assert html.count("hx-post") > 5


def test_preview_shows_the_answer_key_that_the_api_withholds(seeded_content, staff_client, client):
    test = Test.objects.get(slug="twilight-zone")
    answer = AnswerKey.objects.filter(question__test=test, option__isnull=True).first()

    preview = staff_client.get(reverse("dashboard:test-preview", args=[test.pk])).content.decode()
    delivery = client.get(reverse("api:test-detail", args=["twilight-zone"])).content.decode()

    assert "Answer key" in preview
    assert answer.value in preview
    assert "correctAnswers" not in delivery


# --- the editor ----------------------------------------------------------------


def test_creating_a_test_starts_it_as_a_draft_with_a_section(staff_client):
    response = staff_client.post(
        reverse("dashboard:test-create"),
        {
            "title": "New Reading Test",
            "slug": "new-reading-test",
            "skill": Skill.READING,
            "description": "",
            "time_limit_minutes": 20,
            "difficulty": "",
        },
    )

    test = Test.objects.get(slug="new-reading-test")
    assert response.status_code == 302
    assert test.status == PublishStatus.DRAFT
    assert test.sections.count() == 1


def test_pasting_a_passage_creates_labelled_paragraphs(staff_client, draft):
    section = draft.sections.get()

    response = staff_client.post(
        reverse("dashboard:hx-bulk-blocks", args=[section.pk]),
        {"text": "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.", "replace": "on"},
    )

    assert response.status_code == 200
    labels = list(section.blocks.order_by("order").values_list("label", flat=True))
    assert labels == ["A", "B", "C"]


def test_pasting_a_transcript_splits_on_speaker(staff_client):
    test = Test.objects.create(
        skill=Skill.LISTENING, slug="draft-listening", title="Draft", time_limit_minutes=15
    )
    section = Section.objects.create(test=test, order=1, title="Section 1")

    staff_client.post(
        reverse("dashboard:hx-bulk-blocks", args=[section.pk]),
        {"text": "Tutor: Good morning.\nStudent: Hello there.", "replace": "on"},
    )

    blocks = list(section.blocks.order_by("order"))
    assert [b.label for b in blocks] == ["Tutor", "Student"]
    assert blocks[0].text == "Good morning."


@pytest.mark.parametrize(
    "qtype,scope,mode",
    [
        (QuestionType.TFNG, "per_question", "exact"),
        (QuestionType.MCQ, "per_question", "exact"),
        (QuestionType.GAP, "per_question", "normalized"),
        (QuestionType.MATCHING, "shared", "exact"),
    ],
)
def test_group_creation_derives_scope_and_match_mode(staff_client, draft, qtype, scope, mode):
    """Those two fields are never asked for: only one combination is valid per type."""
    section = draft.sections.get()

    staff_client.post(reverse("dashboard:hx-group-create", args=[section.pk]), {"type": qtype})

    group = section.groups.get()
    assert group.type == qtype
    assert group.options_scope == scope
    assert group.match_mode == mode


def test_an_unknown_group_type_is_rejected(staff_client, draft):
    section = draft.sections.get()

    response = staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": "telepathy"}
    )

    assert response.status_code == 404
    assert not section.groups.exists()


def test_adding_an_mcq_question_scaffolds_four_options(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.MCQ}
    )
    group = section.groups.get()

    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))

    question = group.questions.get()
    assert question.options.count() == 4
    assert [o.label for o in question.options.order_by("order")] == ["A", "B", "C", "D"]


def test_adding_a_tfng_question_scaffolds_an_answer(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.TFNG}
    )
    group = section.groups.get()

    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))

    assert group.questions.get().answer_keys.get().value == "TRUE"


def test_setting_a_tfng_answer(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.TFNG}
    )
    group = section.groups.get()
    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))
    question = group.questions.get()

    staff_client.post(
        reverse("dashboard:hx-answer-set", args=[question.pk]), {"value": "NOT GIVEN"}
    )

    assert question.answer_keys.get().value == "NOT GIVEN"


def test_an_invalid_tfng_answer_is_refused(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.TFNG}
    )
    group = section.groups.get()
    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))
    question = group.questions.get()

    response = staff_client.post(
        reverse("dashboard:hx-answer-set", args=[question.pk]), {"value": "MAYBE"}
    )

    assert response.status_code == 400


def test_gap_questions_accept_several_spellings(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.GAP}
    )
    group = section.groups.get()
    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))
    question = group.questions.get()

    staff_client.post(
        reverse("dashboard:hx-answer-set", args=[question.pk]), {"value": ["ninety", "90"]}
    )

    assert sorted(question.answer_keys.values_list("value", flat=True)) == ["90", "ninety"]


def test_a_matching_answer_must_come_from_the_shared_pool(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.MATCHING}
    )
    group = section.groups.get()
    staff_client.post(reverse("dashboard:hx-pool-option-create", args=[group.pk]))
    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))
    question = group.questions.get()
    option = group.options.get()

    staff_client.post(
        reverse("dashboard:hx-answer-set", args=[question.pk]), {"optionId": option.pk}
    )
    assert question.answer_keys.get().option_id == option.pk

    other_group = QuestionGroup.objects.create(
        section=section, order=9, type=QuestionType.MATCHING, options_scope="shared"
    )
    foreign = Option.objects.create(group=other_group, order=1, text="elsewhere")
    response = staff_client.post(
        reverse("dashboard:hx-answer-set", args=[question.pk]), {"optionId": foreign.pk}
    )

    assert response.status_code == 400


def test_pool_options_are_shared_rather_than_copied_per_question(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.MATCHING}
    )
    group = section.groups.get()
    for _ in range(3):
        staff_client.post(reverse("dashboard:hx-pool-option-create", args=[group.pk]))
    for _ in range(2):
        staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))

    assert group.options.filter(question__isnull=True).count() == 3
    assert Option.objects.filter(question__in=group.questions.all()).count() == 0


def test_deleting_a_question_renumbers_the_rest(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.TFNG}
    )
    group = section.groups.get()
    for _ in range(3):
        staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))
    middle = group.questions.order_by("order")[1]

    staff_client.delete(reverse("dashboard:hx-question", args=[middle.pk]))

    numbers = list(
        Question.objects.filter(test=draft).order_by("number").values_list("number", flat=True)
    )
    assert numbers == [1, 2]


def test_reordering_questions_renumbers_them(staff_client, draft):
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.TFNG}
    )
    group = section.groups.get()
    for _ in range(3):
        staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))
    ids = list(group.questions.order_by("order").values_list("id", flat=True))

    staff_client.post(
        reverse("dashboard:hx-reorder", args=["group-questions", group.pk]),
        {"order": [ids[2], ids[0], ids[1]]},
    )

    assert list(group.questions.order_by("order").values_list("id", flat=True)) == [
        ids[2], ids[0], ids[1],
    ]
    assert Question.objects.get(pk=ids[2]).number == 1


def test_editing_the_test_meta_saves(staff_client, draft):
    response = staff_client.post(
        reverse("dashboard:hx-test-meta", args=[draft.pk]),
        {
            "title": "Renamed",
            "slug": draft.slug,
            "skill": draft.skill,
            "description": "",
            "time_limit_minutes": 25,
            "difficulty": "",
            "version": draft.version,
        },
    )
    draft.refresh_from_db()

    assert response.status_code == 204
    assert draft.title == "Renamed"
    assert draft.time_limit_minutes == 25


def test_a_stale_edit_is_refused_rather_than_overwriting(staff_client, draft):
    """Two editors on one test: the second save loses instead of winning silently."""
    response = staff_client.post(
        reverse("dashboard:hx-test-meta", args=[draft.pk]),
        {
            "title": "Stale write",
            "slug": draft.slug,
            "skill": draft.skill,
            "description": "",
            "time_limit_minutes": 20,
            "difficulty": "",
            "version": draft.version - 1,
        },
    )
    draft.refresh_from_db()

    assert response.status_code == 409
    assert draft.title == "Draft Test"


# --- publishing ----------------------------------------------------------------


def test_publishing_an_empty_test_is_refused(staff_client, draft):
    staff_client.post(reverse("dashboard:test-publish", args=[draft.pk]), follow=True)
    draft.refresh_from_db()

    assert draft.status == PublishStatus.DRAFT
    assert draft.published_payload is None


def test_publishing_makes_a_draft_reachable_over_the_api(staff_client, client, draft):
    section = draft.sections.get()
    Block.objects.create(section=section, order=1, label="A", text="Body text.")
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.TFNG}
    )
    group = section.groups.get()
    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))

    assert client.get(reverse("api:test-detail", args=[draft.slug])).status_code == 404

    staff_client.post(reverse("dashboard:test-publish", args=[draft.pk]), follow=True)
    response = client.get(reverse("api:test-detail", args=[draft.slug]))

    assert response.status_code == 200
    assert response.json()["questionCount"] == 1


def test_unpublishing_takes_a_test_out_of_the_api(seeded_content, staff_client, client):
    test = Test.objects.get(slug="museum-tour")
    try:
        staff_client.post(reverse("dashboard:test-unpublish", args=[test.pk]), follow=True)

        assert client.get(reverse("api:test-detail", args=["museum-tour"])).status_code == 404
    finally:
        Test.objects.filter(pk=test.pk).update(status=PublishStatus.PUBLISHED)


def test_an_unpublished_draft_is_never_served_while_being_edited(staff_client, client, draft):
    """Persist-on-interaction is only safe because a half-built test stays private."""
    section = draft.sections.get()
    staff_client.post(
        reverse("dashboard:hx-group-create", args=[section.pk]), {"type": QuestionType.MCQ}
    )
    group = section.groups.get()
    staff_client.post(reverse("dashboard:hx-question-create", args=[group.pk]))

    assert client.get(reverse("api:test-detail", args=[draft.slug])).status_code == 404
