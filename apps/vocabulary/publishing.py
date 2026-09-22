from django.db import transaction
from django.utils import timezone

from apps.common.models import PublishStatus
from apps.common.payloads import payload_etag

from .models import split_bold


def build_word(word) -> dict:
    return {
        "id": word.id,
        "word": word.headword,
        "pos": word.pos,
        "definition": word.definition,
        "example": word.example,
        # Pre-parsed so the frontend does not split on '**' itself.
        "exampleParts": split_bold(word.example),
    }


def build_section_payload(section) -> dict:
    words = list(section.words.order_by("order"))
    return {
        "id": section.slug,
        "title": section.title,
        "wordCount": len(words),
        "words": [build_word(w) for w in words],
    }


@transaction.atomic
def publish_section(section):
    payload = build_section_payload(section)
    section.published_payload = payload
    section.payload_etag = payload_etag(payload)
    section.published_at = timezone.now()
    section.status = PublishStatus.PUBLISHED
    section.save(
        update_fields=["published_payload", "payload_etag", "published_at", "status", "updated_at"]
    )
    return section
