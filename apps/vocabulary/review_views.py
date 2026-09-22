"""Spaced-repetition endpoints."""

from datetime import UTC, datetime

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.models import PublishStatus

from .models import VocabularyReviewEvent, VocabularyReviewState, VocabularyWord
from .publishing import build_word
from .srs import RATINGS, due_at, next_interval

DEFAULT_QUEUE_LIMIT = 40


class RateSerializer(serializers.Serializer):
    wordId = serializers.IntegerField()
    rating = serializers.ChoiceField(choices=RATINGS)


class ImportSerializer(serializers.Serializer):
    """The raw localStorage blob, keyed by "<sectionSlug>::<headword>"."""

    states = serializers.DictField(child=serializers.DictField())


@extend_schema(operation_id="listDueWords", summary="Words due for review", responses={200: dict})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def due_queue(request):
    now = timezone.now()
    states = {
        s.word_id: s
        for s in VocabularyReviewState.objects.filter(user=request.user).only(
            "word_id", "due_at", "interval_days"
        )
    }

    words = (
        VocabularyWord.objects.filter(section__status=PublishStatus.PUBLISHED)
        .select_related("section")
        .order_by("section__order", "order")
    )

    due = []
    for word in words:
        state = states.get(word.id)
        # A word never seen before is due immediately.
        if state is None or state.due_at <= now:
            payload = build_word(word)
            payload["sectionId"] = word.section.slug
            payload["intervalDays"] = state.interval_days if state else 0
            due.append(payload)

    limit = min(int(request.query_params.get("limit", DEFAULT_QUEUE_LIMIT)), 200)
    return Response({"count": len(due), "results": due[:limit]})


@extend_schema(
    operation_id="rateWord",
    summary="Record a review and reschedule the word",
    request=RateSerializer,
    responses={200: dict},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def rate(request):
    serializer = RateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    word = get_object_or_404(VocabularyWord, pk=serializer.validated_data["wordId"])
    rating = serializer.validated_data["rating"]

    state, _ = VocabularyReviewState.objects.get_or_create(user=request.user, word=word)
    before = state.interval_days
    after = next_interval(before, rating)

    state.interval_days = after
    state.due_at = due_at(after)
    state.reps += 1
    state.lapses += rating == "again"
    state.last_rating = rating
    state.last_reviewed_at = timezone.now()
    state.save()

    VocabularyReviewEvent.objects.create(
        user=request.user,
        word=word,
        rating=rating,
        interval_before=before,
        interval_after=after,
    )

    return Response({"wordId": word.id, "intervalDays": after, "dueAt": state.due_at})


@extend_schema(
    operation_id="importSrsState",
    summary="Import spaced-repetition state from the browser",
    description=(
        "Accepts the frontend's localStorage blob so an existing user's schedule "
        "survives the move to server-side storage. Idempotent: re-importing keeps "
        "whichever due date is later."
    ),
    request=ImportSerializer,
    responses={200: dict},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def import_state(request):
    serializer = ImportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    words = {
        f"{w.section.slug}::{w.headword}": w
        for w in VocabularyWord.objects.select_related("section")
    }

    imported, skipped = 0, []
    for key, value in serializer.validated_data["states"].items():
        word = words.get(key)
        if word is None:
            skipped.append(key)
            continue

        interval = max(1, min(60, int(value.get("intervalDays", 1) or 1)))
        due = value.get("dueAt")
        due_dt = (
            datetime.fromtimestamp(int(due) / 1000, tz=UTC)
            if due
            else timezone.now()
        )

        state, created = VocabularyReviewState.objects.get_or_create(
            user=request.user,
            word=word,
            defaults={"interval_days": interval, "due_at": due_dt},
        )
        if not created and due_dt > state.due_at:
            # Keep the later date so a stale import cannot pull work forward.
            state.interval_days = interval
            state.due_at = due_dt
            state.save(update_fields=["interval_days", "due_at"])
        imported += 1

    return Response(
        {"imported": imported, "skipped": skipped}, status=status.HTTP_200_OK
    )
