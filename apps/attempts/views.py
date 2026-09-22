from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.guest import ensure_guest_id, read_guest_id, set_guest_cookie
from apps.common.models import PublishStatus
from apps.common.throttles import AnonWriteThrottle, WriteThrottle
from apps.content.models import Question, Test
from apps.grading import bands

from .models import AttemptStatus, TestAttempt
from .serializers import (
    AttemptResultSerializer,
    AttemptSerializer,
    ClaimSerializer,
    SaveAnswersSerializer,
    StartAttemptSerializer,
)
from .services import (
    AttemptClosed,
    claim_guest_attempts,
    save_answers,
    start_attempt,
    submit_attempt,
)


def _viewer(request):
    user = request.user if request.user.is_authenticated else None
    return user, read_guest_id(request)


def _get_owned_attempt(request, pk) -> TestAttempt:
    """404 rather than 403 for someone else's attempt.

    Telling a caller that an attempt exists but is not theirs leaks that the id
    is real.
    """
    attempt = get_object_or_404(
        TestAttempt.objects.select_related("test", "band_scale"), pk=pk
    )
    user, guest_id = _viewer(request)
    if not attempt.owned_by(user=user, guest_id=guest_id) and not request.user.is_staff:
        from django.http import Http404

        raise Http404
    return attempt


@extend_schema(
    operation_id="startAttempt",
    summary="Start (or resume) an attempt",
    request=StartAttemptSerializer,
    responses={201: AttemptSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonWriteThrottle, WriteThrottle])
def start(request):
    serializer = StartAttemptSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    test = get_object_or_404(
        Test.objects.filter(status=PublishStatus.PUBLISHED),
        slug=serializer.validated_data["testId"],
    )

    user = request.user if request.user.is_authenticated else None
    guest_id = None if user else ensure_guest_id(request)

    attempt = start_attempt(test, user=user, guest_id=guest_id)
    response = Response(AttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)
    if guest_id:
        set_guest_cookie(response, guest_id)
    return response


@extend_schema(
    operation_id="saveAttemptAnswers",
    summary="Autosave answers",
    request=SaveAnswersSerializer,
    responses={200: dict},
)
@api_view(["PATCH"])
@permission_classes([AllowAny])
@throttle_classes([AnonWriteThrottle, WriteThrottle])
def save(request, pk):
    attempt = _get_owned_attempt(request, pk)
    serializer = SaveAnswersSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        saved = save_answers(attempt, serializer.validated_data["answers"])
    except AttemptClosed as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    return Response({"saved": saved, "secondsRemaining": attempt.seconds_remaining})


@extend_schema(
    operation_id="submitAttempt",
    summary="Submit and score an attempt",
    request=None,
    responses={200: AttemptResultSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonWriteThrottle, WriteThrottle])
def submit(request, pk):
    attempt = submit_attempt(_get_owned_attempt(request, pk))

    body = {
        "id": attempt.id,
        "status": attempt.status,
        "rawScore": attempt.raw_score,
        "rawTotal": attempt.raw_total,
        "percent": str(attempt.percent),
        "durationSeconds": attempt.duration_seconds,
        "reviewUrl": f"/api/v1/attempts/{attempt.id}/review/",
        **bands.payload(
            bands.BandEstimate(
                band=attempt.band,
                band_low=attempt.band_low,
                band_high=attempt.band_high,
                confidence=attempt.band_confidence,
                scaled_raw=bands.scale_raw(attempt.raw_score, attempt.raw_total),
                scale_id=attempt.band_scale_id,
            )
        ),
    }
    # Deliberately not the per-question breakdown: scoring and revealing stay
    # two separate, separately auditable operations.
    return Response(body)


@extend_schema(
    operation_id="reviewAttempt",
    summary="Per-question breakdown with correct answers",
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def review(request, pk):
    attempt = _get_owned_attempt(request, pk)
    if attempt.status == AttemptStatus.IN_PROGRESS:
        return Response(
            {"detail": "Submit the attempt before reviewing it."},
            status=status.HTTP_409_CONFLICT,
        )

    questions = (
        Question.objects.filter(test=attempt.test)
        .select_related("group")
        .prefetch_related("answer_keys", "options", "group__options")
        .order_by("number")
    )
    answers = {a.question_id: a for a in attempt.answers.all()}

    items = []
    for question in questions:
        answer = answers.get(question.id)
        keys = list(question.answer_keys.all())
        items.append(
            {
                "questionId": question.id,
                "number": question.number,
                "type": question.group.type,
                "prompt": question.prompt,
                "yourAnswer": answer.raw_value if answer else "",
                "isCorrect": bool(answer and answer.is_correct),
                "correctAnswers": [k.value for k in keys],
                "explanation": question.explanation,
            }
        )

    return Response(
        {
            "id": attempt.id,
            "testId": attempt.test.slug,
            "skill": attempt.test.skill,
            "title": attempt.test.title,
            "status": attempt.status,
            "rawScore": attempt.raw_score,
            "rawTotal": attempt.raw_total,
            "percent": str(attempt.percent) if attempt.percent is not None else None,
            **bands.payload(
                bands.BandEstimate(
                    band=attempt.band,
                    band_low=attempt.band_low,
                    band_high=attempt.band_high,
                    confidence=attempt.band_confidence,
                    scaled_raw=bands.scale_raw(attempt.raw_score or 0, attempt.raw_total or 0),
                    scale_id=attempt.band_scale_id,
                )
            ),
            "questions": items,
        }
    )


@extend_schema(
    operation_id="listMyAttempts", summary="This user's attempt history", responses={200: dict}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_attempts(request):
    attempts = (
        TestAttempt.objects.filter(user=request.user)
        .exclude(status=AttemptStatus.IN_PROGRESS)
        .select_related("test")
        .order_by("-submitted_at")[:100]
    )
    results = [
        {
            "id": a.id,
            "testId": a.test.slug,
            "title": a.test.title,
            "skill": a.test.skill,
            "status": a.status,
            "rawScore": a.raw_score,
            "rawTotal": a.raw_total,
            "band": str(a.band) if a.band is not None else None,
            "bandConfidence": a.band_confidence,
            "submittedAt": a.submitted_at,
            "durationSeconds": a.duration_seconds,
        }
        for a in attempts
    ]
    return Response({"count": len(results), "results": results})


@extend_schema(
    operation_id="claimGuestAttempts",
    summary="Attach guest attempts to the signed-in account",
    request=None,
    responses={200: ClaimSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim(request):
    guest_id = read_guest_id(request)
    claimed = claim_guest_attempts(request.user, guest_id)
    return Response({"claimed": claimed})
