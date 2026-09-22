"""Editors for vocabulary, writing and speaking.

Same pattern as the test editor: one ModelForm per model, one fragment per
change, and publish as a separate step. These trees are shallow enough that the
whole card re-renders on every change -- there is nothing to gain from patching
a single row, and re-rendering cannot drift.
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.common.caching import bump_content_version
from apps.common.models import PublishStatus
from apps.speaking.models import (
    SpeakingCueCard,
    SpeakingItem,
    SpeakingItemKind,
    SpeakingTopic,
)
from apps.vocabulary.models import PartOfSpeech, VocabularySection, VocabularyWord
from apps.vocabulary.publishing import publish_section
from apps.writing.models import WritingModelAnswer, WritingTask

from .access import staff_required
from .editor import saved
from .forms import (
    BulkWordForm,
    SpeakingCueCardForm,
    SpeakingItemForm,
    SpeakingTopicForm,
    VocabularySectionForm,
    VocabularyWordForm,
    WritingModelAnswerForm,
    WritingTaskForm,
    parse_words,
)
from .nav import page_context

# --- vocabulary ----------------------------------------------------------------


def _word_list(request, section, rejected=None):
    return render(
        request,
        "dashboard/partials/word_list.html",
        {
            "section": section,
            "words": section.words.order_by("order"),
            "rejected": rejected or [],
            "pos_choices": PartOfSpeech.choices,
        },
    )


@staff_required
def vocabulary_create(request):
    if request.method == "POST":
        form = VocabularySectionForm(request.POST)
        if form.is_valid():
            section = form.save()
            return redirect("dashboard:vocabulary-edit", slug=section.slug)
    else:
        form = VocabularySectionForm(initial={"status": PublishStatus.DRAFT})
    return render(
        request,
        "dashboard/simple_form.html",
        page_context(
            request, form=form, heading="New vocabulary section",
            cancel_url="dashboard:vocabulary-list",
        ),
    )


@staff_required
def vocabulary_edit(request, slug):
    section = get_object_or_404(VocabularySection, slug=slug)
    return render(
        request,
        "dashboard/vocabulary_edit.html",
        page_context(
            request,
            section=section,
            form=VocabularySectionForm(instance=section),
            bulk_form=BulkWordForm(),
            words=section.words.order_by("order"),
            pos_choices=PartOfSpeech.choices,
        ),
    )


@staff_required
@require_POST
def vocabulary_meta_save(request, slug):
    section = get_object_or_404(VocabularySection, slug=slug)
    form = VocabularySectionForm(request.POST, instance=section)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def vocabulary_publish(request, slug):
    section = get_object_or_404(VocabularySection, slug=slug)
    if not section.words.exists():
        messages.error(request, "Add at least one word before publishing.")
        return redirect("dashboard:vocabulary-edit", slug=slug)

    publish_section(section)
    bump_content_version()
    messages.success(request, f"Published {section.title}.")
    return redirect("dashboard:vocabulary-edit", slug=slug)


@staff_required
@require_POST
def word_create(request, slug):
    section = get_object_or_404(VocabularySection, slug=slug)
    VocabularyWord.objects.create(
        section=section,
        headword=f"New word {section.words.count() + 1}",
        pos="noun",
        definition="",
        example="A **placeholder** example.",
        order=(section.words.aggregate(m=Max("order"))["m"] or 0) + 1,
    )
    return _word_list(request, section)


@staff_required
@require_http_methods(["POST", "DELETE"])
def word_detail(request, pk):
    word = get_object_or_404(VocabularyWord.objects.select_related("section"), pk=pk)
    section = word.section

    if request.method == "DELETE":
        word.delete()
        return _word_list(request, section)

    form = VocabularyWordForm(request.POST, instance=word)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    try:
        # clean() enforces exactly one **bold** span, which the frontend's
        # renderer depends on.
        form.instance.full_clean()
    except Exception as exc:
        return HttpResponse(str(exc), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def word_bulk_import(request, slug):
    section = get_object_or_404(VocabularySection, slug=slug)
    form = BulkWordForm(request.POST)
    if not form.is_valid():
        return HttpResponse("Nothing to import.", status=400)

    rows, rejected = parse_words(form.cleaned_data["text"])

    with transaction.atomic():
        if form.cleaned_data.get("replace"):
            section.words.all().delete()
        start = (section.words.aggregate(m=Max("order"))["m"] or 0) + 1
        for index, row in enumerate(rows):
            VocabularyWord.objects.update_or_create(
                section=section, headword=row["headword"],
                defaults={**row, "order": start + index},
            )

    # Rejected lines are reported rather than dropped: a silent partial import
    # is worse than none.
    return _word_list(request, section, rejected=rejected)


# --- writing -------------------------------------------------------------------


@staff_required
def writing_create(request):
    if request.method == "POST":
        form = WritingTaskForm(request.POST, request.FILES)
        if form.is_valid():
            task = form.save()
            return redirect("dashboard:writing-edit", slug=task.slug)
    else:
        form = WritingTaskForm(initial={"status": PublishStatus.DRAFT, "task_number": 2})
    return render(
        request,
        "dashboard/simple_form.html",
        page_context(
            request, form=form, heading="New writing task", cancel_url="dashboard:writing-list"
        ),
    )


@staff_required
def writing_edit(request, slug):
    task = get_object_or_404(WritingTask.objects.prefetch_related("model_answers"), slug=slug)
    return render(
        request,
        "dashboard/writing_edit.html",
        page_context(
            request,
            task=task,
            form=WritingTaskForm(instance=task),
            answers=[
                (answer, WritingModelAnswerForm(instance=answer, prefix=f"a{answer.pk}"))
                for answer in task.model_answers.order_by("order")
            ],
        ),
    )


@staff_required
@require_POST
def writing_save(request, slug):
    task = get_object_or_404(WritingTask, slug=slug)
    form = WritingTaskForm(request.POST, request.FILES, instance=task)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def writing_answer_create(request, slug):
    task = get_object_or_404(WritingTask, slug=slug)
    WritingModelAnswer.objects.create(
        task=task,
        body="",
        order=(task.model_answers.aggregate(m=Max("order"))["m"] or 0) + 1,
    )
    return redirect("dashboard:writing-edit", slug=slug)


@staff_required
@require_http_methods(["POST", "DELETE"])
def writing_answer_detail(request, pk):
    answer = get_object_or_404(WritingModelAnswer.objects.select_related("task"), pk=pk)
    if request.method == "DELETE":
        slug = answer.task.slug
        answer.delete()
        return redirect("dashboard:writing-edit", slug=slug)

    form = WritingModelAnswerForm(request.POST, instance=answer, prefix=f"a{answer.pk}")
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    # Saved verbatim: the blank lines between paragraphs are what the frontend
    # splits on, so nothing here may strip or normalise whitespace.
    form.save()
    return saved()


# --- speaking ------------------------------------------------------------------

ITEM_SLOTS = [
    (1, SpeakingItemKind.QUESTION, "Part 1 questions"),
    (2, SpeakingItemKind.BULLET, "Cue card bullets"),
    (3, SpeakingItemKind.QUESTION, "Part 3 questions"),
    (3, SpeakingItemKind.PHRASE, "Useful phrases"),
]


def _speaking_slots(topic):
    items = list(topic.items.order_by("part", "kind", "order"))
    return [
        {
            "part": part,
            "kind": kind,
            "label": label,
            "items": [i for i in items if i.part == part and i.kind == kind],
        }
        for part, kind, label in ITEM_SLOTS
    ]


@staff_required
def speaking_create(request):
    if request.method == "POST":
        form = SpeakingTopicForm(request.POST)
        if form.is_valid():
            topic = form.save()
            SpeakingCueCard.objects.create(topic=topic, title=f"Describe {topic.title.lower()}.")
            return redirect("dashboard:speaking-edit", slug=topic.slug)
    else:
        form = SpeakingTopicForm(initial={"status": PublishStatus.DRAFT})
    return render(
        request,
        "dashboard/simple_form.html",
        page_context(
            request, form=form, heading="New speaking topic", cancel_url="dashboard:speaking-list"
        ),
    )


@staff_required
def speaking_edit(request, slug):
    topic = get_object_or_404(SpeakingTopic.objects.prefetch_related("items"), slug=slug)
    cue, _ = SpeakingCueCard.objects.get_or_create(
        topic=topic, defaults={"title": f"Describe {topic.title.lower()}."}
    )
    return render(
        request,
        "dashboard/speaking_edit.html",
        page_context(
            request,
            topic=topic,
            form=SpeakingTopicForm(instance=topic),
            cue_form=SpeakingCueCardForm(instance=cue),
            slots=_speaking_slots(topic),
        ),
    )


@staff_required
@require_POST
def speaking_save(request, slug):
    topic = get_object_or_404(SpeakingTopic, slug=slug)
    form = SpeakingTopicForm(request.POST, instance=topic)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def speaking_cue_save(request, slug):
    topic = get_object_or_404(SpeakingTopic, slug=slug)
    cue, _ = SpeakingCueCard.objects.get_or_create(topic=topic, defaults={"title": topic.title})
    form = SpeakingCueCardForm(request.POST, instance=cue)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


def _slot_fragment(request, topic, part, kind):
    return render(
        request,
        "dashboard/partials/speaking_slot.html",
        {
            "topic": topic,
            "slot": next(
                s for s in _speaking_slots(topic) if s["part"] == part and s["kind"] == kind
            ),
        },
    )


@staff_required
@require_POST
def speaking_item_create(request, slug, part, kind):
    topic = get_object_or_404(SpeakingTopic, slug=slug)
    if kind not in SpeakingItemKind.values or int(part) not in (1, 2, 3):
        return HttpResponse("Unknown slot.", status=404)

    existing = topic.items.filter(part=part, kind=kind)
    SpeakingItem.objects.create(
        topic=topic,
        part=part,
        kind=kind,
        order=(existing.aggregate(m=Max("order"))["m"] or 0) + 1,
        text="",
    )
    return _slot_fragment(request, topic, int(part), kind)


@staff_required
@require_http_methods(["POST", "DELETE"])
def speaking_item_detail(request, pk):
    item = get_object_or_404(SpeakingItem.objects.select_related("topic"), pk=pk)

    if request.method == "DELETE":
        topic, part, kind = item.topic, item.part, item.kind
        item.delete()
        return _slot_fragment(request, topic, part, kind)

    form = SpeakingItemForm(request.POST, instance=item)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()
