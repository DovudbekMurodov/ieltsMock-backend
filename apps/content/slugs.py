"""Slug generation that does not ask a person to invent one."""

from django.utils.text import slugify


def unique_slug(model, value: str, *, field: str = "slug", max_length: int = 120) -> str:
    """A slug derived from `value`, guaranteed free on `model`.

    Collisions get a numeric suffix rather than an error, because the caller is
    usually importing content and the title repeating is not a mistake worth
    stopping for — two tests may legitimately be called "Practice Test 1".

    The suffix is counted rather than random so re-importing the same material
    produces a readable sequence instead of a scatter of hashes.
    """
    base = slugify(value)[:max_length].strip("-") or "untitled"
    candidate = base
    suffix = 2

    while model.objects.filter(**{field: candidate}).exists():
        tail = f"-{suffix}"
        candidate = f"{base[: max_length - len(tail)]}{tail}"
        suffix += 1

    return candidate
