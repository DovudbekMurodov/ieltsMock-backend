"""Test settings: fast hashing, no external services."""

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# WhiteNoise warns about a missing staticfiles/ dir on every request; tests never
# serve static assets, so drop it rather than collectstatic before each run.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]

REFRESH_COOKIE_SAMESITE = "Lax"
REFRESH_COOKIE_SECURE = False
