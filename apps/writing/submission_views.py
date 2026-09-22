"""Writing submission API."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.guest import ensure_guest_id, read_guest_id, set_guest_cookie
from apps.analytics import events
from apps.analytics.tracking import record
from apps.common.models import PublishStatus

from .models import (
    RevealPolicy,
    SubmissionStatus,
    WritingSubmission,
    WritingTask,
    count_words,
    mark_submitted,
)
from .publishing import build_task_payload


class StartSubmissionSerializer(serializers.Serializer):
    taskId = serializers.SlugField()


class SaveSubmissionSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=True, max_length=40000)
    timeSpentSeconds = serializers.IntegerField(required=False, min_value=0)
    selfAssessedBand = serializers.DecimalField(
        max_digits=2, decimal_places=1, required=False, allow_null=True
    )


def _serialize(submission) -> dict:
    feedback = getattr(submission, "feedback", None)
    return {
        "id": submission.id,
        "taskId": submission.task.slug,
        "status": submission.status,
        "body": submission.body,
        "wordCount": submission.word_count,
        "targetWords": submission.task.target_words,
        "meetsTarget": submission.meets_target,
        "timeSpentSeconds": submission.time_spent_seconds,
        "submittedAt": submission.submitted_at,
        "selfAssessedBand": (
            str(submission.self_assessed_band)
            if submission.self_assessed_band is not None
            else None
        ),
        "feedback": (
            {
                "taskAchievement": str(feedback.task_achievement),
                "coherenceCohesion": str(feedback.coherence_cohesion),
                "lexicalResource": str(feedback.lexical_resource),
                "grammaticalRange": str(feedback.grammatical_range),
                "overall": str(feedback.overall),
                "comment": feedback.comment,
                "gradedAt": feedback.created_at,
            }
            if feedback
            else None
        ),
    }


def _owned(request, pk) -> WritingSubmission:
    from django.http import Http404

    submission = get_object_or_404(
        WritingSubmission.objects.select_related("task").prefetch_related("feedback"), pk=pk
    )
    user = request.user if request.user.is_authenticated else None
    if not submission.owned_by(user=user, guest_id=read_guest_id(request)) and not (
        request.user.is_authenticated and request.user.is_staff
    ):
        # 404 rather than 403 -- a 403 confirms the id is real.
        raise Http404
    return submission


@extend_schema(
    operation_id="startWritingSubmission",
    summary="Start or resume a writing submission",
    request=StartSubmissionSerializer,
    responses={201: dict},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def start(request):
    serializer = StartSubmissionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    task = get_object_or_404(
        WritingTask.objects.filter(status=PublishStatus.PUBLISHED),
        slug=serializer.validated_data["taskId"],
    )
    user = request.user if request.user.is_authenticated else None
    guest_id = None if user else ensure_guest_id(request)

    owner = {"user": user} if user else {"user__isnull": True, "guest_id": guest_id}
    submission = (
        WritingSubmission.objects.filter(
            task=task, status=SubmissionStatus.DRAFT, **owner
        ).first()
        or WritingSubmission.objects.create(task=task, user=user, guest_id=guest_id)
    )

    response = Response(_serialize(submission), status=status.HTTP_201_CREATED)
    if guest_id:
        set_guest_cookie(response, guest_id)
    return response


@extend_schema(
    operation_id="saveWritingSubmission",
    summary="Autosave a draft",
    request=SaveSubmissionSerializer,
    responses={200: dict},
)
@api_view(["PATCH"])
@permission_classes([AllowAny])
def save(request, pk):
    submission = _owned(request, pk)
    if submission.status != SubmissionStatus.DRAFT:
        return Response(
            {"detail": "This submission has already been sent for feedback."},
            status=status.HTTP_409_CONFLICT,
        )

    serializer = SaveSubmissionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    submission.body = data["body"]
    submission.word_count = count_words(submission.body)
    submission.time_spent_seconds = data.get(
        "timeSpentSeconds", submission.time_spent_seconds
    )
    if "selfAssessedBand" in data:
        submission.self_assessed_band = data["selfAssessedBand"]
    submission.save()

    return Response(
        {"wordCount": submission.word_count, "meetsTarget": submission.meets_target}
    )


@extend_schema(
    operation_id="submitWriting",
    summary="Send a submission for feedback",
    request=None,
    responses={200: dict},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def submit(request, pk):
    submission = _owned(request, pk)
    if not submission.body.strip():
        return Response({"detail": "Write something first."}, status=400)

    mark_submitted(submission)
    record(
        events.WRITING_SUBMITTED,
        user=submission.user,
        anon_id=submission.guest_id,
        obj=submission.task,
        object_type="writingtask",
        skill="writing",
        props={"wordCount": submission.word_count, "submissionId": submission.id},
        request=request,
    )
    return Response(_serialize(submission))


@extend_schema(
    operation_id="getWritingModelAnswer",
    summary="Reveal the model answer",
    description=(
        "A task set to reveal after submission returns 409 until the student has "
        "submitted their own attempt. The check is server-side so it cannot be "
        "skipped by the client."
    ),
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def model_answer(request, pk):
    submission = _owned(request, pk)
    task = submission.task

    if (
        task.reveal_policy == RevealPolicy.AFTER_SUBMISSION
        and submission.status == SubmissionStatus.DRAFT
    ):
        return Response(
            {"detail": "Submit your own answer first."}, status=status.HTTP_409_CONFLICT
        )

    if submission.model_answer_revealed_at is None:
        submission.model_answer_revealed_at = timezone.now()
        submission.save(update_fields=["model_answer_revealed_at", "updated_at"])

    payload = build_task_payload(task, include_model_answers=True)
    return Response({"modelAnswers": payload["modelAnswers"]})


@extend_schema(
    operation_id="listMyWritingSubmissions",
    summary="This user's writing history",
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mine(request):
    submissions = (
        WritingSubmission.objects.filter(user=request.user)
        .exclude(status=SubmissionStatus.DRAFT)
        .select_related("task")
        .prefetch_related("feedback")
        .order_by("-submitted_at")[:100]
    )
    results = [_serialize(s) for s in submissions]
    return Response({"count": len(results), "results": results})
