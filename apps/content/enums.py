from django.db import models


class Skill(models.TextChoices):
    READING = "reading", "Reading"
    LISTENING = "listening", "Listening"


class QuestionType(models.TextChoices):
    TFNG = "tfng", "True / False / Not Given"
    MCQ = "mcq", "Multiple choice"
    GAP = "gap", "Gap fill"
    MATCHING = "matching", "Matching"

    @classmethod
    def uses_options(cls, value) -> bool:
        """Types whose answers are drawn from a set of options."""
        return value in {cls.MCQ, cls.MATCHING}


class OptionsScope(models.TextChoices):
    PER_QUESTION = "per_question", "Per question"
    SHARED = "shared", "Shared pool"


class MatchMode(models.TextChoices):
    EXACT = "exact", "Exact"
    NORMALIZED = "normalized", "Normalized"


class Difficulty(models.TextChoices):
    EASY = "easy", "Easy"
    MEDIUM = "medium", "Medium"
    HARD = "hard", "Hard"


class PlaybackPolicy(models.TextChoices):
    FREE = "free", "Free playback"
    ONCE_NO_SEEK = "once_no_seek", "Play once, no seeking"


class TranscriptVisibility(models.TextChoices):
    DURING_TEST = "during_test", "Visible during the test"
    AFTER_SUBMIT = "after_submit", "Visible after submission"
    NEVER = "never", "Never shown"


# TFNG answers are a fixed vocabulary; the frontend renders the three radio
# choices itself rather than reading them from the data.
TFNG_VALUES = ["TRUE", "FALSE", "NOT GIVEN"]
