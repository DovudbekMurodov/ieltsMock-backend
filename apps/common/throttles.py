"""Named throttle scopes.

The default anon/user ceilings catch runaway clients. These tighter scopes
guard the endpoints where abuse is cheap and costly: credentials, and anything
that writes a row per call.
"""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class AuthThrottle(AnonRateThrottle):
    """Sign-in and sign-up, keyed on the caller's address."""

    scope = "auth"


class WriteThrottle(UserRateThrottle):
    """Authenticated writes -- autosave is frequent but not unbounded."""

    scope = "write"


class AnonWriteThrottle(AnonRateThrottle):
    """The same ceiling for guests, who are not identified by an account."""

    scope = "write"
