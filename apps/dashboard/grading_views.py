"""Writing grading queue."""

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.speaking.models import SpeakingSession
from apps.writing.models import SubmissionStatus, WritingFeedback, WritingSubmission

from .access import staff_required
from .forms import TEXT_INPUT, TEXTAREA
from .nav import page_context

BAND_CHOICES = [(f"{value / 2:.1f}", f"{value / 2:.1f}") for value in range(0, 19)]


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = WritingFeedback
        fields = (
            "task_achievement",
            "coherence_cohesion",
            "lexical_resource",
            "grammatical_range",
            "comment",
        )
        widgets = {
            "task_achievement": forms.Select(choices=BAND_CHOICES, attrs=TEXT_INPUT),
            "coherence_cohesion": forms.Select(choices=BAND_CHOICES, attrs=TEXT_INPUT),
            "lexical_resource": forms.Select(choices=BAND_CHOICES, attrs=TEXT_INPUT),
            "grammatical_range": forms.Select(choices=BAND_CHOICES, attrs=TEXT_INPUT),
            "comment": forms.Textarea(attrs={**TEXTAREA, "rows": 8}),
        }
        labels = {
            "task_achievement": "Task achievement",
            "coherence_cohesion": "Coherence & cohesion",
            "lexical_resource": "Lexical resource",
            "grammatical_range": "Grammatical range & accuracy",
        }


@staff_required
def grading_queue(request):
    show = request.GET.get("show", "pending")

    submissions = (
        WritingSubmission.objects.exclude(status=SubmissionStatus.DRAFT)
        .select_related("task", "user")
        .prefetch_related("feedback")
    )
    if show == "pending":
        submissions = submissions.filter(status=SubmissionStatus.SUBMITTED)
    elif show == "graded":
        submissions = submissions.filter(status=SubmissionStatus.GRADED)

    counts = WritingSubmission.objects.aggregate(
        pending=Count("id", filter=Q(status=SubmissionStatus.SUBMITTED)),
        graded=Count("id", filter=Q(status=SubmissionStatus.GRADED)),
    )

    return render(
        request,
        "dashboard/grading_queue.html",
        page_context(
            request,
            submissions=submissions.order_by("submitted_at")[:100],
            show=show,
            counts=counts,
        ),
    )


@staff_required
def grade_submission(request, pk):
    submission = get_object_or_404(
        WritingSubmission.objects.select_related("task", "user").prefetch_related(
            "feedback", "task__model_answers"
        ),
        pk=pk,
    )
    feedback = getattr(submission, "feedback", None)

    if request.method == "POST":
        form = FeedbackForm(request.POST, instance=feedback)
        if form.is_valid():
            saved_feedback = form.save(commit=False)
            saved_feedback.submission = submission
            saved_feedback.grader = request.user
            # overall is derived in save(), so it can never disagree with the
            # four criteria it summarises.
            saved_feedback.save()
            messages.success(request, f"Graded — band {saved_feedback.overall}.")
            return redirect("dashboard:grading-queue")
    else:
        form = FeedbackForm(instance=feedback)

    return render(
        request,
        "dashboard/grade_submission.html",
        page_context(request, submission=submission, form=form, feedback=feedback),
    )


@staff_required
@require_POST
def return_to_draft(request, pk):
    """Hand a submission back so the student can revise it."""
    submission = get_object_or_404(WritingSubmission, pk=pk)
    submission.status = SubmissionStatus.DRAFT
    submission.submitted_at = None
    submission.save(update_fields=["status", "submitted_at", "updated_at"])
    messages.success(request, "Returned to the student as a draft.")
    return redirect("dashboard:grading-queue")


@staff_required
def speaking_sessions(request):
    sessions = (
        SpeakingSession.objects.select_related("topic", "user")
        .order_by("-created_at")[:100]
    )
    return render(
        request,
        "dashboard/speaking_sessions.html",
        page_context(
            request,
            sessions=sessions,
            completed=SpeakingSession.objects.exclude(completed_at__isnull=True).count(),
            total=SpeakingSession.objects.count(),
        ),
    )
