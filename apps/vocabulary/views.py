from django.shortcuts import get_object_or_404
from django.views.decorators.http import condition
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.conditional import make_conditional_funcs
from apps.common.middleware import cache_public
from apps.common.models import PublishStatus

from .models import VocabularySection

LIST_MAX_AGE = 300


def _published():
    return VocabularySection.objects.filter(
        status=PublishStatus.PUBLISHED, published_payload__isnull=False
    )


def _lookup(slug):
    row = _published().filter(slug=slug).values_list("payload_etag", "published_at").first()
    return row if row else (None, None)


_detail_etag, _detail_last_modified = make_conditional_funcs(_lookup)


@extend_schema(operation_id="listVocabularySections",
    summary="List published vocabulary sections",
    responses={200: dict},)
@api_view(["GET"])
@permission_classes([AllowAny])
def section_list(request):
    sections = _published().order_by("order", "title").only("slug", "title", "published_payload")
    results = [
        {
            "id": s.slug,
            "title": s.title,
            "wordCount": s.published_payload.get("wordCount", 0),
        }
        for s in sections
    ]
    response = Response({"count": len(results), "results": results})
    return cache_public(response, max_age=LIST_MAX_AGE)


@extend_schema(operation_id="getVocabularySection",
    summary="Fetch one vocabulary section with its words",
    responses={200: dict},)
@api_view(["GET"])
@permission_classes([AllowAny])
@condition(etag_func=_detail_etag, last_modified_func=_detail_last_modified)
def section_detail(request, slug):
    payload = get_object_or_404(
        _published().values_list("published_payload", flat=True), slug=slug
    )
    response = Response(payload)
    return cache_public(response, max_age=LIST_MAX_AGE, stale_while_revalidate=600)
