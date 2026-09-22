import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import PublishStatus, TimeStampedModel

BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


class PartOfSpeech(models.TextChoices):
    NOUN = "noun", "noun"
    VERB = "verb", "verb"
    ADJECTIVE = "adjective", "adjective"
    ADVERB = "adverb", "adverb"
    PHRASE = "phrase", "phrase"
    PHRASAL_VERB = "phrasal verb", "phrasal verb"


def split_bold(text: str) -> list[dict]:
    """Split ``a **b** c`` into ordered {text, bold} parts.

    Returned by the API so the frontend does not have to parse markers itself.
    """
    parts = []
    cursor = 0
    for match in BOLD_PATTERN.finditer(text):
        if match.start() > cursor:
            parts.append({"text": text[cursor : match.start()], "bold": False})
        parts.append({"text": match.group(1), "bold": True})
        cursor = match.end()
    if cursor < len(text):
        parts.append({"text": text[cursor:], "bold": False})
    return parts


class VocabularySection(TimeStampedModel):
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT, db_index=True
    )

    published_payload = models.JSONField(null=True, blank=True, editable=False)
    payload_etag = models.CharField(max_length=64, blank=True, editable=False)
    published_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("order", "title")

    def __str__(self):
        return self.title


class VocabularyWord(models.Model):
    section = models.ForeignKey(
        VocabularySection, on_delete=models.CASCADE, related_name="words"
    )
    headword = models.CharField(max_length=80)
    pos = models.CharField(max_length=20, choices=PartOfSpeech.choices)
    definition = models.TextField()
    example = models.TextField(
        help_text="Must contain exactly one **bolded** span, which is the word in context."
    )
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ("section", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["section", "headword"], name="unique_headword_per_section"
            )
        ]

    def __str__(self):
        return self.headword

    def clean(self):
        if self.example and len(BOLD_PATTERN.findall(self.example)) != 1:
            raise ValidationError(
                {"example": "The example must contain exactly one **bolded** span."}
            )

    @property
    def example_parts(self) -> list[dict]:
        return split_bold(self.example)


class VocabularyReviewState(models.Model):
    """Where one user stands on one word."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vocabulary_states"
    )
    word = models.ForeignKey(
        VocabularyWord, on_delete=models.CASCADE, related_name="review_states"
    )
    interval_days = models.PositiveSmallIntegerField(default=1)
    due_at = models.DateTimeField(default=timezone.now, db_index=True)
    reps = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    last_rating = models.CharField(max_length=8, blank=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("due_at",)
        constraints = [
            models.UniqueConstraint(fields=["user", "word"], name="unique_review_state_per_word")
        ]
        indexes = [models.Index(fields=["user", "due_at"])]

    def __str__(self):
        return f"{self.user} / {self.word}"


class VocabularyReviewEvent(models.Model):
    """One rating. Kept so the schedule can be audited or replayed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vocabulary_reviews"
    )
    word = models.ForeignKey(VocabularyWord, on_delete=models.CASCADE)
    rating = models.CharField(max_length=8)
    interval_before = models.PositiveSmallIntegerField()
    interval_after = models.PositiveSmallIntegerField()
    reviewed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-reviewed_at",)

    def __str__(self):
        return f"{self.word} rated {self.rating}"
