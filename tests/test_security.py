"""Whole-surface guarantees.

These walk the URL configuration rather than listing endpoints by hand, so a
route added later is covered automatically -- which is the only way this kind
of check stays true.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.content.models import AnswerKey, Test

pytestmark = pytest.mark.django_db
User = get_user_model()

# Reachable without being staff, by design.
PUBLIC_DASHBOARD = {"dashboard:login", "dashboard:logout"}


def dashboard_routes():
    """Every dashboard route that takes no arguments or only an int/slug pk."""
    resolver = get_resolver()
    found = []

    def walk(patterns, prefix=""):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                nested = (
                    f"{prefix}{entry.namespace}:" if entry.namespace else prefix
                )
                walk(entry.url_patterns, nested)
            elif isinstance(entry, URLPattern) and entry.name:
                name = f"{prefix}{entry.name}" if prefix else entry.name
                if name.startswith("dashboard:"):
                    found.append((name, entry.pattern.regex.groupindex))
    walk(resolver.url_patterns)
    return found


@pytest.fixture
def seeded_ids(seeded_content):
    test = Test.objects.filter(published_payload__isnull=False).first()
    return {
        "pk": test.pk,
        "slug": test.slug,
        "model": "group-questions",
        "part": 1,
        "kind": "question",
    }


def build_url(name, groups, ids):
    kwargs = {}
    for group in groups:
        if group not in ids:
            return None
        kwargs[group] = ids[group]
    try:
        return reverse(name, kwargs=kwargs)
    except Exception:
        return None


def test_every_dashboard_route_rejects_a_signed_out_visitor(seeded_ids, client):
    checked = 0
    for name, groups in dashboard_routes():
        if name in PUBLIC_DASHBOARD:
            continue
        url = build_url(name, groups, seeded_ids)
        if url is None:
            continue
        response = client.get(url)
        assert response.status_code in (302, 404, 405), f"{name} returned {response.status_code}"
        checked += 1

    assert checked > 20, "the walk should have covered the dashboard, not a handful of routes"


def test_every_dashboard_route_returns_404_to_a_signed_in_non_staff_user(
    seeded_ids, client, user
):
    """404 rather than 403: a 403 confirms the dashboard is really there."""
    client.force_login(user)

    for name, groups in dashboard_routes():
        if name in PUBLIC_DASHBOARD:
            continue
        url = build_url(name, groups, seeded_ids)
        if url is None:
            continue
        response = client.get(url)
        assert response.status_code in (404, 405), f"{name} returned {response.status_code}"


def test_no_published_payload_contains_an_answer_bearing_key(seeded_content):
    """Restated here so the guarantee is checked against every content type."""
    from apps.vocabulary.models import VocabularySection

    banned = {"answer", "answers", "acceptedanswers", "iscorrect", "correct", "answerkeys"}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key.lower().replace("_", "") not in banned, f"leaked key {key!r}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for test in Test.objects.filter(published_payload__isnull=False):
        walk(test.published_payload)
    for section in VocabularySection.objects.filter(published_payload__isnull=False):
        walk(section.published_payload)


def test_a_gap_question_payload_carries_no_options_and_no_answer(seeded_content, client):
    """Gap answers have nowhere legitimate to hide.

    Two checks, both scoped to the question's own object. Structure first --
    a gap question carries only id, number, type and prompt, so there is no
    field an answer could sit in. Then the prompt itself, matched on word
    boundaries: comparing against the serialised object would false-positive
    on a single-digit answer, which collides with the id.
    """
    import re

    allowed = {"id", "number", "type", "prompt"}
    checked = 0

    for test in Test.objects.filter(published_payload__isnull=False):
        payload = client.get(reverse("api:test-detail", args=[test.slug])).json()
        by_number = {
            q["number"]: q
            for section in payload["sections"]
            for group in section["groups"]
            if group["type"] == "gap"
            for q in group["questions"]
        }

        for key in AnswerKey.objects.filter(
            question__test=test, question__group__type="gap"
        ).select_related("question"):
            question = by_number.get(key.question.number)
            assert question is not None
            assert set(question) == allowed, f"{test.slug}: unexpected {set(question) - allowed}"
            assert not re.search(
                rf"\b{re.escape(key.value)}\b", question["prompt"], re.IGNORECASE
            ), f"{test.slug} q{key.question.number}: {key.value!r} visible in its own prompt"
            checked += 1

    assert checked > 20, "the sweep should have covered every gap question"


def test_authenticated_api_responses_are_never_shared_cacheable(seeded_content, client, user):
    token = client.post(
        reverse("api:auth:login"),
        {"email": user.email, "password": "pw-test-1234"},
        content_type="application/json",
    ).json()["access"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    for name in ["api:auth:me", "api:attempts:mine", "api:writing-mine", "api:srs-due"]:
        response = client.get(reverse(name), **headers)
        assert "no-store" in response["Cache-Control"], name
        assert "Authorization" in response["Vary"], name


def test_error_responses_do_not_leak_a_stack_trace(seeded_content, client):
    """DEBUG is off in the test settings, so this reflects production."""
    response = client.get("/api/v1/tests/does-not-exist/")
    body = response.content.decode()

    assert response.status_code == 404
    assert "Traceback" not in body
    assert "django" not in body.lower() or "Not found" in body


def test_the_event_endpoint_will_not_store_arbitrary_names(client):
    before = json.dumps({"name": "arbitrary.name"})
    response = client.post(
        reverse("api:event-record"), before, content_type="application/json"
    )

    assert response.status_code == 400


def test_a_user_cannot_promote_themselves_to_staff(seeded_content, client, user):
    token = client.post(
        reverse("api:auth:login"),
        {"email": user.email, "password": "pw-test-1234"},
        content_type="application/json",
    ).json()["access"]

    client.patch(
        reverse("api:auth:me"),
        {"is_staff": True, "is_superuser": True},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    user.refresh_from_db()

    assert not user.is_staff
    assert not user.is_superuser


def test_production_settings_pass_djangos_own_deployment_checks():
    """Runs the real prod module, not a hand-rebuilt imitation of it.

    Reconstructing the settings in-process would only test the reconstruction,
    and would miss anything prod.py sets that the test forgot to copy.
    """
    import os
    import secrets
    import subprocess
    import sys
    from pathlib import Path

    from django.conf import settings as live

    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
        "DJANGO_DEBUG": "False",
        "DJANGO_ALLOWED_HOSTS": "api.example.com",
        "CORS_ALLOWED_ORIGINS": "https://app.example.com",
        "CSRF_TRUSTED_ORIGINS": "https://api.example.com",
    }
    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=Path(live.BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert "no issues" in output, output
