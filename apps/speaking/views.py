from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.middleware import cache_public
from apps.common.models import PublishStatus

from .models import SpeakingTopic
from .publishing import build_topic_payload

MAX_AGE = 300


def _published():
    return SpeakingTopic.objects.filter(status=PublishStatus.PUBLISHED)


@extend_schema(operation_id="listSpeakingTopics",
    summary="List published speaking topics",
    responses={200: dict},)
@api_view(["GET"])
@permission_classes([AllowAny])
def topic_list(request):
    topics = _published().order_by("order", "title").prefetch_related("items", "cue_card")
    results = [build_topic_payload(t) for t in topics]
    response = Response({"count": len(results), "results": results})
    return cache_public(response, max_age=MAX_AGE)


@extend_schema(operation_id="getSpeakingTopic",
    summary="Fetch one speaking topic",
    responses={200: dict},)
@api_view(["GET"])
@permission_classes([AllowAny])
def topic_detail(request, slug):
    topic = get_object_or_404(_published().prefetch_related("items", "cue_card"), slug=slug)
    response = Response(build_topic_payload(topic))
    return cache_public(response, max_age=MAX_AGE)
