"""Refresh-token handling: cookie transport, rotation and reuse detection."""

from django.conf import settings
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken


class TokenReuseDetected(TokenError):
    """A refresh token was presented after it had already been rotated away."""


def issue(user) -> RefreshToken:
    return RefreshToken.for_user(user)


def set_refresh_cookie(response, refresh) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        str(refresh),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def revoke_all_for_user(user) -> int:
    """Blacklist every outstanding refresh token for a user."""
    count = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        count += created
    return count


def rotate(raw_token: str) -> tuple[RefreshToken, object]:
    """Validate, rotate and return (new refresh, user).

    simplejwt blacklists the old token after rotation, so a replay is rejected.
    On top of that, seeing an already-blacklisted token means the cookie leaked:
    the presenter and the legitimate holder both have it, and we cannot tell
    which is which. Revoking the user's whole token family logs both out and
    forces a fresh login, which is the safe resolution.
    """
    from django.contrib.auth import get_user_model

    try:
        refresh = RefreshToken(raw_token)
    except TokenError:
        _handle_possible_reuse(raw_token)
        raise

    user_id = refresh.payload.get(settings.SIMPLE_JWT["USER_ID_CLAIM"])
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise TokenError("No active user for this token.")

    refresh.blacklist()
    return issue(user), user


def _handle_possible_reuse(raw_token: str) -> None:
    try:
        jti = RefreshToken(raw_token, verify=False).payload.get("jti")
    except Exception:  # a malformed token is simply not a reuse
        return

    outstanding = OutstandingToken.objects.filter(jti=jti).select_related("user").first()
    if outstanding and BlacklistedToken.objects.filter(token=outstanding).exists():
        revoke_all_for_user(outstanding.user)
        raise TokenReuseDetected(
            "This session was signed out because its token was reused. Please sign in again."
        )
