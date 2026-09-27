from django.conf import settings
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.analytics import events
from apps.analytics.tracking import record
from apps.common.throttles import AuthThrottle, WriteThrottle

from .avatars import AvatarRejected, normalise
from .serializers import (
    AuthSessionSerializer,
    DetailSerializer,
    LoginSerializer,
    RegisterSerializer,
    RevokedCountSerializer,
    TokenValiditySerializer,
    UserSerializer,
    VerifyRequestSerializer,
)
from .tokens import (
    TokenReuseDetected,
    clear_refresh_cookie,
    issue,
    revoke_all_for_user,
    rotate,
    set_refresh_cookie,
)


def _access_response(
    user, refresh: RefreshToken, http_status=status.HTTP_200_OK, request=None
) -> Response:
    """Access token in the body, refresh token in an httpOnly cookie.

    The access token is short-lived and meant to be held in memory by the SPA;
    the refresh token never reaches JavaScript.
    """
    access = refresh.access_token
    response = Response(
        {
            "access": str(access),
            "expiresIn": int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            # The request builds the absolute avatar URL. Without it login
            # would return a relative one where /me/ returns absolute.
            "user": UserSerializer(user, context={"request": request}).data,
        },
        status=http_status,
    )
    set_refresh_cookie(response, refresh)
    return response


@extend_schema(
    operation_id="register",
    summary="Create an account",
    request=RegisterSerializer,
    responses={201: AuthSessionSerializer, 400: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    record(events.AUTH_SIGNUP, user=user, request=request)
    return _access_response(user, issue(user), status.HTTP_201_CREATED, request=request)


@extend_schema(
    operation_id="login",
    summary="Sign in",
    request=LoginSerializer,
    responses={200: AuthSessionSerializer, 400: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    serializer = LoginSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data["user"]
    record(events.AUTH_LOGIN, user=user, request=request)
    return _access_response(user, issue(user), request=request)


@extend_schema(
    operation_id="refreshToken",
    summary="Exchange the refresh cookie for a new access token",
    request=None,
    responses={200: AuthSessionSerializer, 401: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def refresh(request):
    raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
    if not raw:
        return Response({"detail": "No refresh token."}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        new_refresh, user = rotate(raw)
    except TokenReuseDetected as exc:
        response = Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
        clear_refresh_cookie(response)
        return response
    except TokenError:
        response = Response(
            {"detail": "Refresh token is invalid or expired."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
        clear_refresh_cookie(response)
        return response

    return _access_response(user, new_refresh, request=request)


@extend_schema(
    operation_id="logout",
    summary="Sign out of this session",
    request=None,
    responses={204: None},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def logout(request):
    raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
    if raw:
        try:
            RefreshToken(raw).blacklist()
        except TokenError:
            pass  # Already expired or blacklisted; the cookie still goes.

    response = Response(status=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response)
    return response


@extend_schema(
    operation_id="logoutEverywhere",
    summary="Revoke every session for this user",
    request=None,
    responses={200: RevokedCountSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_all(request):
    revoked = revoke_all_for_user(request.user)
    response = Response({"revoked": revoked})
    clear_refresh_cookie(response)
    return response


@extend_schema_view(
    get=extend_schema(
        operation_id="getCurrentUser",
        summary="The signed-in user",
        responses={200: UserSerializer},
    ),
    patch=extend_schema(
        operation_id="updateCurrentUser",
        summary="Update the signed-in user's profile",
        request=UserSerializer,
        responses={200: UserSerializer},
    ),
)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    if request.method == "PATCH":
        serializer = UserSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(UserSerializer(request.user, context={"request": request}).data)


@extend_schema_view(
    post=extend_schema(
        operation_id="setAvatar",
        summary="Upload the signed-in user's avatar",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"avatar": {"type": "string", "format": "binary"}},
            }
        },
        responses={200: UserSerializer},
    ),
    delete=extend_schema(
        operation_id="clearAvatar",
        summary="Remove the signed-in user's avatar",
        responses={200: UserSerializer},
    ),
)
@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
@throttle_classes([WriteThrottle])
def avatar(request):
    user = request.user

    if request.method == "DELETE":
        if user.avatar:
            # Content-addressed storage means two accounts can share a file, so
            # the row is cleared and the blob is left alone.
            user.avatar = None
            user.save(update_fields=["avatar"])
        return Response(UserSerializer(user, context={"request": request}).data)

    upload = request.FILES.get("avatar")
    if upload is None:
        return Response({"detail": "No file was sent."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        normalised = normalise(upload)
    except AvatarRejected as rejected:
        return Response({"detail": rejected.messages[0]}, status=status.HTTP_400_BAD_REQUEST)

    # Storage appends a random suffix when a name is taken, which would turn
    # content-addressing into one copy per upload. Reusing the existing blob is
    # what actually makes the dedupe true.
    target = f"avatars/{normalised.name}"
    if default_storage.exists(target):
        user.avatar.name = target
        user.save(update_fields=["avatar"])
    else:
        user.avatar.save(normalised.name, normalised, save=True)

    return Response(UserSerializer(user, context={"request": request}).data)


@extend_schema(
    operation_id="verifyAccessToken",
    summary="Check an access token",
    request=VerifyRequestSerializer,
    responses={200: TokenValiditySerializer, 401: TokenValiditySerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def verify(request):
    token = request.data.get("token")
    try:
        AccessToken(token)
    except TokenError:
        return Response({"valid": False}, status=status.HTTP_401_UNAUTHORIZED)
    return Response({"valid": True})
