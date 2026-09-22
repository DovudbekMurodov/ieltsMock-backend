from django.db import models

from apps.common.models import PublishStatus, TimeStampedModel


class SpeakingPart(models.IntegerChoices):
    PART_1 = 1, "Part 1"
    PART_2 = 2, "Part 2"
    PART_3 = 3, "Part 3"


class SpeakingItemKind(models.TextChoices):
    QUESTION = "question", "Question"
    BULLET = "bullet", "Cue card bullet"
    PHRASE = "phrase", "Useful phrase"


class SpeakingTopic(TimeStampedModel):
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT, db_index=True
    )
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ("order", "title")

    def __str__(self):
        return self.title


class SpeakingCueCard(models.Model):
    topic = models.OneToOneField(
        SpeakingTopic, on_delete=models.CASCADE, related_name="cue_card"
    )
    title = models.CharField(max_length=255)
    prep_seconds = models.PositiveSmallIntegerField(default=60)
    speak_seconds = models.PositiveSmallIntegerField(default=120)

    def __str__(self):
        return self.title


class SpeakingItem(models.Model):
    """One table for part-1 questions, part-3 questions, cue bullets and phrases.

    They are all ordered strings hanging off a topic; separating them into four
    models would mean four formsets in the dashboard for no gain.
    """

    topic = models.ForeignKey(SpeakingTopic, on_delete=models.CASCADE, related_name="items")
    part = models.PositiveSmallIntegerField(choices=SpeakingPart.choices)
    kind = models.CharField(max_length=16, choices=SpeakingItemKind.choices)
    order = models.PositiveSmallIntegerField(default=1)
    text = models.TextField()

    class Meta:
        ordering = ("topic", "part", "kind", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["topic", "part", "kind", "order"], name="unique_speaking_item_slot"
            )
        ]

    def __str__(self):
        return self.text[:60]
