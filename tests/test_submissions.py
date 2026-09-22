from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.analytics.models import Event
from apps.speaking.models import SpeakingSession
from apps.writing.models import (
    SubmissionStatus,
    WritingFeedback,
    WritingSubmission,
    WritingTask,
    count_words,
)

pytestmark = pytest.mark.django_db
User = get_user_model()

TASK = "remote-work"


def auth(client, email="student@example.com", password="pw-test-1234"):
    body = client.post(
        reverse("api:auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {body['access']}"}


@pytest.fixture
def staff_client(client, db):
    client.force_login(
        User.objects.create_user(email="marker@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


def start(client, task=TASK, **extra):
    return client.post(
        reverse("api:writing-start"), {"taskId": task}, content_type="application/json", **extra
    )


# --- counting words ------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("   ", 0),
        ("one", 1),
        ("two words", 2),
        ("line one\nline two", 4),
        ("double  spaced   words", 3),
    ],
)
def test_words_are_counted_the_way_ielts_counts_them(text, expected):
    assert count_words(text) == expected


# --- the student's side --------------------------------------------------------


def test_starting_a_submission_creates_a_draft(seeded_content, client, user):
    response = start(client, **auth(client))

    assert response.status_code == 201
    assert response.json()["status"] == SubmissionStatus.DRAFT
    assert response.json()["targetWords"] == 250


def test_restarting_resumes_the_existing_draft(seeded_content, client, user):
    headers = auth(client)
    first = start(client, **headers).json()["id"]
    second = start(client, **headers).json()["id"]

    assert first == second
    assert WritingSubmission.objects.count() == 1


def test_autosave_tracks_the_word_count(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]

    response = client.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": "one two three four five", "timeSpentSeconds": 90},
        content_type="application/json",
        **headers,
    )

    assert response.json() == {"wordCount": 5, "meetsTarget": False}


def test_an_empty_submission_is_refused(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]

    response = client.post(reverse("api:writing-submit", args=[pk]), **headers)

    assert response.status_code == 400


def test_submitting_records_the_word_count_and_an_event(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]
    client.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": " ".join(["word"] * 260)},
        content_type="application/json",
        **headers,
    )

    body = client.post(reverse("api:writing-submit", args=[pk]), **headers).json()

    assert body["status"] == SubmissionStatus.SUBMITTED
    assert body["wordCount"] == 260
    assert body["meetsTarget"] is True
    assert Event.objects.filter(name="writing.submitted").exists()


def test_a_submitted_piece_cannot_be_edited(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]
    client.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": "Some words here."},
        content_type="application/json",
        **headers,
    )
    client.post(reverse("api:writing-submit", args=[pk]), **headers)

    response = client.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": "Changed my mind."},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 409


def test_another_student_cannot_read_a_submission(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]

    User.objects.create_user(email="nosy@example.com", password="pw-test-1234")
    other = client.__class__()
    response = other.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": "x"},
        content_type="application/json",
        **auth(other, email="nosy@example.com"),
    )

    assert response.status_code == 404


def test_a_guest_can_write_without_an_account(seeded_content, client):
    response = start(client)

    assert response.status_code == 201
    assert WritingSubmission.objects.get().user_id is None


# --- revealing the model answer ------------------------------------------------


def test_the_model_answer_is_withheld_until_submission_when_the_task_says_so(
    seeded_content, client, user
):
    """Checked server-side, so the client cannot skip it."""
    WritingTask.objects.filter(slug=TASK).update(reveal_policy="after_submission")
    headers = auth(client)
    pk = start(client, **headers).json()["id"]

    blocked = client.get(reverse("api:writing-model-answer", args=[pk]), **headers)
    assert blocked.status_code == 409

    client.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": "My own attempt."},
        content_type="application/json",
        **headers,
    )
    client.post(reverse("api:writing-submit", args=[pk]), **headers)

    allowed = client.get(reverse("api:writing-model-answer", args=[pk]), **headers)
    assert allowed.status_code == 200
    assert "\n\n" in allowed.json()["modelAnswers"][0]["body"]


def test_an_always_available_model_answer_needs_no_submission(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]

    assert client.get(reverse("api:writing-model-answer", args=[pk]), **headers).status_code == 200


def test_revealing_is_recorded_on_the_submission(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]

    client.get(reverse("api:writing-model-answer", args=[pk]), **headers)

    assert WritingSubmission.objects.get(pk=pk).model_answer_revealed_at is not None


# --- grading -------------------------------------------------------------------


@pytest.fixture
def submitted(seeded_content, client, user):
    headers = auth(client)
    pk = start(client, **headers).json()["id"]
    client.patch(
        reverse("api:writing-save", args=[pk]),
        {"body": " ".join(["word"] * 255)},
        content_type="application/json",
        **headers,
    )
    client.post(reverse("api:writing-submit", args=[pk]), **headers)
    return WritingSubmission.objects.get(pk=pk)


def test_the_overall_band_is_the_mean_of_the_four_criteria(submitted, staff_client):
    staff_client.post(
        reverse("dashboard:grade-submission", args=[submitted.pk]),
        {
            "task_achievement": "7.0",
            "coherence_cohesion": "6.5",
            "lexical_resource": "6.0",
            "grammatical_range": "6.5",
            "comment": "Solid structure.",
        },
    )

    feedback = WritingFeedback.objects.get()
    # (7.0 + 6.5 + 6.0 + 6.5) / 4 = 6.5
    assert feedback.overall == Decimal("6.5")


def test_the_overall_band_cannot_be_typed_in_directly(submitted, staff_client):
    """It is derived, so it can never disagree with the criteria it summarises."""
    staff_client.post(
        reverse("dashboard:grade-submission", args=[submitted.pk]),
        {
            "task_achievement": "5.0",
            "coherence_cohesion": "5.0",
            "lexical_resource": "5.0",
            "grammatical_range": "5.0",
            "overall": "9.0",
            "comment": "",
        },
    )

    assert WritingFeedback.objects.get().overall == Decimal("5.0")


def test_grading_moves_the_submission_out_of_the_queue(submitted, staff_client):
    staff_client.post(
        reverse("dashboard:grade-submission", args=[submitted.pk]),
        {
            "task_achievement": "6.0", "coherence_cohesion": "6.0",
            "lexical_resource": "6.0", "grammatical_range": "6.0", "comment": "",
        },
    )
    submitted.refresh_from_db()

    assert submitted.status == SubmissionStatus.GRADED


def test_the_student_sees_their_feedback(submitted, client, user):
    WritingFeedback.objects.create(
        submission=submitted, task_achievement=7, coherence_cohesion=7,
        lexical_resource=7, grammatical_range=7, overall=7, comment="Well argued.",
    )

    body = client.get(reverse("api:writing-mine"), **auth(client)).json()

    assert body["count"] == 1
    assert body["results"][0]["feedback"]["overall"] == "7.0"
    assert body["results"][0]["feedback"]["comment"] == "Well argued."


def test_returning_a_submission_puts_it_back_in_draft(submitted, staff_client):
    staff_client.post(reverse("dashboard:grading-return", args=[submitted.pk]), follow=True)
    submitted.refresh_from_db()

    assert submitted.status == SubmissionStatus.DRAFT
    assert submitted.submitted_at is None


def test_the_grading_queue_shows_waiting_work(submitted, staff_client):
    html = staff_client.get(reverse("dashboard:grading-queue")).content.decode()

    assert "remote-work" in html


def test_the_grading_pages_are_staff_only(submitted, client, user):
    client.force_login(user)

    assert client.get(reverse("dashboard:grading-queue")).status_code == 404
    assert client.get(reverse("dashboard:grade-submission", args=[submitted.pk])).status_code == 404


# --- speaking sessions ---------------------------------------------------------


def test_a_speaking_session_records_progress(seeded_content, client, user):
    headers = auth(client)
    pk = client.post(
        reverse("api:speaking-session-start"),
        {"topicId": "hometown"},
        content_type="application/json",
        **headers,
    ).json()["id"]

    response = client.patch(
        reverse("api:speaking-session-update", args=[pk]),
        {"partsCompleted": [1, 2], "prepUsedSeconds": 55, "speakUsedSeconds": 110},
        content_type="application/json",
        **headers,
    )

    assert response.json()["partsCompleted"] == [1, 2]
    assert response.json()["isComplete"] is False


def test_reported_parts_accumulate_rather_than_replace(seeded_content, client, user):
    """Parts are reported as they finish; a retry must not erase earlier ones."""
    headers = auth(client)
    pk = client.post(
        reverse("api:speaking-session-start"),
        {"topicId": "travel"},
        content_type="application/json",
        **headers,
    ).json()["id"]

    for parts in ([1], [2], [3]):
        body = client.patch(
            reverse("api:speaking-session-update", args=[pk]),
            {"partsCompleted": parts},
            content_type="application/json",
            **headers,
        ).json()

    assert body["partsCompleted"] == [1, 2, 3]
    assert body["isComplete"] is True


def test_completing_a_session_records_an_event(seeded_content, client, user):
    headers = auth(client)
    pk = client.post(
        reverse("api:speaking-session-start"),
        {"topicId": "technology"},
        content_type="application/json",
        **headers,
    ).json()["id"]

    client.patch(
        reverse("api:speaking-session-update", args=[pk]),
        {"partsCompleted": [1, 2, 3], "complete": True, "selfRating": 4},
        content_type="application/json",
        **headers,
    )

    assert Event.objects.filter(name="speaking.session_completed").exists()
    assert SpeakingSession.objects.get(pk=pk).completed_at is not None


def test_an_out_of_range_part_is_rejected(seeded_content, client, user):
    headers = auth(client)
    pk = client.post(
        reverse("api:speaking-session-start"),
        {"topicId": "travel"},
        content_type="application/json",
        **headers,
    ).json()["id"]

    response = client.patch(
        reverse("api:speaking-session-update", args=[pk]),
        {"partsCompleted": [4]},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


def test_another_student_cannot_touch_a_session(seeded_content, client, user):
    headers = auth(client)
    pk = client.post(
        reverse("api:speaking-session-start"),
        {"topicId": "travel"},
        content_type="application/json",
        **headers,
    ).json()["id"]

    User.objects.create_user(email="other2@example.com", password="pw-test-1234")
    other = client.__class__()
    response = other.patch(
        reverse("api:speaking-session-update", args=[pk]),
        {"partsCompleted": [1]},
        content_type="application/json",
        **auth(other, email="other2@example.com"),
    )

    assert response.status_code == 404


def test_the_speaking_sessions_page_renders(seeded_content, staff_client):
    assert staff_client.get(reverse("dashboard:speaking-sessions")).status_code == 200
