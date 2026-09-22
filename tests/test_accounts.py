import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


def test_email_is_the_username_field():
    assert User.USERNAME_FIELD == "email"
    assert User.REQUIRED_FIELDS == []


def test_create_user_normalises_email(db):
    user = User.objects.create_user(email="Student@Example.COM", password="pw-test-1234")

    # Django lowercases the domain but preserves the local part's case.
    assert user.email == "Student@example.com"
    assert user.check_password("pw-test-1234")
    assert not user.is_staff


def test_create_user_requires_an_email(db):
    with pytest.raises(ValueError, match="email address"):
        User.objects.create_user(email="", password="pw-test-1234")


def test_create_superuser_sets_flags(db):
    admin = User.objects.create_superuser(email="admin@example.com", password="pw-test-1234")

    assert admin.is_staff
    assert admin.is_superuser


def test_email_is_unique(db):
    from django.db import IntegrityError

    User.objects.create_user(email="dupe@example.com", password="pw-test-1234")
    with pytest.raises(IntegrityError):
        User.objects.create_user(email="dupe@example.com", password="pw-test-1234")
