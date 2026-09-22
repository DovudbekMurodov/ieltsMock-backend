from django.db import transaction

from apps.common.models import PublishStatus

from .models import SpeakingCueCard, SpeakingItem, SpeakingItemKind, SpeakingTopic


@transaction.atomic
def seed_topic(raw: dict, order: int) -> SpeakingTopic:
    topic, _ = SpeakingTopic.objects.update_or_create(
        slug=raw["id"],
        defaults={"title": raw["topic"], "order": order, "status": PublishStatus.PUBLISHED},
    )
    topic.items.all().delete()

    cue = raw["part2"]
    SpeakingCueCard.objects.update_or_create(
        topic=topic,
        defaults={
            "title": cue["title"],
            "prep_seconds": cue["prepSeconds"],
            "speak_seconds": cue["speakSeconds"],
        },
    )

    rows = [
        (1, SpeakingItemKind.QUESTION, raw["part1"]),
        (2, SpeakingItemKind.BULLET, cue["bullets"]),
        (3, SpeakingItemKind.QUESTION, raw["part3"]),
        (3, SpeakingItemKind.PHRASE, raw["phrases"]),
    ]
    for part, kind, texts in rows:
        for index, text in enumerate(texts, start=1):
            SpeakingItem.objects.create(
                topic=topic, part=part, kind=kind, order=index, text=text
            )
    return topic
