import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command


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


@pytest.fixture(scope="session")
def seeded_content(django_db_setup, django_db_blocker):
    """Seed and publish the real content once per session."""
    with django_db_blocker.unblock():
        call_command("seed_content", verbosity=0)
        call_command("publish_content", verbosity=0)
        yield
