"""Preview a test, writing task or speaking topic as a paper, and export it.

One page for all three: the preview shows the paper with the current options,
and the same form downloads it as PDF, Word or JSON.
"""

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.text import slugify

from apps.content.enums import Skill

from . import exporting
from .access import staff_required
from .nav import page_context


def _load(kind: str, key: str) -> dict:
    """Everything the two views need to know about one exportable thing."""
    if kind == "test":
        if not key.isdigit():
            raise Http404
        test = get_object_or_404(exporting.test_queryset().select_related("pack"), pk=int(key))
        has_explanations = any(
            q.explanation
            for s in test.sections.all()
            for g in s.groups.all()
            for q in g.questions.all()
        )
        return {
            "object": test,
            "title": test.title,
            "skill": test.get_skill_display(),
            "paper": exporting.test_paper,
            "json": exporting.test_json,
            "back": reverse("dashboard:test-edit", args=[test.pk]),
            "options": [
                ("answers", "Answer key"),
                *([("explanations", "Explanations")] if has_explanations else []),
                *([("transcript", "Transcript")] if test.skill == Skill.LISTENING else []),
            ],
        }
    if kind == "writing":
        from apps.writing.models import WritingTask

        task = get_object_or_404(WritingTask.objects.select_related("pack"), slug=key)
        return {
            "object": task,
            "title": (
                f"{task.pack.title} · {task.pack_label}"
                if task.pack_id
                else f"Writing Task {task.task_number} · {task.slug}"
            ),
            "skill": "Writing",
            "paper": exporting.writing_paper,
            "json": exporting.writing_json,
            "back": reverse("dashboard:writing-edit", args=[task.slug]),
            "options": [("model_answers", "Model answers")] if task.model_answers.exists() else [],
        }
    if kind == "speaking":
        from apps.speaking.models import SpeakingTopic

        topic = get_object_or_404(
            SpeakingTopic.objects.select_related("pack", "cue_card").prefetch_related("items"),
            slug=key,
        )
        return {
            "object": topic,
            "title": topic.title,
            "skill": "Speaking",
            "paper": exporting.speaking_paper,
            "json": exporting.speaking_json,
            "back": reverse("dashboard:speaking-edit", args=[topic.slug]),
            "options": [],
        }
    raise Http404


@staff_required
def paper_preview(request, kind, key):
    item = _load(kind, key)
    opts = exporting.Options.from_query(request.GET)
    fmt = request.GET.get("format", "pdf")
    return render(
        request,
        "dashboard/paper_preview.html",
        page_context(
            request,
            item=item,
            elements=exporting.html_elements(item["paper"](item["object"], opts)),
            opts=opts,
            fmt=fmt if fmt in exporting.FORMATS else "pdf",
            preview_url=reverse("dashboard:paper-preview", args=[kind, key]),
            export_url=reverse("dashboard:paper-export", args=[kind, key]),
        ),
    )


@staff_required
def paper_export(request, kind, key):
    item = _load(kind, key)
    opts = exporting.Options.from_query(request.GET)
    fmt = request.GET.get("format", "pdf")
    if fmt not in exporting.FORMATS:
        raise Http404

    if fmt == "json":
        body = exporting.to_json(item["json"](item["object"], opts))
    else:
        elements = item["paper"](item["object"], opts)
        body = (
            exporting.to_docx(elements)
            if fmt == "docx"
            else exporting.to_pdf(elements, item["title"])
        )

    name = slugify(f"{item['skill']} {item['title']}") or "paper"
    response = HttpResponse(body, content_type=exporting.CONTENT_TYPES[fmt])
    response["Content-Disposition"] = f'attachment; filename="{name}.{fmt}"'
    return response
