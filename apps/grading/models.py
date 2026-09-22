from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel


class BandScale(TimeStampedModel):
    """A raw-score to band-score conversion table.

    Published IELTS conversion tables disagree with one another and shift by a
    question or so between test papers, so the scale is editable data rather
    than constants in code.
    """

    name = models.CharField(max_length=120)
    skill = models.CharField(max_length=16, db_index=True)
    raw_total = models.PositiveSmallIntegerField(
        default=40,
        help_text="Number of questions the published table is defined over.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Used by tests of this skill that do not name a scale.",
    )
    min_questions_for_confidence = models.PositiveSmallIntegerField(
        default=30,
        help_text=(
            "Attempts with fewer raw questions than this report a band range "
            "rather than a single band."
        ),
    )
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("skill", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["skill"],
                condition=models.Q(is_default=True),
                name="one_default_band_scale_per_skill",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.skill})"

    def lookup(self, scaled_raw: int) -> Decimal | None:
        """Return the band for a raw score already scaled to ``raw_total``."""
        row = self.rows.filter(raw_min__lte=scaled_raw, raw_max__gte=scaled_raw).first()
        return row.band if row else None

    def validate_rows(self):
        """Rows must cover 0..raw_total exactly once, with no gaps or overlaps."""
        rows = list(self.rows.order_by("raw_min"))
        if not rows:
            raise ValidationError("A band scale needs at least one row.")

        expected = 0
        for row in rows:
            if row.raw_min != expected:
                raise ValidationError(
                    f"Gap or overlap at raw score {expected}: next row starts at {row.raw_min}."
                )
            if row.raw_max < row.raw_min:
                raise ValidationError(f"Row {row.raw_min}-{row.raw_max} has max below min.")
            expected = row.raw_max + 1

        if expected != self.raw_total + 1:
            raise ValidationError(
                f"Rows cover 0-{expected - 1} but raw_total is {self.raw_total}."
            )


class BandScaleRow(models.Model):
    scale = models.ForeignKey(BandScale, on_delete=models.CASCADE, related_name="rows")
    raw_min = models.PositiveSmallIntegerField()
    raw_max = models.PositiveSmallIntegerField()
    band = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        validators=[MinValueValidator(Decimal("0.0")), MaxValueValidator(Decimal("9.0"))],
    )

    class Meta:
        ordering = ("scale", "raw_min")
        constraints = [
            models.UniqueConstraint(fields=["scale", "raw_min"], name="unique_row_start_per_scale"),
            models.CheckConstraint(
                condition=models.Q(raw_max__gte=models.F("raw_min")),
                name="band_row_max_gte_min",
            ),
        ]

    def __str__(self):
        return f"{self.raw_min}-{self.raw_max} -> {self.band}"
