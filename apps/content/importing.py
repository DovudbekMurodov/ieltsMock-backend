"""Build a draft test from a JSON document.

Written for material an AI produced from the template in `TEMPLATE`, which
means two things shape this module.

It is liberal in what it accepts. The frontend's export calls a reading body
`passage`/`paragraphs`/`label` and a listening body `transcript`/`lines`/
`speaker` — the same three slots under six names. A model filling a template
will mix them, and refusing over it teaches nobody anything, so both spellings
are read.

It is strict about what it reports. Every problem in the document is collected
and returned together, each one pointing at the question it came from, because
the alternative is a person fixing one typo per upload through a dozen rounds.

Nothing it creates is published. Import lands a draft in the editor; a human
reads it and presses publish.
"""

from django.db import transaction
from django.utils.text import slugify

from apps.common.models import PublishStatus

from .enums import MatchMode, OptionsScope, QuestionType, Skill
from .models import AnswerKey, Block, Option, Question, QuestionGroup, Section, Test
from .slugs import unique_slug

TFNG_ANSWERS = {"TRUE", "FALSE", "NOT GIVEN"}
QUESTION_TYPES = {QuestionType.TFNG, QuestionType.MCQ, QuestionType.GAP, QuestionType.MATCHING}


class ImportError_(Exception):
    """Carries every problem found, not just the first."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _body(raw: dict) -> tuple[dict, list[dict], str]:
    """The passage or transcript, under whichever names it arrived with."""
    body = raw.get("passage") or raw.get("transcript") or {}
    blocks = body.get("paragraphs") or body.get("lines") or []
    return body, blocks, body.get("title") or raw.get("title") or ""


def _block_label(block: dict) -> str:
    return str(block.get("label") or block.get("speaker") or "")


def _number(question: dict, fallback: int) -> int:
    """`number` is the documented key; `id` is what the existing exports use."""
    value = question.get("number", question.get("id", fallback))
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _groups_from(raw: dict) -> list[dict]:
    """Explicit groups if the document declares them, otherwise runs of a type.

    A flat question list is the easy thing to write and covers most material.
    Declaring groups is what buys a heading and a rubric of their own, which a
    note-completion task needs.
    """
    if raw.get("groups"):
        return [
            {
                "heading": group.get("heading", ""),
                "instructions": group.get("instructions", ""),
                "questions": group.get("questions") or [],
            }
            for group in raw["groups"]
        ]

    runs: list[dict] = []
    previous = None
    for question in raw.get("questions") or []:
        current = question.get("type")
        if current != previous:
            runs.append({"heading": "", "instructions": "", "questions": []})
            previous = current
        runs[-1]["questions"].append(question)
    return runs


def validate(raw: dict) -> list[str]:
    """Every problem with the document, in the order a person would fix them."""
    problems: list[str] = []

    if not isinstance(raw, dict):
        return ["The document must be a JSON object describing one test."]

    if not str(raw.get("title") or "").strip():
        problems.append("title is required.")

    skill = raw.get("skill")
    if skill not in {Skill.READING, Skill.LISTENING}:
        problems.append(f'skill must be "reading" or "listening" (got {skill!r}).')

    minutes = raw.get("timeLimitMinutes")
    if not isinstance(minutes, int) or minutes <= 0:
        problems.append("timeLimitMinutes must be a whole number of minutes.")

    _, blocks, _ = _body(raw)
    if not blocks:
        problems.append(
            "No passage text. Reading tests use passage.paragraphs; listening tests use "
            "transcript.lines."
        )
    for index, block in enumerate(blocks):
        if not str(block.get("text") or "").strip():
            problems.append(f"paragraph {index + 1} has no text.")

    groups = _groups_from(raw)
    if not groups or not any(group["questions"] for group in groups):
        problems.append("No questions.")

    seen_numbers: dict[int, int] = {}
    position = 0
    for group_index, group in enumerate(groups):
        for question in group["questions"]:
            position += 1
            where = f"question {_number(question, position)}"
            qtype = question.get("type")

            if qtype not in QUESTION_TYPES:
                problems.append(
                    f"{where}: type must be one of tfng, mcq, gap, matching (got {qtype!r})."
                )
                continue

            if not str(question.get("prompt") or "").strip():
                problems.append(f"{where}: prompt is empty.")

            number = _number(question, position)
            if number in seen_numbers:
                problems.append(f"{where}: number {number} is used twice.")
            seen_numbers[number] = group_index

            if qtype == QuestionType.TFNG:
                answer = str(question.get("answer") or "").upper()
                if answer not in TFNG_ANSWERS:
                    problems.append(
                        f'{where}: answer must be "TRUE", "FALSE" or "NOT GIVEN" '
                        f"(got {question.get('answer')!r})."
                    )

            elif qtype == QuestionType.GAP:
                accepted = [a for a in (question.get("acceptedAnswers") or []) if str(a).strip()]
                if not accepted:
                    problems.append(
                        f"{where}: acceptedAnswers must list at least one spelling you will accept."
                    )

            elif qtype == QuestionType.MCQ:
                options = [o for o in (question.get("options") or []) if str(o).strip()]
                if len(options) < 2:
                    problems.append(f"{where}: needs at least two options.")
                elif question.get("answer") not in options:
                    problems.append(
                        f"{where}: answer {question.get('answer')!r} is not one of its options."
                    )

            elif qtype == QuestionType.MATCHING:
                options = [o for o in (question.get("options") or []) if str(o).strip()]
                if len(options) < 2:
                    problems.append(f"{where}: needs at least two options in the shared pool.")
                elif question.get("answer") not in options:
                    problems.append(
                        f"{where}: answer {question.get('answer')!r} is not one of its options."
                    )

        # A matching group is scored against one pool, so the questions in it
        # have to agree on what that pool is.
        matching = [q for q in group["questions"] if q.get("type") == QuestionType.MATCHING]
        if matching:
            pools = {tuple(q.get("options") or []) for q in matching}
            if len(pools) > 1:
                numbers = ", ".join(str(_number(q, 0)) for q in matching)
                problems.append(
                    f"questions {numbers} are matching questions in one group but list "
                    f"{len(pools)} different option pools. Give them the same options, or split "
                    "them into separate groups."
                )

    return problems


@transaction.atomic
def import_test(raw: dict, *, created_by=None) -> Test:
    """Create a draft test. Raises ImportError_ with every problem found."""
    problems = validate(raw)
    if problems:
        raise ImportError_(problems)

    skill = raw["skill"]
    title = raw["title"].strip()

    # The document may name a slug; it is a suggestion. Taking it verbatim is
    # how a second import of the same material silently overwrites the first.
    requested = str(raw.get("slug") or raw.get("id") or "").strip()
    slug = unique_slug(Test, slugify(requested) or title)

    test = Test.objects.create(
        slug=slug,
        skill=skill,
        title=title,
        description=str(raw.get("description") or "").strip(),
        time_limit_minutes=raw["timeLimitMinutes"],
        difficulty=raw.get("difficulty") or "",
        status=PublishStatus.DRAFT,
        created_by=created_by,
    )

    _, blocks, body_title = _body(raw)
    section = Section.objects.create(test=test, order=1, title=body_title or title)

    for index, block in enumerate(blocks, start=1):
        Block.objects.create(
            section=section,
            order=index,
            label=_block_label(block),
            text=block["text"],
        )

    position = 0
    for order, group_data in enumerate(_groups_from(raw), start=1):
        questions = group_data["questions"]
        if not questions:
            continue

        qtype = questions[0]["type"]
        is_matching = qtype == QuestionType.MATCHING

        group = QuestionGroup.objects.create(
            section=section,
            order=order,
            type=qtype,
            heading=group_data["heading"],
            instructions=group_data["instructions"],
            options_scope=OptionsScope.SHARED if is_matching else OptionsScope.PER_QUESTION,
            match_mode=MatchMode.NORMALIZED if qtype == QuestionType.GAP else MatchMode.EXACT,
        )

        shared: dict[str, Option] = {}
        if is_matching:
            for index, text in enumerate(questions[0]["options"], start=1):
                shared[text] = Option.objects.create(
                    group=group, question=None, order=index, text=text
                )

        for slot, raw_question in enumerate(questions, start=1):
            position += 1
            question = Question.objects.create(
                group=group,
                test=test,
                order=slot,
                number=_number(raw_question, position),
                prompt=raw_question["prompt"].strip(),
                explanation=str(raw_question.get("explanation") or "").strip(),
            )

            if qtype == QuestionType.GAP:
                for index, value in enumerate(raw_question["acceptedAnswers"]):
                    AnswerKey.objects.create(question=question, value=str(value), order=index)

            elif qtype == QuestionType.TFNG:
                AnswerKey.objects.create(
                    question=question, value=str(raw_question["answer"]).upper()
                )

            elif is_matching:
                option = shared[raw_question["answer"]]
                AnswerKey.objects.create(question=question, option=option, value=option.text)

            else:  # mcq
                options = {
                    text: Option.objects.create(
                        group=group, question=question, order=index, text=text
                    )
                    for index, text in enumerate(raw_question["options"], start=1)
                }
                option = options[raw_question["answer"]]
                AnswerKey.objects.create(question=question, option=option, value=option.text)

    return test
