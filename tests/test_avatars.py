from io import BytesIO

import piexif
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

pytestmark = pytest.mark.django_db


def auth(client, email="student@example.com", password="pw-test-1234"):
    body = client.post(
        reverse("api:auth:login"),
        {"email": email, "password": password},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {body['access']}"}


def image_file(name="face.jpg", size=(800, 400), fmt="JPEG", exif=None):
    buffer = BytesIO()
    extra = {"exif": exif} if exif else {}
    Image.new("RGB", size, (120, 140, 200)).save(buffer, format=fmt, **extra)
    buffer.seek(0)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif"}[fmt]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def upload(client, file, **extra):
    return client.post(reverse("api:auth:avatar"), {"avatar": file}, **extra)


@pytest.fixture
def student(django_user_model):
    return django_user_model.objects.create_user(
        email="student@example.com", password="pw-test-1234"
    )


def test_avatar_requires_authentication(client, student):
    assert upload(client, image_file()).status_code == 401


def test_upload_stores_a_square_image_and_returns_its_url(client, student):
    body = upload(client, image_file(size=(800, 400)), **auth(client)).json()

    assert body["avatar"].startswith("http")
    student.refresh_from_db()
    with Image.open(BytesIO(student.avatar.read())) as stored:
        # Centre-cropped rather than squashed, so a face is not stretched.
        assert stored.width == stored.height


def test_a_large_image_is_capped(client, student):
    upload(client, image_file(size=(2000, 2000)), **auth(client))

    student.refresh_from_db()
    with Image.open(BytesIO(student.avatar.read())) as stored:
        assert stored.width == 512


def test_exif_is_stripped(client, student):
    """A phone photo carries GPS, and an avatar is served from a public URL.

    Storing the upload as it arrived would publish where the picture was taken
    to anyone who opens it, so the image is re-encoded rather than saved.
    """
    exif = piexif.dump(
        {
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"N",
                piexif.GPSIFD.GPSLatitude: ((41, 1), (18, 1), (0, 1)),
            }
        }
    )
    original = image_file(exif=exif)
    assert piexif.load(original.read())["GPS"] != {}
    original.seek(0)

    upload(client, original, **auth(client))

    student.refresh_from_db()
    with Image.open(BytesIO(student.avatar.read())) as stored:
        assert not stored.info.get("exif")


def test_a_file_that_is_not_an_image_is_refused(client, student):
    not_an_image = SimpleUploadedFile(
        "payload.jpg", b"#!/bin/sh\nrm -rf /", content_type="image/jpeg"
    )

    response = upload(client, not_an_image, **auth(client))

    # The Content-Type says image/jpeg. The bytes are what decided.
    assert response.status_code == 400
    student.refresh_from_db()
    assert not student.avatar


def test_an_unaccepted_image_format_is_refused(client, student):
    response = upload(client, image_file(name="anim.gif", fmt="GIF"), **auth(client))

    assert response.status_code == 400
    assert "GIF" in response.json()["detail"]


def test_posting_nothing_is_a_400_not_a_crash(client, student):
    response = client.post(reverse("api:auth:avatar"), {}, **auth(client))
    assert response.status_code == 400


def test_delete_clears_the_avatar(client, student):
    headers = auth(client)
    upload(client, image_file(), **headers)

    body = client.delete(reverse("api:auth:avatar"), **headers).json()

    assert body["avatar"] is None
    student.refresh_from_db()
    assert not student.avatar


def test_the_same_photo_twice_lands_on_one_name(client, student):
    headers = auth(client)
    first = upload(client, image_file(), **headers).json()["avatar"]
    second = upload(client, image_file(), **headers).json()["avatar"]

    # Content-addressed storage: identical bytes, identical name, no second copy.
    assert first == second


def test_the_avatar_url_comes_back_from_login_too(client, student):
    upload(client, image_file(), **auth(client))

    body = client.post(
        reverse("api:auth:login"),
        {"email": "student@example.com", "password": "pw-test-1234"},
        content_type="application/json",
    ).json()

    assert body["user"]["avatar"].startswith("http")


def test_one_user_cannot_see_anothers_avatar_field(client, student, django_user_model):
    django_user_model.objects.create_user(email="other@example.com", password="pw-test-1234")
    upload(client, image_file(), **auth(client))

    body = client.get(reverse("api:auth:me"), **auth(client, email="other@example.com")).json()

    assert body["avatar"] is None
