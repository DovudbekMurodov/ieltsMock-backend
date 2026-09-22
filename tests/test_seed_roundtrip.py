"""Proof that seeding is lossless.

Rebuilds the frontend's exact data shape out of the database and diffs it
against the committed JSON. This test, not a manual read-through, is the
guarantee that the migration preserved every paragraph break, curly quote and
bold marker.
"""

import json

import pytest
from django.core.management import call_command

from apps.content.enums import QuestionType, Skill
from apps.content.models import Test
from apps.content.seeding import TYPE_OVERRIDES
from apps.speaking.models import SpeakingItemKind, SpeakingTopic
from apps.vocabulary.models import VocabularySection
from apps.writing.models import WritingTask, WritingTaskType

SEED_DIR = pytest.importorskip("django.conf").settings.BASE_DIR / "seed" / "data"


def load(name):
    return json.loads((SEED_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed_content", verbosity=0)
        yield


def rebuild_question(question):
    group = question.group
    out = {"id": question.number, "type": group.type, "prompt": question.prompt}
    keys = list(question.answer_keys.order_by("order"))

    if group.type == QuestionType.GAP:
        out["acceptedAnswers"] = [k.value for k in keys]
        return out

    if group.type != QuestionType.TFNG:
        pool = group.options if group.has_shared_pool else question.options
        out["options"] = [o.text for o in pool.order_by("order")]

    out["answer"] = keys[0].value
    return out


def rebuild_test(test):
    section = test.sections.get()
    body_key, blocks_key, label_key = (
        ("passage", "paragraphs", "label")
        if test.skill == Skill.READING
        else ("transcript", "lines", "speaker")
    )
    return {
        "id": test.slug,
        "title": test.title,
        "timeLimitMinutes": test.time_limit_minutes,
        body_key: {
            "title": section.title,
            blocks_key: [
                {label_key: b.label, "text": b.text} for b in section.blocks.order_by("order")
            ],
        },
        "questions": [rebuild_question(q) for q in test.questions.order_by("number")],
    }


@pytest.mark.parametrize(
    "dataset,skill", [("reading", Skill.READING), ("listening", Skill.LISTENING)]
)
def test_tests_round_trip(seeded, dataset, skill):
    for source in load(dataset):
        rebuilt = rebuild_test(Test.objects.get(slug=source["id"]))

        # One question is deliberately retyped during seeding; compare it on
        # every field except the type we corrected.
        for question in source["questions"]:
            override = TYPE_OVERRIDES.get((source["id"], question["id"]))
            if override:
                question["type"] = override.value

        assert rebuilt == source, f"{dataset}/{source['id']} did not round-trip"


def test_only_the_documented_question_was_retyped(seeded):
    assert TYPE_OVERRIDES == {("museum-tour", 5): QuestionType.MCQ}


def test_writing_round_trips_including_paragraph_breaks(seeded):
    labels = dict(WritingTaskType.choices)
    for source in load("writing"):
        task = WritingTask.objects.get(slug=source["id"])
        answer = task.model_answers.get()

        assert labels[task.type] == source["type"]
        assert task.prompt == source["prompt"]
        assert task.suggested_time_minutes == source["suggestedTimeMinutes"]
        assert task.target_words == source["targetWords"]
        # Byte-for-byte: the blank lines are what the frontend splits on.
        assert answer.body == source["modelAnswer"]
        assert len(answer.paragraphs) == len(source["modelAnswer"].split("\n\n"))


def test_vocabulary_round_trips_including_bold_markers(seeded):
    for source in load("vocabulary"):
        section = VocabularySection.objects.get(slug=source["id"])
        assert section.title == source["title"]

        rebuilt = [
            {"word": w.headword, "pos": w.pos, "definition": w.definition, "example": w.example}
            for w in section.words.order_by("order")
        ]
        assert rebuilt == source["words"]


def test_speaking_round_trips(seeded):
    for source in load("speaking"):
        topic = SpeakingTopic.objects.get(slug=source["id"])
        items = list(topic.items.order_by("part", "kind", "order"))

        def texts(part, kind, items=items):
            return [i.text for i in items if i.part == part and i.kind == kind]

        assert topic.title == source["topic"]
        assert texts(1, SpeakingItemKind.QUESTION) == source["part1"]
        assert texts(3, SpeakingItemKind.QUESTION) == source["part3"]
        assert texts(3, SpeakingItemKind.PHRASE) == source["phrases"]
        assert texts(2, SpeakingItemKind.BULLET) == source["part2"]["bullets"]
        assert topic.cue_card.title == source["part2"]["title"]
        assert topic.cue_card.prep_seconds == source["part2"]["prepSeconds"]
        assert topic.cue_card.speak_seconds == source["part2"]["speakSeconds"]
