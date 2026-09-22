from django.urls import reverse


def test_health_reports_ok_with_database(db, client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_health_is_never_cached(db, client):
    response = client.get(reverse("health"))

    assert "no-cache" in response.headers["Cache-Control"]
