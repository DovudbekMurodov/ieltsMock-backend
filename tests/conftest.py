import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        email="staff@example.com", password="pw-test-1234", is_staff=True
    )
