"""Build and store the public API payload for a test.

Written as plain builders rather than nested DRF serializers: the shape is
fixed, conditional in two places (passage vs transcript, transcript
visibility), and produced once per publish rather than per request.

Correct answers are absent here by construction. AnswerKey is never traversed,
so leaking an answer through the public API would take a deliberate change
rather than a forgotten exclusion.
"""

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from apps.common.models import PublishStatus
from apps.common.payloads import payload_etag

from .enums import Skill, TranscriptVisibility
from .models import Option, Question, QuestionGroup, Section, Test


def published_queryset():
    """Tests with their whole tree prefetched, for publishing."""
    return Test.objects.prefetch_related(
        Prefetch(
            "sections",
            queryset=Section.objects.order_by("order").select_related("audio"),
        ),
        "sections__blocks",
        Prefetch(
            "sections__groups",
            queryset=QuestionGroup.objects.order_by("order"),
        ),
        Prefetch(
            "sections__groups__questions",
            queryset=Question.objects.order_by("number"),
        ),
        Prefetch(
            "sections__groups__questions__options",
            queryset=Option.objects.order_by("order"),
        ),
        Prefetch(
            "sections__groups__options",
            queryset=Option.objects.filter(question__isnull=True).order_by("order"),
        ),
    )


def build_option(option) -> dict:
    return {"id": option.id, "label": option.label, "text": option.text}


def build_question(question, group) -> dict:
    data = {
        "id": question.id,
        "number": question.number,
        "type": group.type,
        "prompt": question.prompt,
    }
    if group.uses_options and not group.has_shared_pool:
        data["options"] = [build_option(o) for o in question.options.all()]
    return data


def build_group(group) -> dict:
    data = {
        "id": group.id,
        "order": group.order,
        "type": group.type,
        "instructions": group.instructions,
        "questions": [build_question(q, group) for q in group.questions.all()],
    }
    if group.has_shared_pool:
        data["options"] = [build_option(o) for o in group.options.all()]
    return data


def build_audio(section) -> dict | None:
    if not section.audio_id:
        return None
    return {
        "url": section.audio.file.url,
        "durationMs": section.audio.duration_ms,
        "startMs": section.audio_start_ms,
        "endMs": section.audio_end_ms,
        "playbackPolicy": section.playback_policy,
    }


def build_section(section, skill) -> dict:
    data = {
        "id": section.id,
        "order": section.order,
        "title": section.title,
        "instructions": section.instructions,
        "audio": build_audio(section),
        "groups": [build_group(g) for g in section.groups.all()],
    }

    # Showing the transcript while the audio plays turns a listening test into
    # a reading test, so withhold it server-side rather than hiding it in the UI.
    hide_blocks = (
        skill == Skill.LISTENING
        and section.transcript_visibility != TranscriptVisibility.DURING_TEST
    )
    label_key = "label" if skill == Skill.READING else "speaker"
    data["blocks"] = (
        []
        if hide_blocks
        else [{label_key: b.label, "text": b.text} for b in section.blocks.all()]
    )
    data["blocksAvailableAfterSubmit"] = (
        hide_blocks and section.transcript_visibility == TranscriptVisibility.AFTER_SUBMIT
    )
    return data


def build_test_payload(test) -> dict:
    sections = list(test.sections.all())
    question_count = sum(len(g.questions.all()) for s in sections for g in s.groups.all())
    return {
        "id": test.slug,
        "skill": test.skill,
        "title": test.title,
        "description": test.description,
        "difficulty": test.difficulty,
        "timeLimitMinutes": test.time_limit_minutes,
        "questionCount": question_count,
        "sections": [build_section(s, test.skill) for s in sections],
    }


@transaction.atomic
def publish_test(test) -> Test:
    """Materialise the public payload and mark the test published."""
    hydrated = published_queryset().get(pk=test.pk)
    payload = build_test_payload(hydrated)

    test.published_payload = payload
    test.payload_etag = payload_etag(payload)
    test.published_at = timezone.now()
    test.status = PublishStatus.PUBLISHED
    test.save(
        update_fields=["published_payload", "payload_etag", "published_at", "status", "updated_at"]
    )
    return test
