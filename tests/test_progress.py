from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone

from apps.attempts.models import AttemptStatus, TestAttempt
from apps.content.models import Question, Test

pytestmark = pytest.mark.django_db

SLUG = "twilight-zone"


def auth(client, email="student@example.com", password="pw-test-1234"):
    body = client.post(
        reverse("api:auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {body['access']}"}


def progress(client, **extra):
    return client.get(reverse("api:my-progress"), **extra)


def submit_attempt(user, slug=SLUG, *, band, percent, when=None):
    """A finished attempt, written directly so the test controls the numbers."""
    test = Test.objects.get(slug=slug)
    total = Question.objects.filter(test=test).count()
    return TestAttempt.objects.create(
        user=user,
        test=test,
        status=AttemptStatus.SUBMITTED,
        raw_score=int(total * Decimal(percent) / 100),
        raw_total=total,
        percent=percent,
        band=band,
        band_confidence="low",
        submitted_at=when or timezone.now(),
        expires_at=when or timezone.now(),
    )


def test_progress_requires_authentication(client):
    assert progress(client).status_code == 401


def test_progress_is_empty_for_a_new_account(client, django_user_model):
    django_user_model.objects.create_user(email="student@example.com", password="pw-test-1234")
    body = progress(client, **auth(client)).json()

    assert body["streakDays"] == 0
    assert body["accuracy"] is None
    assert body["overallBand"] is None
    assert body["skills"] == []
    assert body["contributingSkills"] == []


def test_progress_summarises_attempts_per_skill(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    submit_attempt(user, band="6.0", percent="60.00")
    submit_attempt(user, band="7.0", percent="80.00")

    body = progress(client, **auth(client)).json()
    reading = next(s for s in body["skills"] if s["skill"] == "reading")

    assert reading["attempts"] == 2
    assert reading["bestBand"] == "7.0"
    # Decimals cross the wire as strings here, as they do everywhere else in
    # this API; the client parses rather than guessing.
    assert reading["avgPercent"] == "70.00"
    assert body["accuracy"] == "70.00"


def test_in_progress_attempts_do_not_count(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    submit_attempt(user, band="6.0", percent="60.00")
    TestAttempt.objects.create(
        user=user,
        test=Test.objects.get(slug=SLUG),
        status=AttemptStatus.IN_PROGRESS,
        expires_at=timezone.now(),
    )

    body = progress(client, **auth(client)).json()
    assert body["totalAttempts"] == 1


def test_overall_band_is_flagged_partial_when_skills_are_missing(client, django_user_model):
    """Two skills is not an IELTS overall, and the response has to say so.

    Speaking is never banded by this API and writing only once a human has
    graded it, so a candidate who has only done reading mocks would otherwise
    be shown a two-skill average as though it were an exam result.
    """
    user = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    submit_attempt(user, band="6.5", percent="70.00")

    body = progress(client, **auth(client)).json()

    assert body["overallBand"] == "6.5"
    assert body["overallBandIsPartial"] is True
    assert body["contributingSkills"] == ["reading"]


def test_streak_counts_consecutive_days_ending_today(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    with time_machine.travel("2026-03-10 09:00:00+00:00"):
        submit_attempt(user, band="6.0", percent="60.00")
    with time_machine.travel("2026-03-11 09:00:00+00:00"):
        submit_attempt(user, band="6.0", percent="60.00")
    with time_machine.travel("2026-03-12 09:00:00+00:00"):
        submit_attempt(user, band="6.0", percent="60.00")

        assert progress(client, **auth(client)).json()["streakDays"] == 3


def test_streak_breaks_on_a_missed_day(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    with time_machine.travel("2026-03-08 09:00:00+00:00"):
        submit_attempt(user, band="6.0", percent="60.00")
    with time_machine.travel("2026-03-12 09:00:00+00:00"):
        submit_attempt(user, band="6.0", percent="60.00")

        assert progress(client, **auth(client)).json()["streakDays"] == 1


def test_streak_survives_yesterday_but_not_the_day_before(client, django_user_model):
    """Today has barely started; a streak should not die at midnight."""
    user = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    with time_machine.travel("2026-03-11 09:00:00+00:00"):
        submit_attempt(user, band="6.0", percent="60.00")
    with time_machine.travel("2026-03-12 09:00:00+00:00"):
        assert progress(client, **auth(client)).json()["streakDays"] == 1
    with time_machine.travel("2026-03-13 09:00:00+00:00"):
        assert progress(client, **auth(client)).json()["streakDays"] == 0


def test_one_users_attempts_are_invisible_to_another(client, django_user_model):
    mine = django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )
    theirs = django_user_model.objects.create_user(
        email="other@example.com", password="pw-test-1234"
    )
    submit_attempt(mine, band="6.0", percent="60.00")
    submit_attempt(theirs, band="9.0", percent="100.00")

    body = progress(client, **auth(client)).json()
    assert body["totalAttempts"] == 1
    assert body["accuracy"] == "60.00"
