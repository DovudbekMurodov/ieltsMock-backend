import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone

from apps.vocabulary.models import VocabularyReviewEvent, VocabularyReviewState, VocabularyWord
from apps.vocabulary.srs import MAX_INTERVAL_DAYS, next_interval

pytestmark = pytest.mark.django_db


def auth(client, email="student@example.com", password="pw-test-1234"):
    body = client.post(
        reverse("api:auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {body['access']}"}


# --- the algorithm, ported verbatim from the frontend --------------------------


@pytest.mark.parametrize(
    "current,rating,expected",
    [
        (1, "again", 1),
        (8, "again", 1),
        (1, "hard", 2),
        (8, "hard", 9),
        (1, "good", 2),
        (8, "good", 16),
        (1, "easy", 3),
        (8, "easy", 24),
    ],
)
def test_interval_matches_the_frontend_algorithm(current, rating, expected):
    assert next_interval(current, rating) == expected


@pytest.mark.parametrize("rating", ["good", "easy"])
def test_multiplying_ratings_are_capped(rating):
    assert next_interval(50, rating) == MAX_INTERVAL_DAYS


def test_hard_only_adds_a_day_and_still_respects_the_cap():
    assert next_interval(50, "hard") == 51
    assert next_interval(MAX_INTERVAL_DAYS, "hard") == MAX_INTERVAL_DAYS


def test_intervals_never_drop_below_a_day():
    assert next_interval(0, "good") == 1


def test_an_unknown_rating_is_rejected():
    with pytest.raises(ValueError, match="Unknown rating"):
        next_interval(1, "mediocre")


# --- the queue -----------------------------------------------------------------


def test_every_word_is_due_before_it_has_been_seen(seeded_content, client, user):
    body = client.get(reverse("api:srs-due"), {"limit": 200}, **auth(client)).json()

    assert body["count"] == VocabularyWord.objects.count() == 100
    assert body["results"][0]["exampleParts"]


def test_the_queue_requires_authentication(seeded_content, client):
    assert client.get(reverse("api:srs-due")).status_code == 401


def test_rating_a_word_reschedules_it_out_of_the_queue(seeded_content, client, user):
    headers = auth(client)
    word_id = client.get(reverse("api:srs-due"), **headers).json()["results"][0]["id"]

    response = client.post(
        reverse("api:srs-rate"),
        {"wordId": word_id, "rating": "good"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    assert response.json()["intervalDays"] == 2

    remaining = client.get(reverse("api:srs-due"), {"limit": 200}, **headers).json()
    assert word_id not in [w["id"] for w in remaining["results"]]


def test_a_rated_word_returns_when_it_falls_due(seeded_content, client, user):
    headers = auth(client)
    word_id = client.get(reverse("api:srs-due"), **headers).json()["results"][0]["id"]
    client.post(
        reverse("api:srs-rate"),
        {"wordId": word_id, "rating": "good"},
        content_type="application/json",
        **headers,
    )

    with time_machine.travel(timezone.now() + timezone.timedelta(days=3)):
        body = client.get(reverse("api:srs-due"), {"limit": 200}, **auth(client)).json()

    assert word_id in [w["id"] for w in body["results"]]


def test_again_records_a_lapse_and_resets_the_interval(seeded_content, client, user):
    headers = auth(client)
    word = VocabularyWord.objects.first()

    for rating in ("good", "good", "again"):
        client.post(
            reverse("api:srs-rate"),
            {"wordId": word.id, "rating": rating},
            content_type="application/json",
            **headers,
        )

    state = VocabularyReviewState.objects.get(user=user, word=word)
    assert state.interval_days == 1
    assert state.lapses == 1
    assert state.reps == 3
    assert VocabularyReviewEvent.objects.filter(user=user, word=word).count() == 3


def test_an_invalid_rating_is_rejected(seeded_content, client, user):
    word = VocabularyWord.objects.first()
    response = client.post(
        reverse("api:srs-rate"),
        {"wordId": word.id, "rating": "sort-of"},
        content_type="application/json",
        **auth(client),
    )

    assert response.status_code == 400


# --- migrating out of localStorage ---------------------------------------------


def test_import_resolves_the_frontends_composite_keys(seeded_content, client, user):
    word = VocabularyWord.objects.select_related("section").first()
    key = f"{word.section.slug}::{word.headword}"
    due_ms = int((timezone.now() + timezone.timedelta(days=9)).timestamp() * 1000)

    response = client.post(
        reverse("api:srs-import"),
        {"states": {key: {"intervalDays": 8, "dueAt": due_ms}}},
        content_type="application/json",
        **auth(client),
    )

    assert response.json() == {"imported": 1, "skipped": []}
    state = VocabularyReviewState.objects.get(user=user, word=word)
    assert state.interval_days == 8


def test_import_reports_keys_it_cannot_resolve(seeded_content, client, user):
    response = client.post(
        reverse("api:srs-import"),
        {"states": {"no-such-section::Nonexistent": {"intervalDays": 4, "dueAt": 0}}},
        content_type="application/json",
        **auth(client),
    )

    body = response.json()
    assert body["imported"] == 0
    assert body["skipped"] == ["no-such-section::Nonexistent"]


def test_reimporting_keeps_the_later_due_date(seeded_content, client, user):
    """A stale second import must not pull work forward."""
    headers = auth(client)
    word = VocabularyWord.objects.select_related("section").first()
    key = f"{word.section.slug}::{word.headword}"

    far = int((timezone.now() + timezone.timedelta(days=30)).timestamp() * 1000)
    near = int((timezone.now() + timezone.timedelta(days=2)).timestamp() * 1000)

    for due in (far, near):
        client.post(
            reverse("api:srs-import"),
            {"states": {key: {"intervalDays": 5, "dueAt": due}}},
            content_type="application/json",
            **headers,
        )

    state = VocabularyReviewState.objects.get(user=user, word=word)
    assert state.due_at > timezone.now() + timezone.timedelta(days=20)
