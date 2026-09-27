"""Avatar validation and normalisation.

Same principle as the audio library: the browser's Content-Type is a claim, so
the file is identified by decoding it rather than by trusting the header.

Two things beyond validation happen here, and both are the point of
normalising rather than storing what was uploaded.

The image is re-encoded, which drops every EXIF block it arrived with. Phone
photos routinely carry GPS coordinates, and an avatar is served from a public
URL — storing the original would publish where the photo was taken to anyone
who opens it.

It is also squared and capped at 512px. An avatar is displayed at 40px; the
rest is storage and bandwidth spent on pixels nobody sees, and an unbounded
one is a way to fill the disk one upload at a time.
"""

import hashlib
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 4 * 1024 * 1024
SIDE = 512
# Decompression-bomb guard: a few hundred KB of PNG can declare a canvas of
# hundreds of megapixels, and Pillow will happily try to allocate it.
MAX_PIXELS = 50_000_000

ACCEPTED = {"JPEG", "PNG", "WEBP"}


class AvatarRejected(ValidationError):
    pass


def normalise(upload) -> ContentFile:
    """Validate an uploaded image and return a square, stripped JPEG."""
    if upload.size > MAX_BYTES:
        limit = MAX_BYTES // 1024 // 1024
        raise AvatarRejected(f"That image is larger than the {limit}MB limit.")

    data = upload.read()

    try:
        probe = Image.open(BytesIO(data))
        probe.verify()
    except (UnidentifiedImageError, OSError) as cause:
        raise AvatarRejected(
            "That file is not an image the server can read. The browser's stated type is "
            "ignored; the file's own bytes are what count."
        ) from cause

    if probe.format not in ACCEPTED:
        raise AvatarRejected(f"{probe.format} images are not accepted. Use JPEG, PNG or WEBP.")

    width, height = probe.size
    if width * height > MAX_PIXELS:
        raise AvatarRejected("That image has too many pixels to process.")

    # verify() leaves the file unusable for reading pixels, so it is reopened.
    image = Image.open(BytesIO(data))
    image = image.convert("RGB")

    # Centre crop to a square before resizing, so faces are not stretched.
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    if side > SIDE:
        image = image.resize((SIDE, SIDE), Image.LANCZOS)

    out = BytesIO()
    # No exif= argument, so nothing from the original is carried over.
    image.save(out, format="JPEG", quality=85, optimize=True)
    payload = out.getvalue()

    # Content-addressed, like the audio library: the same photo uploaded twice
    # lands on one name, and a filename can never smuggle a path.
    digest = hashlib.sha256(payload).hexdigest()[:32]
    return ContentFile(payload, name=f"{digest}.jpg")
