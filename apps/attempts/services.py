"""Attempt lifecycle. All timing decisions are made server-side."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.analytics import events
from apps.analytics.tracking import record
from apps.content.models import Option, Question
from apps.grading import bands
from apps.grading.scoring import score_attempt

from .models import AttemptAnswer, AttemptStatus, TestAttempt

# A submit that arrives slightly late is almost always a slow network rather
# than cheating, so accept it silently within the grace window.
GRACE_SECONDS = 15


class AttemptClosed(RuntimeError):
    pass


@transaction.atomic
def start_attempt(test, *, user=None, guest_id=None) -> TestAttempt:
    """Reuse the caller's open attempt rather than starting a parallel one.

    Reloading the page mid-test must not silently reset the clock, so an
    unexpired attempt is handed straight back.
    """
    signed_in = bool(user and user.is_authenticated)

    owner_filter = (
        {"user": user} if signed_in else {"user__isnull": True, "guest_id": guest_id}
    )
    open_attempt = (
        TestAttempt.objects.filter(
            test=test, status=AttemptStatus.IN_PROGRESS, **owner_filter
        )
        .order_by("-started_at")
        .first()
    )
    if open_attempt and open_attempt.seconds_remaining > 0:
        return open_attempt

    now = timezone.now()
    attempt = TestAttempt.objects.create(
        user=user if signed_in else None,
        guest_id=None if signed_in else guest_id,
        test=test,
        test_version=test.version,
        band_scale=bands.default_scale(test.skill),
        started_at=now,
        expires_at=now + timedelta(minutes=test.time_limit_minutes, seconds=GRACE_SECONDS),
        last_activity_at=now,
    )
    record(
        events.TEST_STARTED,
        user=user,
        anon_id=guest_id,
        obj=test,
        object_type="test",
        skill=test.skill,
    )
    return attempt


@transaction.atomic
def save_answers(attempt, entries: list[dict]) -> int:
    """Upsert answers. Idempotent, so a retried autosave is harmless."""
    if not attempt.is_open:
        raise AttemptClosed("This attempt has already been submitted.")

    questions = {
        q.id: q
        for q in Question.objects.filter(
            test=attempt.test, id__in=[e["questionId"] for e in entries]
        ).select_related("group")
    }

    saved = 0
    for entry in entries:
        question = questions.get(entry["questionId"])
        if question is None:
            continue  # A question from another test is simply ignored.

        option = None
        if entry.get("optionId") is not None:
            option = Option.objects.filter(
                id=entry["optionId"], group=question.group
            ).first()

        AttemptAnswer.objects.update_or_create(
            attempt=attempt,
            question=question,
            defaults={
                "question_number": question.number,
                "question_type": question.group.type,
                "raw_value": (entry.get("value") or "")[:2000],
                "selected_option": option,
                "answered_at": timezone.now(),
                "time_spent_ms": entry.get("timeSpentMs"),
            },
        )
        saved += 1

    TestAttempt.objects.filter(pk=attempt.pk).update(last_activity_at=timezone.now())
    return saved


@transaction.atomic
def submit_attempt(attempt) -> TestAttempt:
    """Score and close. Re-running on a closed attempt re-scores in place."""
    now = timezone.now()
    # A late submit is recorded as such rather than refused -- refusing would
    # throw away the work over a network hiccup.
    late = now > attempt.expires_at

    result = score_attempt(attempt)
    estimate = bands.estimate(result.raw_score, result.raw_total, attempt.band_scale)

    by_question = {o.question_id: o for o in result.outcomes}
    for answer in attempt.answers.all():
        outcome = by_question.get(answer.question_id)
        if outcome:
            answer.is_correct = outcome.is_correct
            answer.normalized_value = outcome.normalized
            answer.save(update_fields=["is_correct", "normalized_value"])

    attempt.status = AttemptStatus.EXPIRED if late else AttemptStatus.SUBMITTED
    attempt.submitted_at = attempt.submitted_at or now
    attempt.duration_seconds = int((attempt.submitted_at - attempt.started_at).total_seconds())
    attempt.raw_score = result.raw_score
    attempt.raw_total = result.raw_total
    attempt.percent = result.percent
    attempt.band = estimate.band
    attempt.band_low = estimate.band_low
    attempt.band_high = estimate.band_high
    attempt.band_confidence = estimate.confidence
    attempt.save()

    record(
        events.TEST_EXPIRED if late else events.TEST_SUBMITTED,
        user=attempt.user,
        anon_id=attempt.guest_id,
        obj=attempt.test,
        object_type="test",
        skill=attempt.test.skill,
        props={
            "attemptId": attempt.id,
            "rawScore": result.raw_score,
            "rawTotal": result.raw_total,
            "band": str(attempt.band) if attempt.band is not None else None,
            "durationSeconds": attempt.duration_seconds,
        },
    )
    return attempt


@transaction.atomic
def claim_guest_attempts(user, guest_id) -> int:
    """Attach a guest's work to their new account."""
    if not guest_id:
        return 0
    return TestAttempt.objects.filter(user__isnull=True, guest_id=guest_id).update(
        user=user, guest_id=None
    )


def expire_stale_attempts(before=None) -> int:
    """Close attempts whose clock ran out and were never submitted."""
    cutoff = before or timezone.now()
    stale = TestAttempt.objects.filter(
        status=AttemptStatus.IN_PROGRESS, expires_at__lt=cutoff
    )
    count = 0
    for attempt in stale:
        submit_attempt(attempt)
        count += 1
    return count
