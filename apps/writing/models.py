from django.db import models

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
