from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.middleware import cache_public
from apps.common.models import PublishStatus

from .models import WritingTask
from .publishing import build_task_payload, model_answers_visible

MAX_AGE = 300


def _published():
    return WritingTask.objects.filter(status=PublishStatus.PUBLISHED)


@extend_schema(operation_id="listWritingTasks",
    summary="List published writing tasks",
    responses={200: dict},)
@api_view(["GET"])
@permission_classes([AllowAny])
def task_list(request):
    tasks = _published().order_by("task_number", "slug")
    results = [build_task_payload(t, include_model_answers=False) for t in tasks]
    response = Response({"count": len(results), "results": results})
    return cache_public(response, max_age=MAX_AGE)


@extend_schema(
    operation_id="getWritingTask",
    summary="Fetch one writing task",
    description=(
        "Model answers are included only when the task's reveal policy allows it "
        "before submission."
    ),
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def task_detail(request, slug):
    task = get_object_or_404(_published().prefetch_related("model_answers"), slug=slug)
    payload = build_task_payload(task, include_model_answers=model_answers_visible(task))
    response = Response(payload)
    return cache_public(response, max_age=MAX_AGE)
