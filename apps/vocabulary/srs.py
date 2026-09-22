"""Spaced repetition.

A direct port of the algorithm the frontend already runs in localStorage.
Deliberately not "upgraded" to SM-2 or FSRS: changing the curve would silently
invalidate the schedule every existing user is already on. The signature is
narrow enough to swap later if that is ever a considered decision rather than
an accident.
"""

from datetime import timedelta

from django.utils import timezone

MAX_INTERVAL_DAYS = 60
MIN_INTERVAL_DAYS = 1

RATINGS = ("again", "hard", "good", "easy")


def next_interval(current_days: int, rating: str) -> int:
    if rating not in RATINGS:
        raise ValueError(f"Unknown rating {rating!r}. Expected one of {', '.join(RATINGS)}.")

    nxt = {
        "again": 1,
        "hard": current_days + 1,
        "good": current_days * 2,
        "easy": current_days * 3,
    }[rating]
    return min(MAX_INTERVAL_DAYS, max(MIN_INTERVAL_DAYS, round(nxt)))


def due_at(interval_days: int, *, now=None):
    return (now or timezone.now()) + timedelta(days=interval_days)
