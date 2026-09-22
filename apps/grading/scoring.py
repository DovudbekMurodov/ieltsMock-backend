"""Scoring -- one code path for all four question types."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from apps.content.enums import QuestionType

from .normalize import normalize_for_group


@dataclass
class AnswerOutcome:
    question_id: int
    number: int
    type: str
    given: str
    normalized: str
    is_correct: bool


@dataclass
class ScoreResult:
    raw_score: int
    raw_total: int
    outcomes: list[AnswerOutcome] = field(default_factory=list)

    @property
    def percent(self) -> Decimal:
        # Decimal at two places so it matches the column and serialises the
        # same way whether it came from memory or from the database.
        if not self.raw_total:
            return Decimal("0.00")
        ratio = Decimal(self.raw_score) / Decimal(self.raw_total) * 100
        return ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def score_answer(question, group, raw_value, *, selected_option_id=None) -> tuple[bool, str]:
    """Return (is_correct, normalised value).

    All four types reduce to the same shape: load the keys, normalise both
    sides with the group's rules, compare. tfng, mcq and matching have exactly
    one key and compare exactly; gap has several and compares loosely.
    """
    keys = list(question.answer_keys.all())
    if not keys:
        return False, ""

    # For option-backed types the option id is authoritative when supplied --
    # two options could carry identical text.
    if QuestionType.uses_options(group.type) and selected_option_id is not None:
        correct = any(k.option_id == selected_option_id for k in keys)
        chosen = next(
            (o for o in group_options(group, question) if o.id == selected_option_id), None
        )
        return correct, normalize_for_group(chosen.text if chosen else "", group)

    normalized = normalize_for_group(raw_value, group)
    if not normalized:
        return False, ""

    return any(normalize_for_group(k.value, group) == normalized for k in keys), normalized


def group_options(group, question):
    return group.options.all() if group.has_shared_pool else question.options.all()


def score_attempt(attempt) -> ScoreResult:
    """Score every question on the attempt's test. Idempotent.

    Unanswered questions count as wrong, which is how IELTS marks them -- there
    is no penalty, but there is no credit either.
    """
    from apps.content.models import Question

    questions = (
        Question.objects.filter(test=attempt.test)
        .select_related("group")
        .prefetch_related("answer_keys", "options", "group__options")
        .order_by("number")
    )
    answers = {a.question_id: a for a in attempt.answers.all()}

    outcomes = []
    score = 0
    for question in questions:
        answer = answers.get(question.id)
        given = answer.raw_value if answer else ""
        selected = answer.selected_option_id if answer else None

        is_correct, normalized = score_answer(
            question, question.group, given, selected_option_id=selected
        )
        score += is_correct
        outcomes.append(
            AnswerOutcome(
                question_id=question.id,
                number=question.number,
                type=question.group.type,
                given=given,
                normalized=normalized,
                is_correct=is_correct,
            )
        )

    return ScoreResult(raw_score=score, raw_total=len(outcomes), outcomes=outcomes)
