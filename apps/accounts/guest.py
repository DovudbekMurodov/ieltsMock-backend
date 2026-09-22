"""Anonymous visitor identity.

A practice platform that demands an account before the first test loses most
casual traffic, so attempts may be anonymous. The server issues an opaque id,
stores it in a cookie, and the SPA also keeps a copy so the attempt survives a
cleared cookie jar. On signup the guest's work is claimed into the account.
"""

import uuid

from django.conf import settings

GUEST_HEADER = "HTTP_X_GUEST_ID"


def read_guest_id(request) -> uuid.UUID | None:
    raw = request.META.get(GUEST_HEADER) or request.COOKIES.get(settings.GUEST_COOKIE_NAME)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def ensure_guest_id(request) -> uuid.UUID:
    return read_guest_id(request) or uuid.uuid4()


def set_guest_cookie(response, guest_id: uuid.UUID):
    response.set_cookie(
        settings.GUEST_COOKIE_NAME,
        str(guest_id),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )
    return response
