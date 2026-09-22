from django.conf import settings
from django.db import models
from django.utils import timezone


class Event(models.Model):
    """One named thing that happened.

    Deliberately not a log of every request: that buries the signal, bloats the
    table by an order of magnitude, and makes every dashboard query expensive.
    """

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    name = models.CharField(max_length=48)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    # Survives login, so a guest's activity can be stitched to the account they
    # later create.
    anon_id = models.UUIDField(null=True, blank=True, db_index=True)
    object_type = models.CharField(max_length=32, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    skill = models.CharField(max_length=16, blank=True)
    path = models.CharField(max_length=200, blank=True)
    # Salted hash, never the address itself.
    ip_hash = models.CharField(max_length=64, blank=True)
    ua_family = models.CharField(max_length=40, blank=True)
    props = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=["name", "occurred_at"]),
            models.Index(fields=["user", "occurred_at"]),
            models.Index(fields=["object_type", "object_id", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.name} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class DailyMetric(models.Model):
    """A generic daily KPI, so new numbers need no migration."""

    date = models.DateField(db_index=True)
    metric_key = models.CharField(max_length=48)
    dimension_key = models.CharField(max_length=64, blank=True)
    value_int = models.IntegerField(default=0)
    value_dec = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ("-date", "metric_key")
        constraints = [
            models.UniqueConstraint(
                fields=["date", "metric_key", "dimension_key"], name="unique_metric_per_day"
            )
        ]

    def __str__(self):
        return f"{self.date} {self.metric_key} {self.dimension_key}={self.value_int}"


class TestStat(models.Model):
    # pytest collects any class named Test*; this model is not a test case.
    __test__ = False

    test = models.ForeignKey("content.Test", on_delete=models.CASCADE, related_name="stats")
    date = models.DateField(db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    completions = models.PositiveIntegerField(default=0)
    avg_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    avg_band = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    median_duration_s = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["test", "date"], name="unique_test_stat_per_day")
        ]

    def __str__(self):
        return f"{self.test.slug} {self.date}"


class QuestionStat(models.Model):
    """Item analysis.

    A question sitting at 0% or 100% accuracy is usually broken rather than
    hard -- an ambiguous prompt, a wrong key, or a giveaway. This is what makes
    the tool a CMS rather than a form, and it is impossible with content stored
    as an opaque blob.
    """

    question = models.ForeignKey(
        "content.Question", on_delete=models.CASCADE, related_name="stats"
    )
    date = models.DateField(db_index=True)
    seen = models.PositiveIntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    accuracy = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ("accuracy",)
        constraints = [
            models.UniqueConstraint(
                fields=["question", "date"], name="unique_question_stat_per_day"
            )
        ]

    def __str__(self):
        return f"Q{self.question_id} {self.date} {self.accuracy}%"


class UserProgress(models.Model):
    """Per-skill standing. Upserted rather than kept per day."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="progress"
    )
    skill = models.CharField(max_length=16)
    attempts = models.PositiveIntegerField(default=0)
    best_band = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    latest_band = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    avg_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    streak_days = models.PositiveIntegerField(default=0)
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("user", "skill")
        constraints = [
            models.UniqueConstraint(fields=["user", "skill"], name="unique_progress_per_skill")
        ]

    def __str__(self):
        return f"{self.user} / {self.skill}"
