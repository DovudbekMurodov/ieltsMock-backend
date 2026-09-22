from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import PublishStatus, TimeStampedModel

from .enums import (
    TFNG_VALUES,
    Difficulty,
    MatchMode,
    OptionsScope,
    PlaybackPolicy,
    QuestionType,
    Skill,
    TranscriptVisibility,
)


def audio_upload_path(instance, filename):
    """Content-addressed storage path.

    Using the checksum rather than the uploaded filename gives free dedupe, no
    path traversal, no collisions, and immutable URLs -- which is what allows
    the long cache headers on audio.
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    digest = instance.checksum_sha256
    return f"audio/{digest[:2]}/{digest}.{suffix}"


class AudioAsset(TimeStampedModel):
    file = models.FileField(upload_to=audio_upload_path)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=80)
    size_bytes = models.PositiveIntegerField()
    duration_ms = models.PositiveIntegerField()
    checksum_sha256 = models.CharField(max_length=64, unique=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.original_filename

    @property
    def duration_seconds(self) -> float:
        return round(self.duration_ms / 1000, 1)


class Test(TimeStampedModel):
    """A reading or listening test.

    Reading passages and listening transcripts are the same structure with a
    renamed field, so both skills share one model tree. Everything downstream --
    scoring, attempts, analytics, the editor -- is then written once.
    """

    # pytest collects any class named Test*; this model is not a test case.
    __test__ = False

    skill = models.CharField(max_length=16, choices=Skill.choices, db_index=True)
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    time_limit_minutes = models.PositiveSmallIntegerField()
    difficulty = models.CharField(max_length=16, choices=Difficulty.choices, blank=True)
    status = models.CharField(
        max_length=16, choices=PublishStatus.choices, default=PublishStatus.DRAFT, db_index=True
    )
    band_scale = models.ForeignKey(
        "grading.BandScale",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Leave empty to use the default scale for this skill.",
    )
    version = models.PositiveIntegerField(default=1)

    # Materialised public API response. Reads become one row with no joins, and
    # cache invalidation collapses into the publish step.
    published_payload = models.JSONField(null=True, blank=True, editable=False)
    payload_etag = models.CharField(max_length=64, blank=True, editable=False)
    published_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ("skill", "title")
        indexes = [models.Index(fields=["skill", "status"])]

    def __str__(self):
        return self.title

    @property
    def is_published(self) -> bool:
        return self.status == PublishStatus.PUBLISHED and self.published_payload is not None

    @property
    def question_count(self) -> int:
        return Question.objects.filter(test=self).count()


class Section(TimeStampedModel):
    """One passage or one listening section."""

    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)

    audio = models.ForeignKey(
        AudioAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="sections"
    )
    audio_start_ms = models.PositiveIntegerField(null=True, blank=True)
    audio_end_ms = models.PositiveIntegerField(null=True, blank=True)

    playback_policy = models.CharField(
        max_length=16, choices=PlaybackPolicy.choices, default=PlaybackPolicy.FREE
    )
    transcript_visibility = models.CharField(
        max_length=16,
        choices=TranscriptVisibility.choices,
        default=TranscriptVisibility.DURING_TEST,
        help_text=(
            "Once real audio is attached, showing the transcript during the test "
            "turns a listening test into a reading test."
        ),
    )

    class Meta:
        ordering = ("test", "order")
        constraints = [
            models.UniqueConstraint(fields=["test", "order"], name="unique_section_order_per_test")
        ]

    def __str__(self):
        return f"{self.test.slug} / {self.title}"

    def clean(self):
        if self.audio_end_ms is not None and self.audio_start_ms is not None:
            if self.audio_end_ms <= self.audio_start_ms:
                raise ValidationError({"audio_end_ms": "Must be greater than audio_start_ms."})


class Block(models.Model):
    """A paragraph (reading) or a transcript line (listening).

    One ``label`` field serves both: 'A' for a paragraph, 'Staff' for a speaker.
    Only the rendered separator differs, which is presentation.
    """

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="blocks")
    order = models.PositiveSmallIntegerField(default=1)
    label = models.CharField(max_length=60, blank=True)
    text = models.TextField()

    class Meta:
        ordering = ("section", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["section", "order"], name="unique_block_order_per_section"
            )
        ]

    def __str__(self):
        return f"{self.label}: {self.text[:40]}"


class QuestionGroup(models.Model):
    """A numbered instruction block, e.g. "Questions 14-20: TRUE/FALSE/NOT GIVEN".

    ``type`` lives here rather than on Question because real IELTS never mixes
    question types inside one instruction block, and because a shared option
    pool (matching headings) has nowhere else correct to live.
    """

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="groups")
    order = models.PositiveSmallIntegerField(default=1)
    type = models.CharField(max_length=16, choices=QuestionType.choices)
    instructions = models.TextField(blank=True)
    options_scope = models.CharField(
        max_length=16, choices=OptionsScope.choices, default=OptionsScope.PER_QUESTION
    )
    match_mode = models.CharField(
        max_length=16, choices=MatchMode.choices, default=MatchMode.EXACT
    )
    allow_article_omission = models.BooleanField(default=False)
    allow_plural_variants = models.BooleanField(
        default=False,
        help_text=(
            "Off by default: real IELTS marks a singular/plural mismatch wrong. "
            "Prefer adding an explicit accepted answer."
        ),
    )

    class Meta:
        ordering = ("section", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["section", "order"], name="unique_group_order_per_section"
            )
        ]

    def __str__(self):
        return f"{self.section.test.slug} / {self.get_type_display()} #{self.order}"

    @property
    def uses_options(self) -> bool:
        return QuestionType.uses_options(self.type)

    @property
    def has_shared_pool(self) -> bool:
        return self.options_scope == OptionsScope.SHARED

    def clean(self):
        errors = {}

        if self.type == QuestionType.MATCHING and not self.has_shared_pool:
            errors["options_scope"] = "Matching groups draw from a shared option pool."
        if self.type != QuestionType.MATCHING and self.has_shared_pool:
            errors["options_scope"] = f"{self.get_type_display()} groups use per-question options."

        if self.type == QuestionType.GAP and self.match_mode != MatchMode.NORMALIZED:
            errors["match_mode"] = "Gap-fill answers are compared with normalisation."
        if self.type != QuestionType.GAP and self.match_mode != MatchMode.EXACT:
            errors["match_mode"] = "Only gap-fill groups use normalised matching."

        if errors:
            raise ValidationError(errors)


class Question(models.Model):
    group = models.ForeignKey(QuestionGroup, on_delete=models.CASCADE, related_name="questions")
    # Denormalised so the display-number constraint can be expressed at all.
    test = models.ForeignKey(
        Test, on_delete=models.CASCADE, related_name="questions", editable=False
    )
    order = models.PositiveSmallIntegerField(default=1)
    number = models.PositiveSmallIntegerField(
        help_text="Display number within the whole test; recomputed on publish."
    )
    prompt = models.TextField()
    explanation = models.TextField(
        blank=True, help_text="Shown only in the post-submission review payload."
    )

    class Meta:
        ordering = ("test", "number")
        constraints = [
            models.UniqueConstraint(
                fields=["group", "order"], name="unique_question_order_per_group"
            ),
            models.UniqueConstraint(
                fields=["test", "number"], name="unique_question_number_per_test"
            ),
        ]

    def __str__(self):
        return f"Q{self.number}: {self.prompt[:50]}"

    def save(self, *args, **kwargs):
        if self.group_id and not self.test_id:
            self.test_id = self.group.section.test_id
        super().save(*args, **kwargs)

    @property
    def type(self) -> str:
        return self.group.type


class Option(models.Model):
    """A choice. ``question`` is NULL for a group-level shared pool."""

    group = models.ForeignKey(QuestionGroup, on_delete=models.CASCADE, related_name="options")
    question = models.ForeignKey(
        Question, null=True, blank=True, on_delete=models.CASCADE, related_name="options"
    )
    order = models.PositiveSmallIntegerField(default=1)
    label = models.CharField(max_length=8, blank=True)
    text = models.TextField()

    class Meta:
        ordering = ("group", "question", "order")

    def __str__(self):
        return self.text[:60]

    def clean(self):
        if self.group_id:
            if self.group.has_shared_pool and self.question_id is not None:
                raise ValidationError({"question": "Shared-pool options belong to the group."})
            if not self.group.has_shared_pool and self.question_id is None:
                raise ValidationError({"question": "Per-question options need a question."})


class AnswerKey(models.Model):
    """The authoritative answer(s) for one question.

    Kept out of Option.is_correct because a shared matching option cannot carry
    a per-question truth value, TFNG has no options to flag, and gap-fill needs
    several accepted strings. Keeping keys in their own table also means the
    public serializer never traverses the relation, so leaking takes effort
    rather than vigilance.
    """

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answer_keys")
    option = models.ForeignKey(
        Option,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="answer_keys",
        help_text="Set when the group's type draws from an option set.",
    )
    value = models.TextField(help_text="Authoritative answer string.")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("question", "order")

    def __str__(self):
        return self.value[:60]

    def save(self, *args, **kwargs):
        # Keep the denormalised copy in step with the referenced option.
        if self.option_id and not self.value:
            self.value = self.option.text
        super().save(*args, **kwargs)

    def clean(self):
        if not self.question_id:
            return
        group = self.question.group

        if group.uses_options:
            if self.option_id is None:
                raise ValidationError(
                    {"option": f"{group.get_type_display()} answers must reference an option."}
                )
            if self.option.group_id != group.id:
                raise ValidationError({"option": "Option belongs to a different group."})
        else:
            if self.option_id is not None:
                raise ValidationError(
                    {"option": f"{group.get_type_display()} answers do not use options."}
                )

        if group.type == QuestionType.TFNG and self.value not in TFNG_VALUES:
            raise ValidationError({"value": f"Must be one of {', '.join(TFNG_VALUES)}."})
