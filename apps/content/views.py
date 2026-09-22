"""Public read API for tests.

Served from Test.published_payload: one row, no joins, no N+1 by construction.
@condition short-circuits before the view body runs, so a returning client
costs one indexed query and gets a 304 with an empty body.
"""

from django.shortcuts import get_object_or_404
from django.views.decorators.http import condition
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.conditional import make_conditional_funcs
from apps.common.middleware import cache_public
from apps.common.models import PublishStatus

from .enums import Skill
from .models import Test

LIST_MAX_AGE = 300
DETAIL_MAX_AGE = 60
DETAIL_STALE_WHILE_REVALIDATE = 600


def _published():
    return Test.objects.filter(status=PublishStatus.PUBLISHED, published_payload__isnull=False)


def _lookup(slug):
    row = _published().filter(slug=slug).values_list("payload_etag", "published_at").first()
    return row if row else (None, None)


_detail_etag, _detail_last_modified = make_conditional_funcs(_lookup)


@extend_schema(
    operation_id="listTests",
    summary="List published tests",
    parameters=[
        OpenApiParameter("skill", str, description="Filter by skill: reading or listening.")
    ],
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def test_list(request):
    queryset = _published()

    skill = request.query_params.get("skill")
    if skill:
        if skill not in Skill.values:
            return Response({"detail": f"Unknown skill {skill!r}."}, status=400)
        queryset = queryset.filter(skill=skill)

    rows = queryset.values(
        "slug", "skill", "title", "description", "difficulty", "time_limit_minutes", "published_at"
    ).order_by("skill", "title")

    counts = {
        test.slug: test.published_payload.get("questionCount", 0)
        for test in queryset.only("slug", "published_payload")
    }

    results = [
        {
            "id": row["slug"],
            "skill": row["skill"],
            "title": row["title"],
            "description": row["description"],
            "difficulty": row["difficulty"],
            "timeLimitMinutes": row["time_limit_minutes"],
            "questionCount": counts.get(row["slug"], 0),
        }
        for row in rows
    ]

    response = Response({"count": len(results), "results": results})
    return cache_public(response, max_age=LIST_MAX_AGE)


@extend_schema(
    operation_id="getTest",
    summary="Fetch one published test",
    description=(
        "Returns the materialised public payload. Correct answers are never "
        "included; scoring happens server-side on submission."
    ),
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([AllowAny])
@condition(etag_func=_detail_etag, last_modified_func=_detail_last_modified)
def test_detail(request, slug):
    payload = get_object_or_404(
        _published().values_list("published_payload", flat=True), slug=slug
    )
    response = Response(payload)
    return cache_public(
        response,
        max_age=DETAIL_MAX_AGE,
        stale_while_revalidate=DETAIL_STALE_WHILE_REVALIDATE,
    )
