"""The nested test editor.

Persist-on-interaction rather than nested formsets: the test is created as a
draft immediately, and every add, edit, delete and reorder is one small POST
that returns one rendered fragment. Each endpoint is a ModelForm over a single
model, so there is no prefix arithmetic and no management form.

That is only safe because of draft/publish -- a half-built test is never
public. The publish pipeline is the precondition for this editing model, not an
optimisation on top of it.
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.common.caching import bump_content_version
from apps.common.models import PublishStatus
from apps.content.enums import (
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
    Question,
    QuestionGroup,
    Section,
    Test,
)
from apps.content.publishing import publish_test

from .access import staff_required
from .forms import (
    AnswerKeyForm,
    BlockForm,
    BulkBlockForm,
    OptionForm,
    QuestionForm,
    QuestionGroupForm,
    TestForm,
    parse_blocks,
)
from .nav import page_context


def saved(extra_trigger=None) -> HttpResponse:
    """An empty 204 with a trigger the toast listens for."""
    response = HttpResponse(status=204)
    response["HX-Trigger"] = extra_trigger or "saved"
    return response


def _hydrated(test_id) -> Test:
    return get_object_or_404(
        Test.objects.prefetch_related(
            "sections__blocks",
            "sections__groups__questions__options",
            "sections__groups__questions__answer_keys",
            "sections__groups__options",
        ),
        pk=test_id,
    )


def _renumber(test) -> None:
    """Display numbers run across the whole test, in section then group order.

    Written in two passes. Assigning final numbers one row at a time would, part
    way through, give two questions the same number and trip the uniqueness
    constraint on (test, number) -- reordering is exactly the case where the old
    and new numbering overlap.
    """
    ordered = [
        question
        for section in test.sections.order_by("order")
        for group in section.groups.order_by("order")
        for question in group.questions.order_by("order")
    ]
    if not ordered:
        return

    offset = (
        Question.objects.filter(test=test).aggregate(m=Max("number"))["m"] or 0
    ) + len(ordered) + 1

    with transaction.atomic():
        for index, question in enumerate(ordered):
            Question.objects.filter(pk=question.pk).update(number=offset + index)
        for number, question in enumerate(ordered, start=1):
            Question.objects.filter(pk=question.pk).update(number=number)


def _group_card(request, group):
    """Re-render a whole group card.

    Any change to a shared option pool re-renders the card rather than patching
    each <select> in place: one template, always consistent, and no chance of
    the pool and the pickers drifting apart.
    """
    group.refresh_from_db()
    return render(
        request,
        "dashboard/partials/group_card.html",
        {"group": group, "questions": group.questions.order_by("order")},
    )


# --- pages ---------------------------------------------------------------------


@staff_required
def test_create(request):
    if request.method == "POST":
        form = TestForm(request.POST)
        if form.is_valid():
            test = form.save(commit=False)
            test.created_by = request.user
            test.status = PublishStatus.DRAFT
            test.save()
            Section.objects.create(test=test, order=1, title=test.title)
            return redirect("dashboard:test-edit", pk=test.pk)
    else:
        form = TestForm(initial={"skill": request.GET.get("skill", Skill.READING)})

    return render(request, "dashboard/test_form.html", page_context(request, form=form))


@staff_required
def test_edit(request, pk):
    test = _hydrated(pk)
    return render(
        request,
        "dashboard/test_edit.html",
        page_context(
            request,
            test=test,
            form=TestForm(instance=test),
            bulk_form=BulkBlockForm(),
            question_types=QuestionType.choices,
            is_listening=test.skill == Skill.LISTENING,
            audio_assets=AudioAsset.objects.order_by("-created_at"),
            visibility_choices=TranscriptVisibility.choices,
        ),
    )


@staff_required
def test_preview(request, pk):
    """Renders the live payload, answers included, without touching publish."""
    from apps.content.publishing import build_test_payload, published_queryset

    test = get_object_or_404(published_queryset(), pk=pk)
    return render(
        request,
        "dashboard/test_preview.html",
        page_context(request, test=test, payload=build_test_payload(test)),
    )


@staff_required
@require_POST
def test_publish(request, pk):
    test = get_object_or_404(Test, pk=pk)
    if not Question.objects.filter(test=test).exists():
        messages.error(request, "Add at least one question before publishing.")
        return redirect("dashboard:test-edit", pk=pk)

    _renumber(test)
    publish_test(test)
    bump_content_version()
    messages.success(request, f"Published {test.title}.")
    return redirect("dashboard:test-edit", pk=pk)


@staff_required
@require_POST
def test_unpublish(request, pk):
    test = get_object_or_404(Test, pk=pk)
    Test.objects.filter(pk=pk).update(status=PublishStatus.DRAFT)
    bump_content_version()
    messages.success(request, f"{test.title} is back to draft and no longer served.")
    return redirect("dashboard:test-edit", pk=pk)


# --- htmx fragments ------------------------------------------------------------


@staff_required
@require_POST
def test_meta_save(request, pk):
    test = get_object_or_404(Test, pk=pk)

    # Optimistic locking: a stale write loses rather than silently overwriting.
    submitted_version = request.POST.get("version")
    if submitted_version and int(submitted_version) != test.version:
        return HttpResponse("Someone else saved first.", status=409)

    form = TestForm(request.POST, instance=test)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)

    test = form.save(commit=False)
    test.version += 1
    test.save()
    return saved()


@staff_required
@require_POST
def section_bulk_blocks(request, pk):
    section = get_object_or_404(Section.objects.select_related("test"), pk=pk)
    form = BulkBlockForm(request.POST)
    if not form.is_valid():
        return HttpResponse("Nothing to import.", status=400)

    parsed = parse_blocks(
        form.cleaned_data["text"], as_transcript=section.test.skill == Skill.LISTENING
    )
    if not parsed:
        return HttpResponse("Nothing to import.", status=400)

    with transaction.atomic():
        if form.cleaned_data.get("replace"):
            section.blocks.all().delete()
        start = (section.blocks.aggregate(m=Max("order"))["m"] or 0) + 1
        Block.objects.bulk_create(
            Block(section=section, order=start + index, label=label, text=text)
            for index, (label, text) in enumerate(parsed)
        )

    return render(
        request,
        "dashboard/partials/block_list.html",
        {"section": section, "blocks": section.blocks.order_by("order")},
    )


@staff_required
@require_http_methods(["POST", "DELETE"])
def block_detail(request, pk):
    block = get_object_or_404(Block, pk=pk)
    if request.method == "DELETE":
        block.delete()
        return HttpResponse(status=200)

    form = BlockForm(request.POST, instance=block)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def group_create(request, pk):
    section = get_object_or_404(Section, pk=pk)
    qtype = request.POST.get("type", QuestionType.TFNG)
    if qtype not in QuestionType.values:
        raise Http404

    is_matching = qtype == QuestionType.MATCHING
    group = QuestionGroup.objects.create(
        section=section,
        order=(section.groups.aggregate(m=Max("order"))["m"] or 0) + 1,
        type=qtype,
        # Derived, never asked for: these are the only combinations the model
        # allows, so offering them as choices would only invite invalid states.
        options_scope=OptionsScope.SHARED if is_matching else OptionsScope.PER_QUESTION,
        match_mode=MatchMode.NORMALIZED if qtype == QuestionType.GAP else MatchMode.EXACT,
    )
    return _group_card(request, group)


@staff_required
@require_http_methods(["POST", "DELETE"])
def group_detail(request, pk):
    group = get_object_or_404(QuestionGroup, pk=pk)
    if request.method == "DELETE":
        test = group.section.test
        group.delete()
        _renumber(test)
        return HttpResponse(status=200)

    form = QuestionGroupForm(request.POST, instance=group)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def question_create(request, pk):
    group = get_object_or_404(QuestionGroup.objects.select_related("section__test"), pk=pk)
    test = group.section.test

    with transaction.atomic():
        question = Question.objects.create(
            group=group,
            test=test,
            order=(group.questions.aggregate(m=Max("order"))["m"] or 0) + 1,
            number=(Question.objects.filter(test=test).aggregate(m=Max("number"))["m"] or 0) + 1,
            prompt="",
        )
        _seed_answer_scaffolding(question, group)
        _renumber(test)

    return _group_card(request, group)


def _seed_answer_scaffolding(question, group) -> None:
    """Create the rows each type needs so the editor never shows an empty shell."""
    if group.type == QuestionType.TFNG:
        AnswerKey.objects.create(question=question, value="TRUE")
    elif group.type == QuestionType.GAP:
        AnswerKey.objects.create(question=question, value="", order=0)
    elif group.type == QuestionType.MCQ:
        for index in range(4):
            Option.objects.create(
                group=group, question=question, order=index + 1,
                label=chr(ord("A") + index), text="",
            )


@staff_required
@require_http_methods(["POST", "DELETE"])
def question_detail(request, pk):
    question = get_object_or_404(Question.objects.select_related("group__section__test"), pk=pk)
    if request.method == "DELETE":
        test = question.test
        group = question.group
        question.delete()
        _renumber(test)
        return _group_card(request, group)

    form = QuestionForm(request.POST, instance=question)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()
    return saved()


@staff_required
@require_POST
def option_save(request, pk):
    option = get_object_or_404(Option, pk=pk)
    form = OptionForm(request.POST, instance=option)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)
    form.save()

    # A shared pool feeds every picker in the group, so re-render the card.
    if option.group.has_shared_pool:
        return _group_card(request, option.group)
    return saved()


@staff_required
@require_POST
def pool_option_create(request, pk):
    group = get_object_or_404(QuestionGroup, pk=pk)
    count = group.options.filter(question__isnull=True).count()
    Option.objects.create(
        group=group,
        question=None,
        order=count + 1,
        label=chr(ord("A") + count) if count < 26 else str(count + 1),
        text="",
    )
    return _group_card(request, group)


@staff_required
@require_http_methods(["DELETE"])
def pool_option_delete(request, pk):
    option = get_object_or_404(Option, pk=pk)
    group = option.group
    option.delete()
    return _group_card(request, group)


@staff_required
@require_POST
def answer_set(request, pk):
    """Set the answer for one question, whatever shape its type needs."""
    question = get_object_or_404(Question.objects.select_related("group"), pk=pk)
    group = question.group

    with transaction.atomic():
        question.answer_keys.all().delete()

        if group.uses_options:
            option_id = request.POST.get("optionId")
            option = Option.objects.filter(pk=option_id, group=group).first()
            if option is None:
                return HttpResponse("Pick one of the options.", status=400)
            AnswerKey.objects.create(question=question, option=option, value=option.text)
        elif group.type == QuestionType.TFNG:
            value = request.POST.get("value", "")
            if value not in ("TRUE", "FALSE", "NOT GIVEN"):
                return HttpResponse("Expected TRUE, FALSE or NOT GIVEN.", status=400)
            AnswerKey.objects.create(question=question, value=value)
        else:  # gap: any number of accepted spellings
            values = [v.strip() for v in request.POST.getlist("value") if v.strip()]
            if not values:
                return HttpResponse("Add at least one accepted answer.", status=400)
            AnswerKey.objects.bulk_create(
                AnswerKey(question=question, value=value, order=index)
                for index, value in enumerate(values)
            )

    return saved()


@staff_required
@require_POST
def answer_key_add(request, pk):
    """Another accepted spelling for a gap question."""
    question = get_object_or_404(Question.objects.select_related("group"), pk=pk)
    form = AnswerKeyForm(request.POST)
    if not form.is_valid():
        return HttpResponse(str(form.errors), status=400)

    AnswerKey.objects.create(
        question=question,
        value=form.cleaned_data["value"],
        order=(question.answer_keys.aggregate(m=Max("order"))["m"] or 0) + 1,
    )
    return _group_card(request, question.group)


@staff_required
@require_http_methods(["DELETE"])
def answer_key_delete(request, pk):
    key = get_object_or_404(AnswerKey.objects.select_related("question__group"), pk=pk)
    group = key.question.group
    key.delete()
    return _group_card(request, group)


@staff_required
@require_POST
def reorder(request, model, pk):
    """Apply a new order to a container's children in one update.

    Drag and drop posts here, and so do the up/down buttons -- drag-only
    reordering is unusable with a keyboard.
    """
    models = {
        "group-questions": (QuestionGroup, "questions"),
        "section-groups": (Section, "groups"),
        "section-blocks": (Section, "blocks"),
    }
    if model not in models:
        raise Http404

    parent_model, related = models[model]
    parent = get_object_or_404(parent_model, pk=pk)
    ids = [int(i) for i in request.POST.getlist("order[]") or request.POST.getlist("order")]

    manager = getattr(parent, related)
    children = {c.id: c for c in manager.all()}
    ordered = [children[i] for i in ids if i in children]

    with transaction.atomic():
        # Two passes. Writing the final positions directly would, part way
        # through, give two rows the same order and trip the unique constraint.
        offset = (manager.aggregate(m=Max("order"))["m"] or 0) + 1
        for index, child in enumerate(ordered):
            manager.filter(pk=child.pk).update(order=offset + index)
        for position, child in enumerate(ordered, start=1):
            manager.filter(pk=child.pk).update(order=position)

        test = parent.test if isinstance(parent, Section) else parent.section.test
        _renumber(test)

    return saved("reordered")
