import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone

from apps.attempts.models import AttemptStatus, TestAttempt
from apps.content.models import AnswerKey, Question, Test

pytestmark = pytest.mark.django_db

SLUG = "twilight-zone"


def auth(client, email="student@example.com", password="pw-test-1234"):
    body = client.post(
        reverse("api:auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {body['access']}"}


def start(client, slug=SLUG, **extra):
    return client.post(
        reverse("api:attempts:start"), {"testId": slug}, content_type="application/json", **extra
    )


def correct_answers(slug=SLUG):
    """Build the answer payload that scores full marks."""
    entries = []
    for question in Question.objects.filter(test__slug=slug).select_related("group"):
        keys = list(question.answer_keys.all())
        entry = {"questionId": question.id, "value": keys[0].value}
        if keys[0].option_id:
            entry["optionId"] = keys[0].option_id
        entries.append(entry)
    return entries


# --- lifecycle -----------------------------------------------------------------


def test_starting_an_attempt_sets_a_server_side_deadline(seeded_content, client, user):
    response = start(client, **auth(client))
    body = response.json()

    assert response.status_code == 201
    assert body["testId"] == SLUG
    # 20 minutes plus the grace window; the client never decides this.
    assert 1200 <= body["secondsRemaining"] <= 1215


def test_restarting_resumes_the_open_attempt_rather_than_resetting_the_clock(
    seeded_content, client, user
):
    headers = auth(client)
    first = start(client, **headers).json()
    second = start(client, **headers).json()

    assert first["id"] == second["id"]
    assert TestAttempt.objects.filter(user=user, test__slug=SLUG).count() == 1


def test_an_unpublished_test_cannot_be_started(seeded_content, client, user):
    Test.objects.filter(slug=SLUG).update(status="draft")
    try:
        assert start(client, **auth(client)).status_code == 404
    finally:
        Test.objects.filter(slug=SLUG).update(status="published")


# --- autosave ------------------------------------------------------------------


def test_answers_autosave_and_are_idempotent(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    question = Question.objects.filter(test__slug=SLUG).first()
    url = reverse("api:attempts:save", args=[attempt_id])

    for _ in range(3):
        response = client.patch(
            url,
            {"answers": [{"questionId": question.id, "value": "TRUE"}]},
            content_type="application/json",
            **headers,
        )

    assert response.status_code == 200
    assert TestAttempt.objects.get(pk=attempt_id).answers.count() == 1


def test_answers_for_another_test_are_ignored(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    foreign = Question.objects.exclude(test__slug=SLUG).first()

    response = client.patch(
        reverse("api:attempts:save", args=[attempt_id]),
        {"answers": [{"questionId": foreign.id, "value": "TRUE"}]},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    assert response.json()["saved"] == 0


def test_a_submitted_attempt_refuses_further_answers(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    question = Question.objects.filter(test__slug=SLUG).first()
    response = client.patch(
        reverse("api:attempts:save", args=[attempt_id]),
        {"answers": [{"questionId": question.id, "value": "TRUE"}]},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 409


# --- scoring -------------------------------------------------------------------


def test_a_perfect_attempt_scores_full_marks(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    client.patch(
        reverse("api:attempts:save", args=[attempt_id]),
        {"answers": correct_answers()},
        content_type="application/json",
        **headers,
    )

    body = client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers).json()

    assert body["rawScore"] == 12
    assert body["rawTotal"] == 12
    assert body["percent"] == "100.00"


def test_an_empty_attempt_scores_zero(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    body = client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers).json()

    assert body["rawScore"] == 0
    assert body["rawTotal"] == 12


def test_gap_answers_tolerate_case_and_padding(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    gap = Question.objects.filter(test__slug=SLUG, group__type="gap").first()
    expected = gap.answer_keys.first().value

    client.patch(
        reverse("api:attempts:save", args=[attempt_id]),
        {"answers": [{"questionId": gap.id, "value": f"  {expected.upper()}  "}]},
        content_type="application/json",
        **headers,
    )
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    answer = TestAttempt.objects.get(pk=attempt_id).answers.get(question=gap)
    assert answer.is_correct


def test_submission_reports_a_band_range_not_a_false_precision(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    body = client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers).json()

    assert body["bandConfidence"] == "low"
    assert body["bandIsEstimate"] is True
    assert body["bandRange"] is not None
    # Raw numbers always travel with the band so the UI can be honest.
    assert body["rawScore"] is not None and body["rawTotal"] is not None


def test_submit_response_withholds_the_per_question_breakdown(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    body = client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers).json()

    assert "questions" not in body
    assert "correctAnswers" not in str(body)
    assert body["reviewUrl"].endswith(f"/attempts/{attempt_id}/review/")


# --- the clock -----------------------------------------------------------------


def test_submitting_after_the_deadline_is_accepted_but_flagged(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    with time_machine.travel(timezone.now() + timezone.timedelta(minutes=25)):
        # Mint the token inside the jump: the 15-minute access token would
        # otherwise have expired before the 20-minute test deadline.
        response = client.post(
            reverse("api:attempts:submit", args=[attempt_id]), **auth(client)
        )

    assert response.status_code == 200
    # Refusing would throw away 20 minutes of work over a slow network.
    assert response.json()["status"] == AttemptStatus.EXPIRED


def test_expire_stale_attempts_closes_abandoned_sittings(seeded_content, client, user):
    from apps.attempts.services import expire_stale_attempts

    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    with time_machine.travel(timezone.now() + timezone.timedelta(hours=2)):
        closed = expire_stale_attempts()

    assert closed >= 1
    assert TestAttempt.objects.get(pk=attempt_id).status == AttemptStatus.EXPIRED


# --- review and ownership ------------------------------------------------------


def test_review_is_the_only_place_correct_answers_appear(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    body = client.get(reverse("api:attempts:review", args=[attempt_id]), **headers).json()

    assert len(body["questions"]) == 12
    assert all(q["correctAnswers"] for q in body["questions"])


def test_review_before_submission_is_refused(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    response = client.get(reverse("api:attempts:review", args=[attempt_id]), **headers)

    assert response.status_code == 409


def test_another_user_cannot_read_an_attempt(seeded_content, client, user, staff_user):
    from django.contrib.auth import get_user_model

    owner_headers = auth(client)
    attempt_id = start(client, **owner_headers).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **owner_headers)

    get_user_model().objects.create_user(email="other@example.com", password="pw-test-1234")
    other = client.__class__()
    other_headers = auth(other, email="other@example.com")

    response = other.get(reverse("api:attempts:review", args=[attempt_id]), **other_headers)

    # 404, not 403: confirming the attempt exists would leak that the id is real.
    assert response.status_code == 404


def test_an_anonymous_caller_cannot_read_someone_elses_attempt(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    anon = client.__class__()
    assert anon.get(reverse("api:attempts:review", args=[attempt_id])).status_code == 404


def test_attempt_responses_are_never_shared_cacheable(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]

    response = client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    assert "no-store" in response["Cache-Control"]


# --- guests --------------------------------------------------------------------


def test_a_guest_can_take_a_test_without_an_account(seeded_content, client):
    response = start(client)

    assert response.status_code == 201
    attempt = TestAttempt.objects.get(pk=response.json()["id"])
    assert attempt.user_id is None
    assert attempt.guest_id is not None


def test_a_guest_keeps_their_attempt_across_requests(seeded_content, client):
    first = start(client).json()["id"]
    second = start(client).json()["id"]

    assert first == second, "the guest cookie should identify the same visitor"


def test_signing_up_claims_the_guest_attempt(seeded_content, client):
    attempt_id = start(client).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]))

    client.post(
        reverse("api:auth:register"),
        {"email": "claimer@example.com", "password": "pw-test-abcd-1234"},
        content_type="application/json",
    )
    headers = auth(client, email="claimer@example.com", password="pw-test-abcd-1234")
    claimed = client.post(reverse("api:attempts:claim"), **headers).json()

    attempt = TestAttempt.objects.get(pk=attempt_id)
    assert claimed["claimed"] == 1
    assert attempt.user.email == "claimer@example.com"
    assert attempt.guest_id is None


def test_history_lists_only_the_callers_own_attempts(seeded_content, client, user):
    headers = auth(client)
    attempt_id = start(client, **headers).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    body = client.get(reverse("api:attempts:mine"), **headers).json()

    assert body["count"] == 1
    assert body["results"][0]["testId"] == SLUG


def test_history_requires_authentication(seeded_content, client):
    assert client.get(reverse("api:attempts:mine")).status_code == 401


def test_answer_keys_are_still_absent_from_the_delivery_payload(seeded_content, client):
    """The whole point of server-side scoring: the client never sees the key."""
    body = client.get(reverse("api:test-detail", args=[SLUG])).json()
    blob = str(body)

    gap_keys = AnswerKey.objects.filter(
        question__test__slug=SLUG, question__group__type="gap"
    )
    assert gap_keys.exists()
    assert "correctAnswers" not in blob
    assert "answer" not in blob
