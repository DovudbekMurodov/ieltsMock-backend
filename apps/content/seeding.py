"""Import the frontend's flat test JSON into the relational content model.

Idempotent: tests are matched on slug and their section tree is rebuilt. Once
attempts exist, AttemptAnswer protects its questions, so a re-seed that would
destroy answered questions fails loudly instead of silently discarding data.
"""

from django.db import transaction

from apps.common.models import PublishStatus

from .enums import MatchMode, OptionsScope, QuestionType, Skill
from .models import AnswerKey, Block, Option, Question, QuestionGroup, Section, Test

# The source data types museum-tour q5 as 'matching', but it has four
# per-question options and no shared pool -- structurally an MCQ. The frontend
# renders 'mcq' and 'matching' through the same branch, which is how it went
# unnoticed. Recorded explicitly so the shared-pool assertion below stays strict.
TYPE_OVERRIDES = {
    ("museum-tour", 5): QuestionType.MCQ,
}


class SeedError(RuntimeError):
    pass


def _question_type(test_slug: str, raw: dict) -> str:
    return TYPE_OVERRIDES.get((test_slug, raw["id"]), raw["type"])


def _group_runs(test_slug: str, questions: list[dict]) -> list[list[dict]]:
    """Split a flat question list into runs of a single type.

    A run is exactly what IELTS calls a numbered instruction block, so this
    recovers the grouping the source data already encodes by ordering.
    """
    runs: list[list[dict]] = []
    previous = None
    for raw in questions:
        current = _question_type(test_slug, raw)
        if current != previous:
            runs.append([])
            previous = current
        runs[-1].append(raw)
    return runs


def _assert_shared_pool(test_slug: str, run: list[dict]) -> list[str]:
    """Matching questions in one group must draw from one identical pool."""
    pools = {tuple(raw["options"]) for raw in run}
    if len(pools) != 1:
        raise SeedError(
            f"{test_slug}: matching questions {[r['id'] for r in run]} do not share "
            f"one option pool ({len(pools)} distinct pools found). Either they belong "
            f"to separate groups or one is mistyped."
        )
    return list(pools.pop())


def _build_group(section: Section, order: int, test_slug: str, run: list[dict]) -> None:
    qtype = _question_type(test_slug, run[0])
    is_matching = qtype == QuestionType.MATCHING

    group = QuestionGroup.objects.create(
        section=section,
        order=order,
        type=qtype,
        options_scope=OptionsScope.SHARED if is_matching else OptionsScope.PER_QUESTION,
        match_mode=MatchMode.NORMALIZED if qtype == QuestionType.GAP else MatchMode.EXACT,
    )

    shared_options: dict[str, Option] = {}
    if is_matching:
        for index, text in enumerate(_assert_shared_pool(test_slug, run), start=1):
            shared_options[text] = Option.objects.create(
                group=group, question=None, order=index, text=text
            )

    for position, raw in enumerate(run, start=1):
        question = Question.objects.create(
            group=group,
            test=section.test,
            order=position,
            number=raw["id"],
            prompt=raw["prompt"],
        )

        if qtype == QuestionType.GAP:
            for index, value in enumerate(raw["acceptedAnswers"]):
                AnswerKey.objects.create(question=question, value=value, order=index)
        elif qtype == QuestionType.TFNG:
            AnswerKey.objects.create(question=question, value=raw["answer"])
        elif is_matching:
            option = shared_options[raw["answer"]]
            AnswerKey.objects.create(question=question, option=option, value=option.text)
        else:  # mcq
            options = {
                text: Option.objects.create(
                    group=group, question=question, order=index, text=text
                )
                for index, text in enumerate(raw["options"], start=1)
            }
            if raw["answer"] not in options:
                raise SeedError(
                    f"{test_slug} q{raw['id']}: answer {raw['answer']!r} is not one of its options."
                )
            option = options[raw["answer"]]
            AnswerKey.objects.create(question=question, option=option, value=option.text)


@transaction.atomic
def seed_test(raw: dict, skill: str) -> Test:
    body_key = "passage" if skill == Skill.READING else "transcript"
    body = raw[body_key]
    blocks_key = "paragraphs" if skill == Skill.READING else "lines"
    label_key = "label" if skill == Skill.READING else "speaker"

    test, _ = Test.objects.update_or_create(
        slug=raw["id"],
        defaults={
            "skill": skill,
            "title": raw["title"],
            "time_limit_minutes": raw["timeLimitMinutes"],
            "status": PublishStatus.PUBLISHED,
        },
    )

    # Children carry no external identity, so rebuild rather than reconcile.
    test.sections.all().delete()

    section = Section.objects.create(test=test, order=1, title=body["title"])

    for index, block in enumerate(body[blocks_key], start=1):
        Block.objects.create(
            section=section, order=index, label=block[label_key], text=block["text"]
        )

    for order, run in enumerate(_group_runs(test.slug, raw["questions"]), start=1):
        _build_group(section, order, test.slug, run)

    return test
