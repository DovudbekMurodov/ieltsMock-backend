import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.common.models import PublishStatus
from apps.content.enums import MatchMode, QuestionType
from apps.content.models import AnswerKey, Question, QuestionGroup, Section, Test
from apps.content.publishing import build_test_payload, published_queryset

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff(client):
    client.force_login(
        User.objects.create_user(email="editor@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


@pytest.fixture
def gap_question(db):
    test = Test.objects.create(
        slug="notes", title="Notes", skill="listening", time_limit_minutes=10
    )
    section = Section.objects.create(test=test, order=1, title="Notes")
    # A gap group is only valid with normalised matching; the editor derives
    # this server-side, so a fixture has to set it explicitly.
    group = QuestionGroup.objects.create(
        section=section, order=1, type=QuestionType.GAP, match_mode=MatchMode.NORMALIZED
    )
    question = Question.objects.create(test=test, group=group, number=1, prompt="Gallery")
    return question


# --- a group needs a heading of its own ---------------------------------------


def test_a_group_heading_can_be_saved_from_the_editor(staff, gap_question):
    group = gap_question.group

    staff.post(
        reverse("dashboard:hx-group", args=[group.pk]),
        {
            "type": group.type,
            "heading": "The Globe\nParts of the original Globe",
            "instructions": "",
        },
    )

    group.refresh_from_db()
    assert group.heading == "The Globe\nParts of the original Globe"


def test_the_heading_reaches_the_published_payload(staff, gap_question):
    group = gap_question.group
    group.heading = "The Globe"
    # The rubric is a different thing and lives in its own field: it is shown
    # per question, so a title stored here would repeat above every gap.
    group.instructions = "Write NO MORE THAN TWO WORDS."
    group.save()
    AnswerKey.objects.create(question=gap_question, value="gallery")

    payload = build_test_payload(published_queryset().get(pk=gap_question.test_id))
    published_group = payload["sections"][0]["groups"][0]

    assert published_group["heading"] == "The Globe"
    assert published_group["instructions"] == "Write NO MORE THAN TWO WORDS."


# --- accepted answers ---------------------------------------------------------


def test_an_existing_accepted_answer_can_be_corrected(staff, gap_question):
    """The input used to be readonly, so a typo could only be deleted and retyped."""
    key = AnswerKey.objects.create(question=gap_question, value="gallry")

    response = staff.post(reverse("dashboard:hx-key-save", args=[key.pk]), {"value": "gallery"})

    assert response.status_code == 204
    key.refresh_from_db()
    assert key.value == "gallery"


def test_saving_an_answer_keeps_its_pk(staff, gap_question):
    """204 and the same row, deliberately.

    Re-rendering the card on every keystroke would move focus mid-word, and
    recreating the keys would invalidate the delete buttons beside them.
    """
    key = AnswerKey.objects.create(question=gap_question, value="a")

    staff.post(reverse("dashboard:hx-key-save", args=[key.pk]), {"value": "b"})

    assert AnswerKey.objects.filter(pk=key.pk).count() == 1


def test_a_new_gap_question_has_no_blank_answer_row(staff, gap_question):
    """A seeded blank key rendered as an empty box that rejected every keystroke."""
    group = gap_question.group

    staff.post(reverse("dashboard:hx-question-create", args=[group.pk]))

    created = Question.objects.filter(group=group).order_by("-number").first()
    assert created.answer_keys.count() == 0


# --- publishing ---------------------------------------------------------------


def test_publishing_is_refused_when_a_question_has_no_accepted_answer(staff, gap_question):
    """Scoring compares against the keys, so no key means every candidate is
    marked wrong with nothing explaining why."""
    response = staff.post(
        reverse("dashboard:test-publish", args=[gap_question.test_id]), follow=True
    )

    gap_question.test.refresh_from_db()
    assert gap_question.test.status != PublishStatus.PUBLISHED
    assert "question 1" in response.content.decode().lower()


def test_publishing_succeeds_once_every_question_is_answerable(staff, gap_question):
    AnswerKey.objects.create(question=gap_question, value="gallery")

    staff.post(reverse("dashboard:test-publish", args=[gap_question.test_id]), follow=True)

    gap_question.test.refresh_from_db()
    assert gap_question.test.status == PublishStatus.PUBLISHED
