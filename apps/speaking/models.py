import uuid

from django.conf import settings
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


class SpeakingSession(TimeStampedModel):
    """A practice run through one topic.

    There is no automatic marking here -- speaking cannot be scored from
    timings. What this records is whether the student actually did the parts
    and how long they used, which is what tells staff a topic is too hard or a
    cue card is unclear.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="speaking_sessions",
    )
    guest_id = models.UUIDField(null=True, blank=True, db_index=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    topic = models.ForeignKey(SpeakingTopic, on_delete=models.PROTECT, related_name="sessions")
    parts_completed = models.JSONField(default=list, blank=True)
    prep_used_seconds = models.PositiveIntegerField(default=0)
    speak_used_seconds = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    self_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.topic.slug} / {self.user or 'guest'}"

    def owned_by(self, *, user=None, guest_id=None) -> bool:
        if self.user_id and user is not None and getattr(user, "id", None) == self.user_id:
            return True
        return self.user_id is None and guest_id is not None and self.guest_id == guest_id

    @property
    def is_complete(self) -> bool:
        return sorted(self.parts_completed) == [1, 2, 3]
