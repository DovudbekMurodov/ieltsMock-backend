"""Cache-key versioning.

Every derived cache key is prefixed with a global content version. Bumping the
version on publish orphans every derived key atomically -- no dependency graph
to maintain, and no way to miss one. Orphans fall out on their own TTL.
"""

from django.core.cache import cache

VERSION_KEY = "content:version"
DEFAULT_TIMEOUT = 60 * 10


def content_version() -> int:
    version = cache.get(VERSION_KEY)
    if version is None:
        version = 1
        cache.set(VERSION_KEY, version, None)
    return version


def bump_content_version() -> int:
    try:
        return cache.incr(VERSION_KEY)
    except ValueError:
        # Key expired or was evicted between read and increment.
        cache.set(VERSION_KEY, 2, None)
        return 2


def versioned_key(*parts) -> str:
    return "v{}:{}".format(content_version(), ":".join(str(p) for p in parts))
