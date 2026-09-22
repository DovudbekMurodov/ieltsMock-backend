"""The one event endpoint the browser may call.

Server-side events are authoritative; this exists only for signals the server
cannot see, such as a page view inside the SPA. Names are whitelisted and the
payload is capped, so a client cannot fill the table with junk.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.accounts.guest import read_guest_id

from .events import CLIENT_EVENTS
from .tracking import record

MAX_PROPS = 10
MAX_VALUE_LENGTH = 200


class EventThrottle(AnonRateThrottle):
    scope = "events"


class EventSerializer(serializers.Serializer):
    name = serializers.ChoiceField(choices=sorted(CLIENT_EVENTS))
    objectType = serializers.CharField(required=False, allow_blank=True, max_length=32)
    objectId = serializers.IntegerField(required=False, allow_null=True)
    skill = serializers.CharField(required=False, allow_blank=True, max_length=16)
    props = serializers.DictField(required=False)

    def validate_props(self, value):
        if len(value) > MAX_PROPS:
            raise serializers.ValidationError(f"At most {MAX_PROPS} properties.")
        # Scalars only, and short ones: props is for dimensions, not payloads.
        cleaned = {}
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                raise serializers.ValidationError(f"{key!r} must be a scalar.")
            cleaned[str(key)[:40]] = str(item)[:MAX_VALUE_LENGTH]
        return cleaned


@extend_schema(
    operation_id="recordEvent",
    summary="Record a client-side event",
    request=EventSerializer,
    responses={202: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EventThrottle])
def record_event(request):
    serializer = EventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    record(
        data["name"],
        user=request.user,
        anon_id=read_guest_id(request),
        object_type=data.get("objectType", ""),
        object_id=data.get("objectId"),
        skill=data.get("skill", ""),
        props=data.get("props", {}),
        request=request,
    )
    return Response(status=status.HTTP_202_ACCEPTED)
