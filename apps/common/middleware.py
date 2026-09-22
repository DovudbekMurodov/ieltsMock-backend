"""Cache-safety defaults.

Responses are private and uncacheable unless a view explicitly opts in. The
inverse default is how a shared cache ends up serving one user's attempt review
to another, so the safe state is the default state and public caching is the
deliberate act.
"""

from django.utils.cache import patch_vary_headers

PUBLIC_FLAG = "_cache_public"


def cache_public(response, *, max_age: int, stale_while_revalidate: int | None = None):
    """Mark a response as safe for shared caches."""
    directives = [f"public, max-age={max_age}"]
    if stale_while_revalidate:
        directives.append(f"stale-while-revalidate={stale_while_revalidate}")
    response["Cache-Control"] = ", ".join(directives)
    setattr(response, PUBLIC_FLAG, True)
    return response


class PrivateByDefaultCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if getattr(response, PUBLIC_FLAG, False):
            # A public payload still varies by Origin so a shared cache cannot
            # hand a response with the wrong CORS header to another origin.
            patch_vary_headers(response, ("Origin",))
            return response

        response.setdefault("Cache-Control", "private, no-store")
        patch_vary_headers(response, ("Cookie", "Authorization", "Origin"))
        return response
