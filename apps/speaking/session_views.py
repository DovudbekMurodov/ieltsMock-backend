"""Speaking practice sessions.

Nothing here is scored -- speaking cannot be marked from timings. What is
recorded is whether the parts were attempted and how much of the allowance was
used, which is what tells staff that a cue card is unclear or a topic is too
hard.
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.guest import ensure_guest_id, read_guest_id, set_guest_cookie
from apps.analytics import events
from apps.analytics.tracking import record
from apps.common.models import PublishStatus
from apps.common.throttles import AnonWriteThrottle, WriteThrottle

from .models import SpeakingSession, SpeakingTopic


class StartSessionSerializer(serializers.Serializer):
    topicId = serializers.SlugField()


class UpdateSessionSerializer(serializers.Serializer):
    partsCompleted = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=3), required=False
    )
    prepUsedSeconds = serializers.IntegerField(required=False, min_value=0)
    speakUsedSeconds = serializers.IntegerField(required=False, min_value=0)
    selfRating = serializers.IntegerField(required=False, min_value=1, max_value=5)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    complete = serializers.BooleanField(required=False)


def _serialize(session) -> dict:
    return {
        "id": session.id,
        "topicId": session.topic.slug,
        "partsCompleted": sorted(session.parts_completed),
        "prepUsedSeconds": session.prep_used_seconds,
        "speakUsedSeconds": session.speak_used_seconds,
        "selfRating": session.self_rating,
        "notes": session.notes,
        "isComplete": session.is_complete,
        "completedAt": session.completed_at,
    }


def _owned(request, pk) -> SpeakingSession:
    from django.http import Http404

    session = get_object_or_404(SpeakingSession.objects.select_related("topic"), pk=pk)
    user = request.user if request.user.is_authenticated else None
    if not session.owned_by(user=user, guest_id=read_guest_id(request)):
        raise Http404
    return session


@extend_schema(
    operation_id="startSpeakingSession",
    summary="Start a speaking practice session",
    request=StartSessionSerializer,
    responses={201: dict},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonWriteThrottle, WriteThrottle])
def start(request):
    serializer = StartSessionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    topic = get_object_or_404(
        SpeakingTopic.objects.filter(status=PublishStatus.PUBLISHED),
        slug=serializer.validated_data["topicId"],
    )
    user = request.user if request.user.is_authenticated else None
    guest_id = None if user else ensure_guest_id(request)

    session = SpeakingSession.objects.create(topic=topic, user=user, guest_id=guest_id)
    response = Response(_serialize(session), status=status.HTTP_201_CREATED)
    if guest_id:
        set_guest_cookie(response, guest_id)
    return response


@extend_schema(
    operation_id="updateSpeakingSession",
    summary="Record progress through a session",
    request=UpdateSessionSerializer,
    responses={200: dict},
)
@api_view(["PATCH"])
@permission_classes([AllowAny])
@throttle_classes([AnonWriteThrottle, WriteThrottle])
def update(request, pk):
    session = _owned(request, pk)
    serializer = UpdateSessionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    if "partsCompleted" in data:
        # Union, not replace: parts are reported as they finish, and a retry
        # must not erase what came before.
        session.parts_completed = sorted(set(session.parts_completed) | set(data["partsCompleted"]))
    for field, key in [
        ("prep_used_seconds", "prepUsedSeconds"),
        ("speak_used_seconds", "speakUsedSeconds"),
        ("self_rating", "selfRating"),
        ("notes", "notes"),
    ]:
        if key in data:
            setattr(session, field, data[key])

    if data.get("complete") and session.completed_at is None:
        session.completed_at = timezone.now()
        record(
            events.SPEAKING_SESSION_COMPLETED,
            user=session.user,
            anon_id=session.guest_id,
            obj=session.topic,
            object_type="speakingtopic",
            skill="speaking",
            props={
                "parts": len(session.parts_completed),
                "speakUsedSeconds": session.speak_used_seconds,
            },
            request=request,
        )

    session.save()
    return Response(_serialize(session))


@extend_schema(
    operation_id="listMySpeakingSessions",
    summary="This user's speaking history",
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mine(request):
    sessions = (
        SpeakingSession.objects.filter(user=request.user)
        .select_related("topic")
        .order_by("-created_at")[:100]
    )
    results = [_serialize(s) for s in sessions]
    return Response({"count": len(results), "results": results})
