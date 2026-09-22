from datetime import timedelta

import pytest
import time_machine
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.analytics import events
from apps.analytics.models import DailyMetric, Event, QuestionStat, TestStat, UserProgress
from apps.analytics.rollups import rollup_for, rollup_user_progress
from apps.analytics.tracking import hash_ip, record, ua_family
from apps.attempts.models import TestAttempt
from apps.content.models import Question

pytestmark = pytest.mark.django_db
User = get_user_model()


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
        User.objects.create_user(email="an@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


# --- what gets recorded --------------------------------------------------------


def test_only_known_event_names_are_stored():
    assert record(events.TEST_SUBMITTED) is not None
    assert record("something.invented") is None
    assert Event.objects.count() == 1


def test_ip_addresses_are_hashed_never_stored():
    digest = hash_ip("203.0.113.9")

    assert len(digest) == 64
    assert "203.0.113.9" not in digest
    # Salted with SECRET_KEY, so the table is not a rainbow-table lookup away
    # from the raw addresses.
    assert digest != hash_ip("203.0.113.10")


def test_no_address_hashes_to_empty():
    assert hash_ip(None) == ""


@pytest.mark.parametrize(
    "agent,expected",
    [
        ("Mozilla/5.0 Chrome/120.0 Safari/537.36", "Chrome"),
        ("Mozilla/5.0 Firefox/121.0", "Firefox"),
        ("Mozilla/5.0 Version/17.0 Safari/605.1", "Safari"),
        ("Mozilla/5.0 Chrome/120 Edg/120", "Edge"),
        ("curl/8.4.0", "Other"),
        (None, ""),
    ],
)
def test_user_agents_are_reduced_to_a_family(agent, expected):
    """The full string is itself a fingerprint; only the family is kept."""
    assert ua_family(agent) == expected


def test_starting_and_submitting_a_test_records_events(seeded_content, client, user):
    headers = auth(client)
    attempt_id = client.post(
        reverse("api:attempts:start"),
        {"testId": "twilight-zone"},
        content_type="application/json",
        **headers,
    ).json()["id"]
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)

    names = list(Event.objects.values_list("name", flat=True))
    assert events.TEST_STARTED in names
    assert events.TEST_SUBMITTED in names

    submitted = Event.objects.get(name=events.TEST_SUBMITTED)
    assert submitted.props["rawTotal"] == 12
    assert submitted.skill == "reading"


def test_a_late_submission_is_recorded_as_expired(seeded_content, client, user):
    headers = auth(client)
    attempt_id = client.post(
        reverse("api:attempts:start"),
        {"testId": "twilight-zone"},
        content_type="application/json",
        **headers,
    ).json()["id"]

    with time_machine.travel(timezone.now() + timedelta(minutes=30)):
        client.post(reverse("api:attempts:submit", args=[attempt_id]), **auth(client))

    assert Event.objects.filter(name=events.TEST_EXPIRED).exists()


def test_signing_up_and_signing_in_are_recorded(seeded_content, client):
    client.post(
        reverse("api:auth:register"),
        {"email": "tracked@example.com", "password": "pw-test-abcd-1234"},
        content_type="application/json",
    )
    auth(client, email="tracked@example.com", password="pw-test-abcd-1234")

    assert Event.objects.filter(name=events.AUTH_SIGNUP).count() == 1
    assert Event.objects.filter(name=events.AUTH_LOGIN).count() == 1


def test_rating_a_word_is_recorded(seeded_content, client, user):
    from apps.vocabulary.models import VocabularyWord

    word = VocabularyWord.objects.first()
    client.post(
        reverse("api:srs-rate"),
        {"wordId": word.id, "rating": "good"},
        content_type="application/json",
        **auth(client),
    )

    event = Event.objects.get(name=events.VOCAB_RATED)
    assert event.props["rating"] == "good"


# --- the client endpoint -------------------------------------------------------


def test_the_client_can_record_a_whitelisted_event(client):
    response = client.post(
        reverse("api:event-record"),
        {"name": events.PAGE_VIEWED, "props": {"route": "/tests"}},
        content_type="application/json",
    )

    assert response.status_code == 202
    assert Event.objects.get().props["route"] == "/tests"


def test_the_client_cannot_record_server_side_events(client):
    """Otherwise a browser could forge a submission and poison the numbers."""
    response = client.post(
        reverse("api:event-record"),
        {"name": events.TEST_SUBMITTED},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not Event.objects.exists()


def test_the_client_cannot_invent_event_names(client):
    response = client.post(
        reverse("api:event-record"),
        {"name": "free.text.name"},
        content_type="application/json",
    )

    assert response.status_code == 400


def test_props_are_capped_and_flattened(client):
    response = client.post(
        reverse("api:event-record"),
        {
            "name": events.PAGE_VIEWED,
            "props": {"nested": {"no": "dicts"}},
        },
        content_type="application/json",
    )

    assert response.status_code == 400


def test_too_many_props_are_rejected(client):
    response = client.post(
        reverse("api:event-record"),
        {"name": events.PAGE_VIEWED, "props": {f"k{i}": i for i in range(20)}},
        content_type="application/json",
    )

    assert response.status_code == 400


def test_long_prop_values_are_truncated_rather_than_rejected(client):
    client.post(
        reverse("api:event-record"),
        {"name": events.PAGE_VIEWED, "props": {"route": "x" * 5000}},
        content_type="application/json",
    )

    assert len(Event.objects.get().props["route"]) == 200


# --- rollups -------------------------------------------------------------------


@pytest.fixture
def submitted_attempt(seeded_content, client, user):
    headers = auth(client)
    attempt_id = client.post(
        reverse("api:attempts:start"),
        {"testId": "twilight-zone"},
        content_type="application/json",
        **headers,
    ).json()["id"]
    question = Question.objects.filter(test__slug="twilight-zone", group__type="tfng").first()
    client.patch(
        reverse("api:attempts:save", args=[attempt_id]),
        {"answers": [{"questionId": question.id, "value": question.answer_keys.first().value}]},
        content_type="application/json",
        **headers,
    )
    client.post(reverse("api:attempts:submit", args=[attempt_id]), **headers)
    return TestAttempt.objects.get(pk=attempt_id)


def test_rollup_writes_daily_metrics(submitted_attempt):
    today = timezone.now().date()

    rollup_for(today)

    assert DailyMetric.objects.get(
        date=today, metric_key="attempts.submitted", dimension_key=""
    ).value_int == 1
    assert DailyMetric.objects.get(
        date=today, metric_key="attempts.submitted", dimension_key="reading"
    ).value_int == 1


def test_rollup_is_idempotent(submitted_attempt):
    today = timezone.now().date()

    rollup_for(today)
    before = DailyMetric.objects.count()
    rollup_for(today)

    assert DailyMetric.objects.count() == before
    assert DailyMetric.objects.get(
        date=today, metric_key="attempts.submitted", dimension_key=""
    ).value_int == 1


def test_rollup_records_per_question_accuracy(submitted_attempt):
    today = timezone.now().date()

    rollup_for(today)

    stat = QuestionStat.objects.filter(date=today).first()
    assert stat is not None
    assert stat.seen == 1
    assert stat.accuracy in (0, 100)


def test_rollup_records_test_stats(submitted_attempt):
    today = timezone.now().date()

    rollup_for(today)

    stat = TestStat.objects.get(test__slug="twilight-zone", date=today)
    assert stat.completions == 1
    assert stat.median_duration_s is not None


def test_user_progress_tracks_best_and_latest(submitted_attempt, user):
    rollup_user_progress()

    progress = UserProgress.objects.get(user=user, skill="reading")
    assert progress.attempts == 1
    assert progress.last_active_at is not None


def test_the_management_command_backfills_a_range(submitted_attempt):
    call_command("rollup_metrics", "--since", str(timezone.now().date()), "--include-today")

    assert DailyMetric.objects.filter(date=timezone.now().date()).exists()


def test_the_management_command_rejects_a_bad_date():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="not a YYYY-MM-DD"):
        call_command("rollup_metrics", "--date", "yesterday")


def test_pruning_removes_only_old_events():
    old = record(events.PAGE_VIEWED)
    Event.objects.filter(pk=old.pk).update(occurred_at=timezone.now() - timedelta(days=400))
    recent = record(events.PAGE_VIEWED)

    call_command("prune_events", "--days", "180")

    assert not Event.objects.filter(pk=old.pk).exists()
    assert Event.objects.filter(pk=recent.pk).exists()


def test_prune_dry_run_deletes_nothing():
    old = record(events.PAGE_VIEWED)
    Event.objects.filter(pk=old.pk).update(occurred_at=timezone.now() - timedelta(days=400))

    call_command("prune_events", "--days", "180", "--dry-run")

    assert Event.objects.filter(pk=old.pk).exists()


# --- the pages -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["dashboard:analytics", "dashboard:question-analysis"]
)
def test_analytics_pages_render(seeded_content, staff_client, name):
    assert staff_client.get(reverse(name)).status_code == 200


def test_analytics_page_says_so_when_there_are_no_rollups(seeded_content, staff_client):
    html = staff_client.get(reverse("dashboard:analytics")).content.decode()

    assert "No rollups yet" in html


def test_test_analytics_page_renders(seeded_content, staff_client):
    response = staff_client.get(reverse("dashboard:test-analytics", args=["twilight-zone"]))

    assert response.status_code == 200


def test_analytics_pages_are_staff_only(seeded_content, client, user):
    client.force_login(user)

    assert client.get(reverse("dashboard:analytics")).status_code == 404
    assert client.get(reverse("dashboard:question-analysis")).status_code == 404


def test_the_dashboard_overview_query_count_does_not_grow_with_events(
    submitted_attempt, staff_client, django_assert_max_num_queries
):
    for _ in range(50):
        record(events.PAGE_VIEWED)

    with django_assert_max_num_queries(30):
        staff_client.get(reverse("dashboard:analytics"))
