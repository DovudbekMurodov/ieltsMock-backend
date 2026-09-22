"""ETag / Last-Modified helpers that share one query.

Django calls etag_func and last_modified_func separately, so a naive
implementation issues two queries before the view body runs -- and a third
inside it. Memoising the lookup on the request makes a conditional hit cost one
query in total, and a 304 never reaches the view body at all.
"""

CACHE_ATTR = "_conditional_cache"


def make_conditional_funcs(lookup):
    """Build (etag_func, last_modified_func) from ``lookup(slug) -> (etag, modified)``."""

    def fetch(request, slug):
        cache = getattr(request, CACHE_ATTR, None)
        if cache is None:
            cache = {}
            setattr(request, CACHE_ATTR, cache)
        if slug not in cache:
            cache[slug] = lookup(slug)
        return cache[slug]

    def etag_func(request, slug):
        etag, _ = fetch(request, slug)
        return f'"{etag}"' if etag else None

    def last_modified_func(request, slug):
        _, modified = fetch(request, slug)
        return modified

    return etag_func, last_modified_func
