"""Production settings.

Required environment variables are resolved at import time, so a misconfigured
deploy fails at boot rather than on the first request that happens to need them.
"""

from .base import *
from .base import env

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")

# A bare IP cannot hold a Let's Encrypt certificate, so the first deploy of a
# new droplet runs over plain HTTP until a hostname exists. Everything that
# assumes TLS hangs off this one flag: with it on and no certificate, the SSL
# redirect loops forever and neither session nor CSRF cookie is ever set, which
# locks the dashboard out entirely. Turn it back on the moment certbot has run.
SECURE_SSL = env.bool("DJANGO_SECURE_SSL", default=True)

SECURE_SSL_REDIRECT = SECURE_SSL
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS is deliberately separate from SECURE_SSL, because it is the one setting
# here a mistake in cannot be taken back: once a browser has seen the header it
# refuses plain http to this host for the full duration, no matter what the
# server later sends. An IP certificate is issued under Let's Encrypt's
# "shortlived" profile and expires in 160 hours, so a host reached by IP is one
# stalled renewal away from needing that http fallback. Deploys like that set
# this to 0 and keep it there until the API lives on a hostname with a 90-day
# certificate.
_default_hsts = 60 * 60 * 24 * 365 if SECURE_SSL else 0
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=_default_hsts)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# The dashboard is server-rendered and same-origin, so it uses ordinary sessions.
# The SPA uses JWT because *.vercel.app is on the Public Suffix List and can never
# share a cookie with this host.
SESSION_COOKIE_SECURE = SECURE_SSL
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = SECURE_SSL
CSRF_COOKIE_SAMESITE = "Lax"

_redis_url = env("REDIS_URL", default="")
if _redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_url,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache_table",
        }
    }

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

_sentry_dsn = env("SENTRY_DSN", default="")
if _sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=_sentry_dsn, traces_sample_rate=0.1, send_default_pii=False)
