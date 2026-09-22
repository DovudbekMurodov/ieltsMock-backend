import io
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.content.audio import AudioRejected, inspect, sniff
from apps.content.enums import Skill, TranscriptVisibility
from apps.content.models import AudioAsset, Section, Test
from apps.content.publishing import publish_test

pytestmark = pytest.mark.django_db
User = get_user_model()

MP3 = (Path(settings.BASE_DIR) / "tests" / "fixtures" / "tone.mp3").read_bytes()


def upload(name="clip.mp3", data=None, content_type="audio/mpeg"):
    return SimpleUploadedFile(name, data if data is not None else MP3, content_type)


@pytest.fixture
def staff_client(client, db):
    client.force_login(
        User.objects.create_user(email="audio@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


@pytest.fixture
def listening(db):
    test = Test.objects.create(
        skill=Skill.LISTENING, slug="audio-test", title="Audio Test", time_limit_minutes=15
    )
    section = Section.objects.create(test=test, order=1, title="Section 1")
    return test, section


# --- identifying the file ------------------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        (b"ID3\x04\x00", "audio/mpeg"),
        (b"\xff\xfb\x90\x00", "audio/mpeg"),
        (b"OggS\x00\x02", "audio/ogg"),
        (b"\x00\x00\x00 ftypM4A ", "audio/mp4"),
    ],
)
def test_formats_are_identified_from_their_own_bytes(header, expected):
    assert sniff(header)[0] == expected


@pytest.mark.parametrize("header", [b"PK\x03\x04", b"%PDF-1.7", b"GIF89a", b"\x00" * 16])
def test_non_audio_is_rejected_whatever_the_extension(header):
    with pytest.raises(AudioRejected):
        sniff(header)


def test_a_lying_content_type_does_not_get_a_file_accepted():
    """The browser's stated type is a claim; the bytes are the evidence."""
    disguised = upload("evil.mp3", b"PK\x03\x04" + b"\x00" * 100, "audio/mpeg")

    with pytest.raises(AudioRejected):
        inspect(disguised)


def test_a_file_that_cannot_be_decoded_is_rejected():
    """A valid header is not enough -- it has to actually play."""
    truncated = upload("broken.mp3", b"ID3\x04\x00" + b"\x00" * 40)

    with pytest.raises(AudioRejected):
        inspect(truncated)


def test_oversized_files_are_rejected_before_decoding():
    big = upload("huge.mp3", b"\xff\xfb\x90\x00")
    big.size = 40 * 1024 * 1024

    with pytest.raises(AudioRejected, match="limit"):
        inspect(big)


def test_inspect_returns_the_metadata_an_asset_needs():
    meta = inspect(upload())

    assert meta["content_type"] == "audio/mpeg"
    assert meta["extension"] == "mp3"
    assert len(meta["checksum_sha256"]) == 64
    assert 900 <= meta["duration_ms"] <= 1100


def test_the_same_bytes_always_hash_the_same():
    assert inspect(upload("a.mp3"))["checksum_sha256"] == inspect(upload("b.mp3"))[
        "checksum_sha256"
    ]


# --- the library ---------------------------------------------------------------


def test_uploading_stores_the_file_under_its_checksum(staff_client):
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)

    asset = AudioAsset.objects.get()
    assert asset.checksum_sha256 in asset.file.name
    # The uploaded filename never reaches the path, so it cannot smuggle one.
    assert "clip" not in asset.file.name
    assert asset.original_filename == "clip.mp3"


def test_uploading_the_same_file_twice_reuses_the_first_copy(staff_client):
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload("first.mp3")}, follow=True)
    response = staff_client.post(
        reverse("dashboard:audio-upload"), {"file": upload("second.mp3")}, follow=True
    )

    assert AudioAsset.objects.count() == 1
    assert "already in the library" in response.content.decode()


def test_a_rejected_upload_explains_why(staff_client):
    response = staff_client.post(
        reverse("dashboard:audio-upload"),
        {"file": upload("notes.mp3", b"%PDF-1.7" + b"\x00" * 50)},
        follow=True,
    )

    assert AudioAsset.objects.count() == 0
    assert "not an MP3" in response.content.decode()


def test_an_empty_upload_is_handled(staff_client):
    response = staff_client.post(reverse("dashboard:audio-upload"), {}, follow=True)

    assert response.status_code == 200
    assert AudioAsset.objects.count() == 0


def test_audio_in_use_cannot_be_deleted(staff_client, listening):
    _, section = listening
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    asset = AudioAsset.objects.get()
    section.audio = asset
    section.save()

    response = staff_client.post(reverse("dashboard:audio-delete", args=[asset.pk]), follow=True)

    assert AudioAsset.objects.filter(pk=asset.pk).exists()
    assert "Detach it first" in response.content.decode()


def test_unused_audio_can_be_deleted(staff_client):
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    asset = AudioAsset.objects.get()

    staff_client.post(reverse("dashboard:audio-delete", args=[asset.pk]), follow=True)

    assert not AudioAsset.objects.exists()


# --- attaching it, and what that does to the transcript ------------------------


def test_attaching_audio_hides_the_transcript_by_default(staff_client, listening):
    """Otherwise it stops being a listening test."""
    _, section = listening
    assert section.transcript_visibility == TranscriptVisibility.DURING_TEST

    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    asset = AudioAsset.objects.get()
    staff_client.post(
        reverse("dashboard:hx-section-audio", args=[section.pk]), {"assetId": asset.pk}
    )
    section.refresh_from_db()

    assert section.audio_id == asset.pk
    assert section.transcript_visibility == TranscriptVisibility.AFTER_SUBMIT


def test_a_deliberate_transcript_choice_is_not_overridden(staff_client, listening):
    _, section = listening
    section.transcript_visibility = TranscriptVisibility.NEVER
    section.save()
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)

    staff_client.post(
        reverse("dashboard:hx-section-audio", args=[section.pk]),
        {"assetId": AudioAsset.objects.get().pk},
    )
    section.refresh_from_db()

    assert section.transcript_visibility == TranscriptVisibility.NEVER


def test_detaching_audio_leaves_the_section_playable_as_transcript(staff_client, listening):
    _, section = listening
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    staff_client.post(
        reverse("dashboard:hx-section-audio", args=[section.pk]),
        {"assetId": AudioAsset.objects.get().pk},
    )

    staff_client.post(reverse("dashboard:hx-section-audio", args=[section.pk]), {"assetId": ""})
    section.refresh_from_db()

    assert section.audio_id is None


def test_an_end_before_its_start_is_refused(staff_client, listening):
    _, section = listening
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)

    response = staff_client.post(
        reverse("dashboard:hx-section-audio", args=[section.pk]),
        {"assetId": AudioAsset.objects.get().pk, "audio_start_ms": 5000, "audio_end_ms": 1000},
    )

    assert response.status_code == 400


# --- what the API serves -------------------------------------------------------


def test_the_payload_carries_the_audio_url(staff_client, client, listening):
    test, section = listening
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    staff_client.post(
        reverse("dashboard:hx-section-audio", args=[section.pk]),
        {"assetId": AudioAsset.objects.get().pk},
    )
    publish_test(test)

    payload = client.get(reverse("api:test-detail", args=[test.slug])).json()
    audio = payload["sections"][0]["audio"]

    assert audio["url"]
    assert 900 <= audio["durationMs"] <= 1100
    assert audio["playbackPolicy"] == "free"


def test_the_transcript_is_withheld_server_side_once_audio_is_attached(
    staff_client, client, listening
):
    """Hiding it in the UI would be bypassable; omitting it from the payload is not."""
    from apps.content.models import Block

    test, section = listening
    Block.objects.create(section=section, order=1, label="Tutor", text="Secret transcript line.")
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    staff_client.post(
        reverse("dashboard:hx-section-audio", args=[section.pk]),
        {"assetId": AudioAsset.objects.get().pk},
    )
    publish_test(test)

    body = client.get(reverse("api:test-detail", args=[test.slug])).content.decode()
    section_payload = client.get(reverse("api:test-detail", args=[test.slug])).json()["sections"][0]

    assert "Secret transcript line." not in body
    assert section_payload["blocks"] == []
    assert section_payload["blocksAvailableAfterSubmit"] is True


def test_a_section_without_audio_still_serves_its_transcript(seeded_content, client):
    payload = client.get(reverse("api:test-detail", args=["booking-campsite"])).json()
    section = payload["sections"][0]

    assert section["audio"] is None
    assert len(section["blocks"]) > 0
    assert section["blocksAvailableAfterSubmit"] is False


def test_audio_urls_are_content_addressed_so_they_can_be_cached_forever(staff_client):
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)
    asset = AudioAsset.objects.get()

    # The path is derived entirely from the bytes, so the same URL can never
    # point at different content.
    assert asset.file.name == f"audio/{asset.checksum_sha256[:2]}/{asset.checksum_sha256}.mp3"


def test_uploading_records_who_did_it(staff_client):
    staff_client.post(reverse("dashboard:audio-upload"), {"file": upload()}, follow=True)

    assert AudioAsset.objects.get().uploaded_by.email == "audio@example.com"


def test_a_zero_byte_file_is_rejected():
    with pytest.raises(AudioRejected):
        inspect(SimpleUploadedFile("empty.mp3", b"", "audio/mpeg"))


def test_inspect_leaves_the_stream_rewound():
    handle = io.BytesIO(MP3)
    handle.name = "x.mp3"
    handle.size = len(MP3)

    inspect(handle)

    assert handle.tell() == 0
