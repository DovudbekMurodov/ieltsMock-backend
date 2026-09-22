from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def health(request):
    """Liveness plus a real database round-trip.

    A health check that does not touch the database reports green while every
    request 500s, so this one deliberately pays for one query.
    """
    checks = {}
    status = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - exercised only when the DB is down
        checks["database"] = f"error: {exc.__class__.__name__}"
        status = 503

    return JsonResponse(
        {"status": "ok" if status == 200 else "degraded", "checks": checks},
        status=status,
    )
