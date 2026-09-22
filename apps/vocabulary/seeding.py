from django.db import transaction

from apps.common.models import PublishStatus

from .models import VocabularySection, VocabularyWord


@transaction.atomic
def seed_section(raw: dict, order: int) -> VocabularySection:
    section, _ = VocabularySection.objects.update_or_create(
        slug=raw["id"],
        defaults={"title": raw["title"], "order": order, "status": PublishStatus.PUBLISHED},
    )
    section.words.all().delete()
    for index, word in enumerate(raw["words"], start=1):
        VocabularyWord.objects.create(
            section=section,
            headword=word["word"],
            pos=word["pos"],
            definition=word["definition"],
            example=word["example"],
            order=index,
        )
    return section
