"""Import the ieltsx.com scrape into the content, writing and speaking models.

The scrape lives in one directory per section, each `<pack>/<test>/test.json`
plus its media (see the scraper repo's `data/ieltsx-sections-SCHEMA.md`):

    <data>/ieltsx/            listening (+ audio.mp3, diagram images)
    <data>/ieltsx-reading/    reading
    <data>/ieltsx-writing/    writing (+ Task 1 chart images)
    <data>/ieltsx-speaking/   speaking

ieltsx has seventeen question types; this backend has four. Each source type is
mapped onto the closest one the app can already render and score, so the
frontend needs no change:

    tfng      TRUE_FALSE_NOT_GIVEN
    mcq       MULTIPLE_CHOICE, MULTIPLE_CHOICE_MANY, YES_NO_NOT_GIVEN (YES/NO/NOT GIVEN as options)
    matching  every "choose from the box" type: headings, features, names,
              sentence endings, information (paragraph letters), summary/flow-chart
              with a word list, diagram labelling
    gap       every completion type: note, form, table, sentence, summary,
              short answer, flow-chart, diagram

What does not survive: table and flow-chart layout (each gap becomes its own
prompt carrying its row/column context), and diagram images for reading and
listening (the content model has nowhere to put one). The raw JSON stays in
the data directory for a richer import later.

Idempotent: everything is matched on an `ix-` slug and rebuilt. Existing
content with other slugs is never touched.

    manage.py import_ieltsx --data /srv/ieltsmock-import/data
        [--only reading] [--limit 3] [--no-media] [--dry-run] [--packs-only]
"""

import hashlib
import json
import re
from pathlib import Path

import mutagen
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.common.models import PublishStatus
from apps.content.enums import (
    BlockKind,
    MatchMode,
    OptionsScope,
    QuestionType,
    Skill,
    TranscriptVisibility,
)
from apps.content.models import (
    AnswerKey,
    AudioAsset,
    Block,
    Option,
    Pack,
    Question,
    QuestionGroup,
    Section,
    Test,
)
from apps.speaking.models import SpeakingCueCard, SpeakingItem, SpeakingItemKind, SpeakingTopic
from apps.writing.models import WritingTask, WritingTaskType

DIRS = {
    "listening": "ieltsx",
    "reading": "ieltsx-reading",
    "writing": "ieltsx-writing",
    "speaking": "ieltsx-speaking",
}
BLANK = "______"

GAP_TYPES = {
    "NOTE_COMPLETION",
    "FORM_COMPLETION",
    "SENTENCE_COMPLETION",
    "SHORT_ANSWER_COMPLETION",
    "SUMMARY_COMPLETION",
    "TABLE_COMPLETION",
    "FLOW_CHART_COMPLETION",
    "DIAGRAM_COMPLETION",
}
LIMIT_RE = re.compile(
    r"^(write\s+|choose\s+)?(NO MORE THAN|ONE WORD|TWO WORDS|THREE WORDS|ONLY ONE|A NUMBER)", re.I
)
VERB = {
    "NOTE_COMPLETION": "Complete the notes below.",
    "FORM_COMPLETION": "Complete the form below.",
    "TABLE_COMPLETION": "Complete the table below.",
    "SENTENCE_COMPLETION": "Complete the sentences below.",
    "SUMMARY_COMPLETION": "Complete the summary below.",
    "SHORT_ANSWER_COMPLETION": "Answer the questions below.",
    "DIAGRAM_COMPLETION": "Label the diagram below.",
    "FLOW_CHART_COMPLETION": "Complete the flow-chart below.",
    "FLOW_CHART_MATCHING": "Complete the flow-chart below.",
}

TASK1_TYPES = {
    "map": WritingTaskType.TASK1_MAP,
    "process_diagram": WritingTaskType.TASK1_PROCESS,
    "letter": WritingTaskType.TASK1_LETTER,
}
TASK2_TYPES = {
    "agree_disagree": WritingTaskType.AGREE_DISAGREE,
    "opinion": WritingTaskType.AGREE_DISAGREE,
    "discussion": WritingTaskType.DISCUSS_BOTH_VIEWS,
    "discuss_both_views": WritingTaskType.DISCUSS_BOTH_VIEWS,
    "advantages_disadvantages": WritingTaskType.ADVANTAGES_DISADVANTAGES,
    "problem_solution": WritingTaskType.PROBLEM_SOLUTION,
    "positive_negative": WritingTaskType.POSITIVE_NEGATIVE,
}


class Skip(Exception):
    """A group that cannot be represented; the test is imported without it."""


def slug(section: str, path: Path) -> str:
    return f"ix-{section[0]}-{path.parent.parent.name}-{path.parent.name}"[:120]


def clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def gap_prompt(item: dict, context: str = "") -> str:
    prompt = " ".join(x for x in (clean(item.get("prefix")), BLANK, clean(item.get("suffix"))) if x)
    return f"{context} — {prompt}" if context else prompt


def answers_by_number(raw: dict) -> dict[int, list[str]]:
    """{"18-19-20": "CDE"} -> 18, 19 and 20 each accept C, D or E (order is free)."""
    out: dict[int, list[str]] = {}
    for key, value in (raw or {}).items():
        numbers = [int(n) for n in str(key).split("-") if n.strip().isdigit()]
        if len(numbers) > 1 and isinstance(value, str) and len(value) == len(numbers):
            values = list(value)
        else:
            values = value if isinstance(value, list) else [value]
        for n in numbers:
            out[n] = [clean(v) for v in values if clean(v)]
    return out


def instruction(group: dict, skill: str) -> str:
    instr = clean(group.get("instruction")).replace("**", "")
    kind = group["questionType"]
    if kind in VERB and LIMIT_RE.match(instr):
        limit = re.sub(r"^(write|choose)\s+", "", instr, flags=re.I)
        limit = re.sub(r"\s+for each answer\.?$", "", limit, flags=re.I)
        tail = (
            f"Choose {limit} from the passage for each answer."
            if skill == Skill.READING
            else f"Write {limit} for each answer."
        )
        return f"{VERB[kind]} {tail}"
    if kind == "TRUE_FALSE_NOT_GIVEN" and not instr:
        return (
            "Do the following statements agree with the information given in the passage? "
            "Choose TRUE, FALSE or NOT GIVEN."
        )
    if kind == "YES_NO_NOT_GIVEN" and not instr:
        return (
            "Do the following statements agree with the claims of the writer? "
            "Choose YES, NO or NOT GIVEN."
        )
    return instr or VERB.get(kind, "")


def summary_prompts(text: str) -> list[tuple[int, str]]:
    """One prompt per [N] gap: the sentence around it, other gaps shown as (M)."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", clean(text)):
        for n in re.findall(r"\[(\d+)\]", sentence):
            prompt = re.sub(
                r"\[(\d+)\]",
                lambda m, n=n: BLANK if m.group(1) == n else f"({m.group(1)})",
                sentence,
            )
            out.append((int(n), prompt))
    return out


def section_items(content: dict) -> list[tuple[int, str]]:
    out = []
    for sec in content.get("sections") or []:
        title = clean(sec.get("title"))
        for item in sec.get("items") or []:
            if item.get("questionNumber") is not None:
                out.append((int(item["questionNumber"]), gap_prompt(item, title)))
    return out


def table_items(content: dict) -> list[tuple[int, str]]:
    headers = [
        clean(h if isinstance(h, str) else h.get("text")) for h in content.get("headers") or []
    ]
    out = []
    for row in content.get("rows") or []:
        first = row[0] if row else {}
        row_label = (
            clean(first.get("text")) if first.get("type") in ("STATIC", "ROW_HEADER") else ""
        )
        for col, cell in enumerate(row):
            header = headers[col] if col < len(headers) else ""
            context = " / ".join(x for x in (row_label, header) if x)
            cells = cell.get("items", []) if cell.get("type") == "CELL_GROUP" else [cell]
            for item in cells:
                if item.get("questionNumber") is not None:
                    out.append((int(item["questionNumber"]), gap_prompt(item, context)))
    return out


def question_items(content: dict) -> list[tuple[int, str]]:
    """`questions[]` entries carry either a statement (`text`) or a gap (`prefix`/`suffix`)."""
    return [
        (int(x["questionNumber"]), clean(x.get("text")) or gap_prompt(x))
        for x in content.get("questions") or []
        if x.get("questionNumber") is not None
    ]


def options(items, label_key="id") -> list[tuple[str, str]]:
    return [(clean(o.get(label_key)), clean(o.get("text"))) for o in items or []]


def convert_group(group: dict, skill: str) -> dict:
    """Source group -> {type, heading, instructions, pool, questions[{number, prompt, options}]}."""
    kind, c = group["questionType"], group.get("content") or {}
    spec = {
        "type": None,
        "heading": clean(c.get("title") if kind != "MULTIPLE_CHOICE_MANY" else ""),
        "instructions": instruction(group, skill),
        "pool": None,
        "questions": [],
    }
    q = spec["questions"]

    if kind in GAP_TYPES:
        spec["type"] = QuestionType.GAP
        if kind == "TABLE_COMPLETION":
            pairs = table_items(c)
        elif kind == "SUMMARY_COMPLETION":
            pairs = summary_prompts(c.get("summaryText"))
        else:
            pairs = section_items(c)
            if kind == "FLOW_CHART_COMPLETION" and c.get("questionsTitle"):
                spec["heading"] = clean(c["questionsTitle"])
        q += [{"number": n, "prompt": p} for n, p in pairs]
    elif kind == "TRUE_FALSE_NOT_GIVEN":
        spec["type"] = QuestionType.TFNG
        q += [
            {"number": int(x["questionNumber"]), "prompt": clean(x["text"])}
            for x in c.get("questions") or []
        ]
    elif kind == "YES_NO_NOT_GIVEN":
        spec["type"] = QuestionType.MCQ
        yn = [("", "YES"), ("", "NO"), ("", "NOT GIVEN")]
        q += [
            {"number": int(x["questionNumber"]), "prompt": clean(x["text"]), "options": yn}
            for x in c.get("questions") or []
        ]
    elif kind == "MULTIPLE_CHOICE":
        spec["type"] = QuestionType.MCQ
        q += [
            {
                "number": int(x["questionNumber"]),
                "prompt": clean(x["text"]),
                "options": options(x.get("options")),
            }
            for x in c.get("questions") or []
        ]
    elif kind == "MULTIPLE_CHOICE_MANY":
        # "Choose TWO" over questions 21-22: each number is an MCQ over the same
        # options and accepts any of the correct letters.
        spec["type"] = QuestionType.MCQ
        for x in c.get("questions") or []:
            numbers = x.get("questionNumbers") or []
            for i, n in enumerate(numbers, start=1):
                suffix = f" (answer {i} of {len(numbers)})" if len(numbers) > 1 else ""
                q.append(
                    {
                        "number": int(n),
                        "prompt": clean(x["text"]) + suffix,
                        "options": options(x.get("options")),
                    }
                )
    else:
        spec["type"] = QuestionType.MATCHING
        if kind == "MATCHING_INFORMATION":
            spec["pool"] = [(lbl, f"Paragraph {lbl}") for lbl in c.get("labels") or []]
        elif kind == "MATCHING_HEADINGS":
            spec["pool"] = options(c.get("headings"))
            spec["heading"] = spec["heading"] or "List of Headings"
        elif kind == "MATCHING_FEATURES":
            spec["pool"] = options(c.get("features"))
            spec["heading"] = spec["heading"] or clean(
                c.get("featuresTitle") or c.get("featureTitle")
            )
        elif kind == "DIAGRAM_LABELING":
            # "A music room" -> (A, music room)
            spec["pool"] = [
                tuple(label.split(" ", 1)) if " " in label else (label, label)
                for label in map(clean, c.get("labels") or [])
            ]
        elif kind in (
            "MATCHING_NAMES",
            "MATCHING_SENTENCE_ENDINGS",
            "SUMMARY_COMPLETION_OPTIONS",
            "FLOW_CHART_MATCHING",
        ):
            spec["pool"] = options(c.get("options"))
            spec["heading"] = spec["heading"] or clean(
                c.get("optionsTitle") or c.get("questionsTitle")
            )
        else:
            raise Skip(f"unknown question type {kind}")

        if kind == "SUMMARY_COMPLETION_OPTIONS":
            pairs = summary_prompts(c.get("summaryText"))
        elif kind == "FLOW_CHART_MATCHING":
            pairs = section_items(c) or question_items(c)
        elif kind == "DIAGRAM_LABELING":
            pairs = [
                (
                    int(x["questionNumber"]),
                    clean(x.get("text")) or f"Location {x['questionNumber']} on the plan",
                )
                for x in c.get("itemsToLabel") or []
            ]
        else:
            pairs = question_items(c)
        q += [{"number": n, "prompt": p} for n, p in pairs]

    if not q:
        raise Skip(f"{kind} has no questions")
    return spec


def pick_option(opts: dict, value: str):
    """Answer value -> Option, by label ("A", "iv") first, then by text."""

    def find(v):
        for (label, _text), option in opts.items():
            if label.lower() == v:
                return option
        for (label, text), option in opts.items():
            if text.lower() == v or f"{label} {text}".lower() == v:
                return option
        return None

    v = value.strip().lower()
    # Short forms only as a fallback: "F" is also a matching letter.
    return find(v) or find({"ng": "not given", "y": "yes", "n": "no"}.get(v, v))


def build_group(
    section: Section, order: int, spec: dict, answers: dict, explanations: dict, problems: list
) -> int:
    kind = spec["type"]
    group = QuestionGroup.objects.create(
        section=section,
        order=order,
        type=kind,
        heading=spec["heading"][:2000],
        instructions=spec["instructions"],
        options_scope=OptionsScope.SHARED
        if kind == QuestionType.MATCHING
        else OptionsScope.PER_QUESTION,
        match_mode=MatchMode.NORMALIZED if kind == QuestionType.GAP else MatchMode.EXACT,
    )
    pool = {}
    if kind == QuestionType.MATCHING:
        for i, (label, text) in enumerate(spec["pool"] or [], start=1):
            pool[(label, text)] = Option.objects.create(
                group=group, question=None, order=i, label=label[:8], text=text or label
            )

    made = 0
    for position, raw in enumerate(spec["questions"], start=1):
        number = raw["number"]
        if Question.objects.filter(test=section.test, number=number).exists():
            problems.append(f"q{number}: duplicate number, skipped")
            continue
        question = Question.objects.create(
            group=group,
            test=section.test,
            order=position,
            number=number,
            prompt=raw["prompt"] or f"Question {number}",
            explanation=explanations.get(number, ""),
        )
        made += 1
        values = answers.get(number) or []
        if not values:
            problems.append(f"q{number}: no answer key")
            continue
        if kind == QuestionType.GAP:
            for i, value in enumerate(values):
                AnswerKey.objects.create(question=question, value=value, order=i)
        elif kind == QuestionType.TFNG:
            value = {"T": "TRUE", "F": "FALSE", "NG": "NOT GIVEN"}.get(
                values[0].upper(), values[0].upper()
            )
            AnswerKey.objects.create(question=question, value=value)
        else:
            opts = pool
            if kind == QuestionType.MCQ:
                opts = {}
                for i, (label, text) in enumerate(raw["options"], start=1):
                    opts[(label, text)] = Option.objects.create(
                        group=group, question=question, order=i, label=label[:8], text=text or label
                    )
            for i, value in enumerate(values):
                option = pick_option(opts, value)
                if option is None:
                    problems.append(f"q{number}: answer {value!r} is not an option")
                    continue
                AnswerKey.objects.create(
                    question=question, option=option, value=option.text, order=i
                )
    return made


def explanations_for(raw: dict) -> dict[int, str]:
    out = {}
    for sol in raw.get("solutions") or []:
        for number, e in (sol.get("explanations") or {}).items():
            if isinstance(e, str):
                e = {"explanation": e}
            text = clean(e.get("explanation"))
            if e.get("excerpt"):
                text += f"\n\n“{clean(e['excerpt'])}”"
            if str(number).isdigit():
                out[int(number)] = text
    return out


def timestamp_ms(ts: str):
    try:
        parts = [int(x) for x in str(ts).split(":")]
    except ValueError:
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds * 1000


def audio_asset(path: Path) -> AudioAsset:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    existing = AudioAsset.objects.filter(checksum_sha256=checksum).first()
    if existing:
        return existing
    info = mutagen.File(path)
    asset = AudioAsset(
        original_filename=f"{path.parent.parent.name}-{path.parent.name}.mp3",
        content_type="audio/mpeg",
        size_bytes=path.stat().st_size,
        duration_ms=int(info.info.length * 1000) if info else 0,
        checksum_sha256=checksum,
    )
    with open(path, "rb") as fh:
        asset.file.save(f"{checksum}.mp3", File(fh), save=False)
    asset.save()
    return asset


@transaction.atomic
def import_test(path: Path, skill: str, with_audio: bool) -> tuple[Test, list[str]]:
    raw = json.loads(path.read_text())
    problems: list[str] = []
    test, _ = Test.objects.update_or_create(
        slug=slug(skill, path),
        defaults={
            "skill": skill,
            "title": test_title(raw, path),
            "description": clean(raw.get("source")),
            "time_limit_minutes": 60 if skill == Skill.READING else 30,
            "status": PublishStatus.PUBLISHED,
        },
    )
    test.sections.all().delete()

    answers = answers_by_number(raw.get("answers"))
    explanations = explanations_for(raw)
    asset = None
    if skill == Skill.LISTENING and with_audio and (path.parent / "audio.mp3").exists():
        asset = audio_asset(path.parent / "audio.mp3")

    parts = sorted(raw.get("parts") or [], key=lambda p: p.get("partNumber", 0))
    starts = [
        timestamp_ms(
            ((p.get("transcript") or {}).get("dialogue") or {})
            .get("lines", [{}])[0]
            .get("timestamp")
        )
        for p in parts
    ]

    for index, part in enumerate(parts):
        n = part.get("partNumber") or index + 1
        groups = part.get("questionGroups") or []
        numbers = [g.get("fromNumber") for g in groups] + [g.get("toNumber") for g in groups]
        numbers = [x for x in numbers if x is not None]
        span = f"Questions {min(numbers)}\u2013{max(numbers)}" if numbers else ""

        if skill == Skill.READING:
            passage = part.get("passage") or {}
            section = Section.objects.create(
                test=test,
                order=index + 1,
                title=clean(passage.get("title")) or f"Reading Passage {n}",
                instructions=span,
            )
            blocks = []
            if passage.get("subtitle"):
                blocks.append((BlockKind.PARAGRAPH, "", clean(passage["subtitle"])))
            for par in passage.get("content") or []:
                if par.get("title"):
                    blocks.append((BlockKind.HEADING, "", clean(par["title"])))
                if clean(par.get("text")):
                    blocks.append(
                        (BlockKind.PARAGRAPH, clean(par.get("label")), str(par["text"]).strip())
                    )
            if passage.get("footer"):
                blocks.append((BlockKind.PARAGRAPH, "", clean(passage["footer"])))
        else:
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            section = Section.objects.create(
                test=test,
                order=index + 1,
                title=f"Part {n}",
                instructions=span,
                audio=asset,
                audio_start_ms=starts[index] if asset else None,
                audio_end_ms=next_start
                if asset and next_start and starts[index] is not None and next_start > starts[index]
                else None,
                transcript_visibility=TranscriptVisibility.AFTER_SUBMIT,
            )
            lines = ((part.get("transcript") or {}).get("dialogue") or {}).get("lines") or []
            blocks = [
                (BlockKind.PARAGRAPH, clean(line.get("speaker"))[:60], clean(line.get("text")))
                for line in lines
                if clean(line.get("text"))
            ]

        Block.objects.bulk_create(
            [
                Block(section=section, order=i, kind=k, label=label[:60], text=text)
                for i, (k, label, text) in enumerate(blocks, start=1)
            ]
        )

        order = 0
        for group in groups:
            try:
                spec = convert_group(group, skill)
            except (Skip, KeyError, TypeError, ValueError) as exc:
                where = f"{group.get('fromNumber')}-{group.get('toNumber')}"
                problems.append(f"{group.get('questionType')} {where}: {exc}")
                continue
            order += 1
            build_group(section, order, spec, answers, explanations, problems)
    return test, problems


def test_title(raw: dict, path: Path) -> str:
    pack = raw.get("packName") or path.parent.parent.name
    return f"{pack} · {raw.get('title') or path.parent.name}"[:200]


def speaking_title(raw: dict, path: Path) -> str:
    """The Part 3 theme names the whole test best; Part 2's cue card is a full sentence."""
    for n in (3, 2, 1):
        for part in raw.get("parts") or []:
            if part.get("partNumber") == n:
                for group in part.get("questionGroups") or []:
                    topic = clean((group.get("content") or {}).get("topic"))
                    if topic:
                        return topic[:200]
    return clean(raw.get("title")) or path.parent.name


def natural_key(text: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def pack_title(raw: dict, path: Path) -> str:
    """Writing packs are named by date ("01_06-08_06"); their source reads better."""
    name = clean(raw.get("packName")) or path.parent.parent.name
    if not re.search(r"[A-Za-z]", name) and clean(raw.get("source")):
        return clean(raw["source"])[:200]
    return name[:200]


def ensure_pack(section: str, path: Path, raw: dict, order: int) -> Pack:
    pack, _ = Pack.objects.update_or_create(
        slug=f"ix-{section[0]}-{path.parent.parent.name}"[:120],
        defaults={"skill": section, "title": pack_title(raw, path), "order": order},
    )
    return pack


def place(item, pack: Pack, position: int, label: str) -> None:
    item.pack, item.pack_position, item.pack_label = pack, position, label[:60]
    item.save(update_fields=["pack", "pack_position", "pack_label"])


def task_type(number: int, categories: list[str], question: str) -> str:
    if number == 1:
        if re.search(r"\bletter\b", question, re.I):
            return WritingTaskType.TASK1_LETTER
        return next(
            (TASK1_TYPES[c] for c in categories if c in TASK1_TYPES), WritingTaskType.TASK1_CHART
        )
    return next(
        (TASK2_TYPES[c] for c in categories if c in TASK2_TYPES), WritingTaskType.AGREE_DISAGREE
    )


@transaction.atomic
def import_writing(path: Path, with_images: bool = True) -> list[WritingTask]:
    raw = json.loads(path.read_text())
    categories = raw.get("categories") or []
    tasks = []
    for part in raw.get("parts") or []:
        group = part.get("task") or (part.get("questionGroups") or [{}])[0]
        c = group.get("content") or {}
        number = 1 if group.get("questionType") == "WRITING_TASK1" else 2
        question = str(c.get("question") or group.get("instruction") or "").strip()
        follow = str(c.get("task") or "").strip()
        prompt = question if not follow or follow in question else f"{question}\n\n{follow}"
        task, _ = WritingTask.objects.update_or_create(
            slug=f"{slug('writing', path)}-t{number}"[:120],
            defaults={
                "task_number": number,
                "type": task_type(number, categories, question),
                "prompt": prompt,
                "suggested_time_minutes": 20 if number == 1 else 40,
                "target_words": 150 if number == 1 else 250,
                "status": PublishStatus.PUBLISHED,
            },
        )
        image = c.get("imgFile") or c.get("imageFile")
        if with_images and image and (path.parent / image).exists() and not task.image:
            with open(path.parent / image, "rb") as fh:
                task.image.save(f"ix-{path.parent.parent.name}-{image}", File(fh), save=True)
        tasks.append(task)
    return tasks


@transaction.atomic
def import_speaking(path: Path, order: int) -> SpeakingTopic:
    raw = json.loads(path.read_text())
    groups = {
        n: [
            g
            for p in raw.get("parts") or []
            if p.get("partNumber") == n
            for g in p.get("questionGroups") or []
        ]
        for n in (1, 2, 3)
    }

    def texts(group):
        return [
            clean(q if isinstance(q, str) else q.get("text"))
            for q in (group.get("content") or {}).get("questions") or []
        ]

    def topic_of(n):
        return clean(((groups[n] or [{}])[0].get("content") or {}).get("topic"))

    title = speaking_title(raw, path)
    topic, _ = SpeakingTopic.objects.update_or_create(
        slug=slug("speaking", path),
        defaults={
            "title": title,
            "order": order,
            "status": PublishStatus.PUBLISHED,
        },
    )
    topic.items.all().delete()
    if groups[2]:
        SpeakingCueCard.objects.update_or_create(
            topic=topic, defaults={"title": topic_of(2)[:255] or title[:255]}
        )
    rows = [
        (1, SpeakingItemKind.QUESTION, [t for g in groups[1] for t in texts(g)]),
        (2, SpeakingItemKind.BULLET, [t for g in groups[2] for t in texts(g)]),
        (3, SpeakingItemKind.QUESTION, [t for g in groups[3] for t in texts(g)]),
    ]
    SpeakingItem.objects.bulk_create(
        [
            SpeakingItem(topic=topic, part=part, kind=kind, order=i, text=text)
            for part, kind, items in rows
            for i, text in enumerate(items, start=1)
            if text
        ]
    )
    return topic


class Command(BaseCommand):
    help = "Import the ieltsx.com scrape (listening, reading, writing, speaking). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data", required=True, help="Directory holding ieltsx/, ieltsx-reading/, ..."
        )
        parser.add_argument(
            "--only", choices=list(DIRS), action="append", help="Import only these sections."
        )
        parser.add_argument(
            "--limit", type=int, help="At most this many tests per section (for a trial run)."
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Write no files into MEDIA_ROOT (no audio, no images).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Roll everything back at the end."
        )
        parser.add_argument(
            "--packs-only",
            action="store_true",
            help="Only (re)assign packs and titles to already imported content; rebuild nothing.",
        )

    def handle(self, *args, **opts):
        root = Path(opts["data"])
        if not root.is_dir():
            raise CommandError(f"{root} is not a directory")
        sections = opts["only"] or list(DIRS)
        try:
            with transaction.atomic():
                self._run(root, sections, opts)
                if opts["dry_run"]:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING("dry run: rolled back"))

    def _run(self, root, sections, opts):
        for section in sections:
            base = root / DIRS[section]
            files = sorted(
                base.glob("*/*/test.json"),
                key=lambda p: (natural_key(p.parent.parent.name), natural_key(p.parent.name)),
            )[: opts["limit"] or None]
            if not files:
                self.stdout.write(f"{section}: nothing under {base}")
                continue
            pack_dirs = sorted({p.parent.parent.name for p in files}, key=natural_key)
            done = issues = 0
            positions: dict[str, int] = {}
            for i, path in enumerate(files, start=1):
                raw = json.loads(path.read_text())
                pack = ensure_pack(
                    section, path, raw, order=pack_dirs.index(path.parent.parent.name)
                )
                position = positions[pack.slug] = positions.get(pack.slug, 0) + 1
                label = clean(raw.get("title")) or path.parent.name
                where = f"{path.parent.parent.name}/{path.parent.name}"

                if section in (Skill.READING, Skill.LISTENING):
                    if opts["packs_only"]:
                        test = Test.objects.filter(slug=slug(section, path)).first()
                    else:
                        test, problems = import_test(path, section, with_audio=not opts["no_media"])
                        issues += len(problems)
                        for problem in problems:
                            self.stdout.write(self.style.WARNING(f"  {section} {where} {problem}"))
                    if test:
                        place(test, pack, position, label)
                elif section == "writing":
                    if opts["packs_only"]:
                        tasks = list(
                            WritingTask.objects.filter(slug__startswith=f"{slug(section, path)}-t")
                        )
                    else:
                        tasks = import_writing(path, with_images=not opts["no_media"])
                    for task in tasks:
                        place(
                            task,
                            pack,
                            position * 10 + task.task_number,
                            f"{label} · Task {task.task_number}",
                        )
                else:
                    if opts["packs_only"]:
                        topic = SpeakingTopic.objects.filter(slug=slug(section, path)).first()
                        if topic:
                            topic.title = speaking_title(raw, path)
                            topic.save(update_fields=["title"])
                    else:
                        topic = import_speaking(path, order=100 + i)
                    if topic:
                        place(topic, pack, position, label)
                done += 1
                if i % 25 == 0:
                    self.stdout.write(f"  {section}: {i}/{len(files)}")
            verb = "placed in packs" if opts["packs_only"] else "imported"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{section}: {done} {verb}, {len(pack_dirs)} packs, {issues} warnings"
                )
            )


class _DryRun(Exception):
    pass
