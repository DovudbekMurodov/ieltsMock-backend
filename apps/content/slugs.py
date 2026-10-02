"""Slug generation that does not ask a person to invent one."""

import secrets

from django.utils.text import slugify

# No vowels, so a generated suffix cannot land on a word; no l/1/0/o, so it can
# be read back off a screen without ambiguity.
ALPHABET = "23456789bcdfghjkmnpqrstvwxyz"
SUFFIX_LENGTH = 6


def random_suffix(length: int = SUFFIX_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def unique_slug(model, value: str, *, field: str = "slug", max_length: int = 120) -> str:
    """A slug derived from `value`, guaranteed free on `model`.

    A collision takes a random suffix rather than a counted one. Counting reads
    better in a list, but it also means the slug of the second import depends
    on how many imports came before it, so re-running the same import twice
    produces different URLs each time. A random tag is stable per test and
    needs no scan to pick.

    It still checks, because 28^6 is small enough to lose a coin flip on
    eventually and a duplicate here would be a 500 at the point of import.
    """
    base = slugify(value)[:max_length].strip("-") or "untitled"

    if not model.objects.filter(**{field: base}).exists():
        return base

    while True:
        tail = f"-{random_suffix()}"
        candidate = f"{base[: max_length - len(tail)]}{tail}"
        if not model.objects.filter(**{field: candidate}).exists():
            return candidate
