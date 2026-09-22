"""Recording events.

Server-side calls live inside service functions so the event and the change it
describes commit together -- an event that survives a rolled-back transaction
is worse than no event.
"""

import hashlib

from django.conf import settings

from .events import ALL_EVENTS
from .models import Event

UA_FAMILIES = [
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Chrome/", "Chrome"),
    ("Firefox/", "Firefox"),
    ("Safari/", "Safari"),
]


def hash_ip(ip: str | None) -> str:
    """Salted hash. The raw address is never stored."""
    if not ip:
        return ""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()


def ua_family(user_agent: str | None) -> str:
    """A coarse family, not the full string, which is itself a fingerprint."""
    if not user_agent:
        return ""
    for needle, family in UA_FAMILIES:
        if needle in user_agent:
            return family
    return "Other"


def client_meta(request) -> dict:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return {
        "ip_hash": hash_ip(ip),
        "ua_family": ua_family(request.META.get("HTTP_USER_AGENT")),
        "path": request.path[:200],
    }


def record(
    name: str,
    *,
    user=None,
    anon_id=None,
    obj=None,
    object_type: str = "",
    object_id=None,
    skill: str = "",
    props: dict | None = None,
    request=None,
) -> Event | None:
    """Write one event. Unknown names are dropped rather than stored."""
    if name not in ALL_EVENTS:
        return None

    if obj is not None:
        object_type = object_type or obj.__class__.__name__.lower()
        object_id = object_id or obj.pk

    meta = client_meta(request) if request is not None else {}
    return Event.objects.create(
        name=name,
        user=user if (user and getattr(user, "is_authenticated", False)) else None,
        anon_id=anon_id,
        object_type=object_type[:32],
        object_id=object_id,
        skill=skill[:16],
        props=props or {},
        **meta,
    )
