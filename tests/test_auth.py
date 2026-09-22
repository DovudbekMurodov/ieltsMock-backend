import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

User = get_user_model()
pytestmark = pytest.mark.django_db

COOKIE = settings.REFRESH_COOKIE_NAME


def register(client, email="new@example.com", password="pw-test-abcd-1234"):
    return client.post(
        reverse("api:auth:register"),
        {"email": email, "password": password, "first_name": "New"},
        content_type="application/json",
    )


def login(client, email="student@example.com", password="pw-test-1234"):
    return client.post(
        reverse("api:auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    )


# --- registration and sign-in --------------------------------------------------


def test_register_returns_an_access_token_and_sets_the_refresh_cookie(client):
    response = register(client)

    assert response.status_code == 201
    assert response.json()["access"]
    assert response.json()["user"]["email"] == "new@example.com"
    assert COOKIE in response.cookies


def test_register_rejects_a_weak_password(client):
    response = client.post(
        reverse("api:auth:register"),
        {"email": "weak@example.com", "password": "1234"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not User.objects.filter(email="weak@example.com").exists()


def test_login_succeeds(client, user):
    response = login(client)

    assert response.status_code == 200
    assert response.json()["access"]
    assert response.json()["expiresIn"] == 900


def test_wrong_password_and_unknown_email_give_the_same_message(client, user):
    wrong = login(client, password="not-the-password")
    unknown = login(client, email="nobody@example.com")

    assert wrong.status_code == unknown.status_code == 400
    # Otherwise the endpoint tells an attacker which addresses are registered.
    assert wrong.json() == unknown.json()


def test_a_disabled_account_cannot_sign_in(client, user):
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert login(client).status_code == 400


# --- the refresh cookie --------------------------------------------------------


def test_refresh_cookie_is_httponly_and_scoped_to_the_auth_path(client, user):
    cookie = login(client).cookies[COOKIE]

    assert cookie["httponly"]
    assert cookie["path"] == settings.REFRESH_COOKIE_PATH
    assert cookie["samesite"] == settings.REFRESH_COOKIE_SAMESITE


def test_the_refresh_token_is_never_in_the_response_body(client, user):
    body = login(client).json()

    assert "refresh" not in body
    assert settings.REFRESH_COOKIE_NAME not in str(body)


def test_refresh_issues_a_new_access_token(client, user):
    login(client)
    response = client.post(reverse("api:auth:refresh"))

    assert response.status_code == 200
    assert response.json()["access"]


def test_refresh_without_a_cookie_is_rejected(client):
    assert client.post(reverse("api:auth:refresh")).status_code == 401


def test_rotation_invalidates_the_previous_refresh_token(client, user):
    login(client)
    first = client.cookies[COOKIE].value

    client.post(reverse("api:auth:refresh"))
    second = client.cookies[COOKIE].value

    assert first != second, "the refresh token should rotate on every use"


# --- reuse detection -----------------------------------------------------------


def test_replaying_a_rotated_token_revokes_every_session(client, user):
    """A token presented twice means the cookie leaked.

    We cannot tell the attacker from the legitimate holder, so both are signed
    out and must authenticate again.
    """
    login(client)
    stolen = client.cookies[COOKIE].value

    client.post(reverse("api:auth:refresh"))  # rotates; `stolen` is now spent
    assert client.post(reverse("api:auth:refresh")).status_code == 200

    client.cookies[COOKIE] = stolen
    replay = client.post(reverse("api:auth:refresh"))

    assert replay.status_code == 401
    assert "reused" in replay.json()["detail"].lower()

    outstanding = OutstandingToken.objects.filter(user=user)
    blacklisted = BlacklistedToken.objects.filter(token__in=outstanding)
    assert outstanding.count() == blacklisted.count(), "every session should be revoked"

    client.cookies.clear()
    assert client.post(reverse("api:auth:refresh")).status_code == 401


def test_a_garbage_cookie_is_rejected_without_touching_other_sessions(client, user):
    login(client)
    client.cookies[COOKIE] = "not-a-jwt"

    assert client.post(reverse("api:auth:refresh")).status_code == 401
    assert not BlacklistedToken.objects.exists()


# --- sign-out ------------------------------------------------------------------


def test_logout_blacklists_the_token_and_clears_the_cookie(client, user):
    login(client)
    response = client.post(reverse("api:auth:logout"))

    assert response.status_code == 204
    assert client.cookies[COOKIE].value == ""
    assert client.post(reverse("api:auth:refresh")).status_code == 401


def test_logout_all_revokes_every_device(client, user):
    other = client.__class__()
    login(client)
    login(other)

    access = login(client).json()["access"]
    response = client.post(
        reverse("api:auth:logout-all"), HTTP_AUTHORIZATION=f"Bearer {access}"
    )

    assert response.status_code == 200
    assert other.post(reverse("api:auth:refresh")).status_code == 401


# --- the authenticated user ----------------------------------------------------


def test_me_requires_authentication(client):
    assert client.get(reverse("api:auth:me")).status_code == 401


def test_me_returns_the_signed_in_user(client, user):
    access = login(client).json()["access"]

    response = client.get(reverse("api:auth:me"), HTTP_AUTHORIZATION=f"Bearer {access}")

    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_me_never_exposes_the_password_hash(client, user):
    access = login(client).json()["access"]
    body = client.get(reverse("api:auth:me"), HTTP_AUTHORIZATION=f"Bearer {access}").json()

    assert "password" not in body


def test_me_can_update_the_profile_but_not_staff_status(client, user):
    access = login(client).json()["access"]

    response = client.patch(
        reverse("api:auth:me"),
        {"target_band": "7.5", "is_staff": True},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    user.refresh_from_db()

    assert response.status_code == 200
    assert str(user.target_band) == "7.5"
    assert user.is_staff is False, "is_staff is read-only over the API"


def test_authenticated_responses_are_not_shared_cacheable(client, user):
    access = login(client).json()["access"]

    response = client.get(reverse("api:auth:me"), HTTP_AUTHORIZATION=f"Bearer {access}")

    assert "no-store" in response["Cache-Control"]
    assert "Authorization" in response["Vary"]
