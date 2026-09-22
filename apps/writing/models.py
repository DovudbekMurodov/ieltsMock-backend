import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import PublishStatus, TimeStampedModel


class WritingTaskType(models.TextChoices):
    AGREE_DISAGREE = "agree_disagree", "Agree or Disagree"
    ADVANTAGES_DISADVANTAGES = "advantages_disadvantages", "Advantages / Disadvantages"
    DISCUSS_BOTH_VIEWS = "discuss_both_views", "Discuss Both Views"
    PROBLEM_SOLUTION = "problem_solution", "Problem / Solution"
    POSITIVE_NEGATIVE = "positive_negative", "Positive or Negative Development"
    TASK1_CHART = "task1_chart", "Task 1 — Chart or Graph"
    TASK1_PROCESS = "task1_process", "Task 1 — Process"
    TASK1_MAP = "task1_map", "Task 1 — Map"
    TASK1_LETTER = "task1_letter", "Task 1 — Letter (General Training)"


class RevealPolicy(models.TextChoices):
    ALWAYS = "always", "Always available"
    AFTER_SUBMISSION = "after_submission", "Only after the student submits"


class WritingTask(TimeStampedModel):
    slug = models.SlugField(max_length=120, unique=True)
    task_number = models.PositiveSmallIntegerField(default=2)
    type = models.CharField(max_length=32, choices=WritingTaskType.choices)
    prompt = models.TextField()
    image = models.ImageField(upload_to="writing/", null=True, blank=True)
    suggested_time_minutes = models.PositiveSmallIntegerField(default=40)
    target_words = models.PositiveSmallIntegerField(default=250)
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT, db_index=True
    )
    reveal_policy = models.CharField(
        max_length=20, choices=RevealPolicy.choices, default=RevealPolicy.ALWAYS
    )

    class Meta:
        ordering = ("task_number", "slug")

    def __str__(self):
        return self.prompt[:60]


class WritingModelAnswer(models.Model):
    """A worked example answer.

    ``body`` keeps its blank-line paragraph breaks verbatim -- the frontend
    splits on them, so stripping or normalising whitespace silently destroys
    the formatting.
    """

    task = models.ForeignKey(WritingTask, on_delete=models.CASCADE, related_name="model_answers")
    band = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    body = models.TextField()
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ("task", "order")

    def __str__(self):
        return f"{self.task.slug} model answer"

    @property
    def paragraphs(self) -> list[str]:
        return self.body.split("\n\n")


class SubmissionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Awaiting feedback"
    GRADED = "graded", "Graded"


class WritingSubmission(TimeStampedModel):
    """What a student actually wrote.

    Guests may write too, keyed on the same opaque id as their test attempts,
    so the work is not lost if they sign up afterwards.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="writing_submissions",
    )
    guest_id = models.UUIDField(null=True, blank=True, db_index=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    task = models.ForeignKey(WritingTask, on_delete=models.PROTECT, related_name="submissions")
    body = models.TextField(blank=True)
    word_count = models.PositiveIntegerField(default=0)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=SubmissionStatus.choices, default=SubmissionStatus.DRAFT,
        db_index=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    self_assessed_band = models.DecimalField(
        max_digits=2, decimal_places=1, null=True, blank=True
    )
    model_answer_revealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-submitted_at", "-created_at")
        indexes = [
            models.Index(fields=["status", "-submitted_at"]),
            models.Index(fields=["user", "-submitted_at"]),
        ]

    def __str__(self):
        return f"{self.task.slug} / {self.user or 'guest'}"

    def owned_by(self, *, user=None, guest_id=None) -> bool:
        if self.user_id and user is not None and getattr(user, "id", None) == self.user_id:
            return True
        return self.user_id is None and guest_id is not None and self.guest_id == guest_id

    @property
    def meets_target(self) -> bool:
        return self.word_count >= self.task.target_words


class WritingFeedback(TimeStampedModel):
    """A grader's marks against the four official criteria.

    The overall band is derived rather than typed, so it can never disagree
    with the four parts it is meant to summarise.
    """

    submission = models.OneToOneField(
        WritingSubmission, on_delete=models.CASCADE, related_name="feedback"
    )
    grader = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="graded"
    )
    task_achievement = models.DecimalField(max_digits=2, decimal_places=1)
    coherence_cohesion = models.DecimalField(max_digits=2, decimal_places=1)
    lexical_resource = models.DecimalField(max_digits=2, decimal_places=1)
    grammatical_range = models.DecimalField(max_digits=2, decimal_places=1)
    overall = models.DecimalField(max_digits=2, decimal_places=1)
    comment = models.TextField(blank=True)

    def __str__(self):
        return f"{self.submission} -> {self.overall}"

    def save(self, *args, **kwargs):
        from apps.grading.bands import round_to_half_band

        criteria = [
            self.task_achievement,
            self.coherence_cohesion,
            self.lexical_resource,
            self.grammatical_range,
        ]
        self.overall = round_to_half_band(sum(criteria) / len(criteria))
        super().save(*args, **kwargs)

        if self.submission.status != SubmissionStatus.GRADED:
            self.submission.status = SubmissionStatus.GRADED
            self.submission.save(update_fields=["status", "updated_at"])


def count_words(text: str) -> int:
    """Whitespace-separated tokens, which is how IELTS counts."""
    return len(text.split()) if text and text.strip() else 0


def mark_submitted(submission) -> None:
    submission.word_count = count_words(submission.body)
    submission.status = SubmissionStatus.SUBMITTED
    submission.submitted_at = submission.submitted_at or timezone.now()
    submission.save()
