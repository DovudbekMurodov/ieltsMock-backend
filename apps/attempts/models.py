import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class AttemptStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    SUBMITTED = "submitted", "Submitted"
    EXPIRED = "expired", "Submitted after time expired"
    ABANDONED = "abandoned", "Abandoned"


class TestAttempt(TimeStampedModel):
    """One sitting of one test.

    ``user`` is null for a guest attempt; ``guest_id`` then identifies the
    visitor and the attempt can be claimed into an account on signup.
    """

    # pytest collects any class named Test*; this model is not a test case.
    __test__ = False

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name="attempts",
    )
    guest_id = models.UUIDField(null=True, blank=True, db_index=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    test = models.ForeignKey("content.Test", on_delete=models.PROTECT, related_name="attempts")
    # Snapshots, so later content edits never rewrite history.
    test_version = models.PositiveIntegerField(default=1)
    band_scale = models.ForeignKey(
        "grading.BandScale", null=True, blank=True, on_delete=models.PROTECT
    )

    status = models.CharField(
        max_length=16, choices=AttemptStatus.choices, default=AttemptStatus.IN_PROGRESS,
        db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    raw_score = models.PositiveSmallIntegerField(null=True, blank=True)
    raw_total = models.PositiveSmallIntegerField(null=True, blank=True)
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    band = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    band_low = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    band_high = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    band_confidence = models.CharField(max_length=8, default="low")

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["user", "-submitted_at"]),
            models.Index(fields=["test", "-submitted_at"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self):
        return f"{self.test.slug} / {self.user or 'guest'}"

    @property
    def is_open(self) -> bool:
        return self.status == AttemptStatus.IN_PROGRESS

    @property
    def seconds_remaining(self) -> int:
        return max(0, int((self.expires_at - timezone.now()).total_seconds()))

    def owned_by(self, *, user=None, guest_id=None) -> bool:
        if self.user_id and user is not None and getattr(user, "id", None) == self.user_id:
            return True
        if self.user_id is None and guest_id is not None and self.guest_id == guest_id:
            return True
        return False


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(TestAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey("content.Question", on_delete=models.PROTECT)

    # Snapshots taken at scoring time: analytics wants the question as it was.
    question_number = models.PositiveSmallIntegerField()
    question_type = models.CharField(max_length=16)

    raw_value = models.TextField(blank=True)
    normalized_value = models.TextField(blank=True)
    selected_option = models.ForeignKey(
        "content.Option", null=True, blank=True, on_delete=models.SET_NULL
    )
    is_correct = models.BooleanField(null=True)
    answered_at = models.DateTimeField(default=timezone.now)
    time_spent_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("attempt", "question_number")
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"], name="unique_answer_per_attempt_question"
            )
        ]

    def __str__(self):
        return f"Q{self.question_number} = {self.raw_value[:30]}"
