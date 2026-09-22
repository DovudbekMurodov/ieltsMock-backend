"""Audio upload validation and storage.

The client's Content-Type is a claim, not evidence, so the file is identified
by its own bytes and then decoded to confirm it really is audio. Storage is
content-addressed, which gives dedupe, immutable URLs and no way to smuggle a
path through a filename.
"""

import hashlib

import mutagen
from django.core.exceptions import ValidationError

MAX_BYTES = 25 * 1024 * 1024
READ_CHUNK = 1024 * 1024

# (offset, signature, content type, extension)
SIGNATURES = [
    (0, b"ID3", "audio/mpeg", "mp3"),
    (0, b"\xff\xfb", "audio/mpeg", "mp3"),
    (0, b"\xff\xf3", "audio/mpeg", "mp3"),
    (0, b"\xff\xf2", "audio/mpeg", "mp3"),
    (0, b"OggS", "audio/ogg", "ogg"),
    (4, b"ftyp", "audio/mp4", "m4a"),
]


class AudioRejected(ValidationError):
    pass


def sniff(header: bytes) -> tuple[str, str]:
    """Identify the format from the file's own bytes."""
    for offset, signature, content_type, extension in SIGNATURES:
        if header[offset : offset + len(signature)] == signature:
            return content_type, extension
    raise AudioRejected(
        "That file is not an MP3, M4A or OGG. The browser's stated type is ignored; "
        "the file's own bytes are what count."
    )


def checksum(upload) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in iter(lambda: upload.read(READ_CHUNK), b""):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def duration_ms(upload) -> int:
    """Decode the file to confirm it plays and to read its length.

    mutagen is pure Python, so this needs no ffmpeg on the host -- which
    matters on a plain droplet.
    """
    upload.seek(0)
    try:
        parsed = mutagen.File(upload)
    except Exception as exc:
        raise AudioRejected(f"That file could not be decoded as audio ({exc}).") from exc
    finally:
        upload.seek(0)

    if parsed is None or not getattr(parsed, "info", None):
        raise AudioRejected("That file could not be decoded as audio.")

    length = getattr(parsed.info, "length", 0) or 0
    if length <= 0:
        raise AudioRejected("That file reports no playable length.")
    return int(length * 1000)


def inspect(upload) -> dict:
    """Validate an upload and return the metadata an AudioAsset needs."""
    if upload.size > MAX_BYTES:
        raise AudioRejected(
            f"That file is {upload.size // 1024 // 1024} MB. The limit is "
            f"{MAX_BYTES // 1024 // 1024} MB — a 30-minute mono MP3 is about 14 MB."
        )

    upload.seek(0)
    header = upload.read(16)
    upload.seek(0)

    content_type, extension = sniff(header)
    return {
        "content_type": content_type,
        "extension": extension,
        "checksum_sha256": checksum(upload),
        "duration_ms": duration_ms(upload),
        "size_bytes": upload.size,
        "original_filename": upload.name[:255],
    }


def store(asset, upload, extension: str) -> None:
    """Attach the uploaded bytes to an asset at its content-addressed path.

    Django's storage appends a random suffix when a name is taken, which would
    defeat the point: identical bytes must land on one path, or the same
    recording accumulates copies and the URL stops being derivable from the
    content. Since the path *is* the checksum, an existing file is already the
    right file, so it is reused rather than rewritten.
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    path = f"audio/{asset.checksum_sha256[:2]}/{asset.checksum_sha256}.{extension}"

    if default_storage.exists(path):
        asset.file.name = path
        return

    upload.seek(0)
    default_storage.save(path, ContentFile(upload.read()))
    asset.file.name = path
