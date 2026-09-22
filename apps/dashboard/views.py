from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attempts.models import AttemptStatus, TestAttempt
from apps.common.models import PublishStatus
from apps.content.enums import Skill
from apps.content.models import Question, Test
from apps.grading.models import BandScale
from apps.speaking.models import SpeakingTopic
from apps.vocabulary.models import VocabularySection, VocabularyWord
from apps.writing.models import WritingTask

from .access import staff_required
from .nav import page_context

# --- authentication ------------------------------------------------------------


def login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("dashboard:overview")

    error = None
    if request.method == "POST":
        user = authenticate(
            request, username=request.POST.get("email"), password=request.POST.get("password")
        )
        if user is None or not user.is_staff:
            # Same message either way: a distinct "not staff" reply would
            # confirm the address belongs to a real account.
            error = "Incorrect email or password."
        else:
            auth_login(request, user)
            return redirect(request.GET.get("next") or "dashboard:overview")

    return render(request, "dashboard/login.html", {"error": error})


@require_POST
def logout(request):
    auth_logout(request)
    return redirect("dashboard:login")


# --- overview ------------------------------------------------------------------


@staff_required
def overview(request):
    now = timezone.now()
    since = now - timedelta(days=14)

    submitted = TestAttempt.objects.exclude(status=AttemptStatus.IN_PROGRESS)
    recent = submitted.filter(submitted_at__gte=since)

    by_day = []
    for offset in range(13, -1, -1):
        day = (now - timedelta(days=offset)).date()
        by_day.append(
            (day.strftime("%d/%m"), recent.filter(submitted_at__date=day).count())
        )

    band_buckets = []
    for low in range(4, 10):
        band_buckets.append(
            (f"{low}", submitted.filter(band__gte=low, band__lt=low + 1).count())
        )

    per_skill = [
        (
            skill.label,
            submitted.filter(test__skill=skill.value).count(),
        )
        for skill in Skill
    ]

    totals = {
        "tests": Test.objects.count(),
        "published": Test.objects.filter(status=PublishStatus.PUBLISHED).count(),
        "drafts": Test.objects.filter(status=PublishStatus.DRAFT).count(),
        "questions": Question.objects.count(),
        "words": VocabularyWord.objects.count(),
        "writing": WritingTask.objects.count(),
        "speaking": SpeakingTopic.objects.count(),
        "attempts": submitted.count(),
        "attempts_recent": recent.count(),
        "in_progress": TestAttempt.objects.filter(status=AttemptStatus.IN_PROGRESS).count(),
        "avg_percent": submitted.aggregate(v=Avg("percent"))["v"],
        "learners": submitted.values("user").distinct().count(),
    }

    # An item sitting at 0% or 100% is usually broken rather than hard: an
    # ambiguous prompt, a wrong key, or a giveaway.
    flagged = (
        Question.objects.annotate(
            seen=Count("attemptanswer"),
            correct=Count("attemptanswer", filter=Q(attemptanswer__is_correct=True)),
        )
        .filter(seen__gte=5)
        .order_by("correct")[:8]
    )

    return render(
        request,
        "dashboard/overview.html",
        page_context(
            request,
            totals=totals,
            by_day=by_day,
            band_buckets=band_buckets,
            per_skill=per_skill,
            flagged=flagged,
            recent_attempts=submitted.select_related("test", "user").order_by("-submitted_at")[:8],
            unpublished=Test.objects.exclude(status=PublishStatus.PUBLISHED).order_by("title")[:5],
        ),
    )


# --- content lists -------------------------------------------------------------


def _test_list(request, skill, title):
    tests = (
        Test.objects.filter(skill=skill)
        # Annotation names must not collide with the related_name they count.
        .annotate(question_total=Count("questions", distinct=True))
        .order_by("title")
    )
    return render(
        request,
        "dashboard/test_list.html",
        page_context(request, tests=tests, skill=skill, page_title=title),
    )


@staff_required
def test_list(request):
    return _test_list(request, Skill.READING, "Reading tests")


@staff_required
def listening_list(request):
    return _test_list(request, Skill.LISTENING, "Listening tests")


@staff_required
def writing_list(request):
    return render(
        request,
        "dashboard/writing_list.html",
        page_context(
            request,
            tasks=WritingTask.objects.prefetch_related("model_answers").order_by("slug"),
        ),
    )


@staff_required
def speaking_list(request):
    return render(
        request,
        "dashboard/speaking_list.html",
        page_context(
            request,
            topics=SpeakingTopic.objects.annotate(item_total=Count("items")).order_by("order"),
        ),
    )


@staff_required
def vocabulary_list(request):
    return render(
        request,
        "dashboard/vocabulary_list.html",
        page_context(
            request,
            sections=VocabularySection.objects.annotate(
                word_total=Count("words")
            ).order_by("order"),
        ),
    )


# --- people --------------------------------------------------------------------


@staff_required
def user_list(request):
    from django.contrib.auth import get_user_model

    query = request.GET.get("q", "").strip()
    users = (
        get_user_model()
        # Annotation names must not collide with the related_name they count.
        .objects.annotate(
            attempt_total=Count(
                "attempts", filter=~Q(attempts__status=AttemptStatus.IN_PROGRESS)
            ),
            avg_band=Avg("attempts__band"),
        )
        .order_by("-date_joined")
    )
    if query:
        users = users.filter(Q(email__icontains=query) | Q(first_name__icontains=query))

    return render(
        request, "dashboard/user_list.html", page_context(request, users=users[:100], query=query)
    )


@staff_required
def user_detail(request, pk):
    from django.contrib.auth import get_user_model

    student = get_object_or_404(get_user_model(), pk=pk)
    attempts = (
        TestAttempt.objects.filter(user=student)
        .exclude(status=AttemptStatus.IN_PROGRESS)
        .select_related("test")
        .order_by("-submitted_at")
    )
    trend = [
        (a.submitted_at.strftime("%d/%m"), float(a.percent or 0))
        for a in reversed(list(attempts[:12]))
    ]
    return render(
        request,
        "dashboard/user_detail.html",
        page_context(request, student=student, attempts=attempts[:50], trend=trend),
    )


@staff_required
def attempt_list(request):
    attempts = (
        TestAttempt.objects.exclude(status=AttemptStatus.IN_PROGRESS)
        .select_related("test", "user")
        .order_by("-submitted_at")
    )
    skill = request.GET.get("skill")
    if skill in Skill.values:
        attempts = attempts.filter(test__skill=skill)

    return render(
        request,
        "dashboard/attempt_list.html",
        page_context(request, attempts=attempts[:100], skill=skill),
    )


@staff_required
def attempt_detail(request, pk):
    attempt = get_object_or_404(
        TestAttempt.objects.select_related("test", "user", "band_scale"), pk=pk
    )
    answers = attempt.answers.select_related("question").order_by("question_number")
    return render(
        request,
        "dashboard/attempt_detail.html",
        page_context(request, attempt=attempt, answers=answers),
    )


# --- band scales ---------------------------------------------------------------


@staff_required
def band_scale_list(request):
    scales = BandScale.objects.prefetch_related("rows").order_by("skill", "name")
    problems = {}
    for scale in scales:
        try:
            scale.validate_rows()
        except Exception as exc:  # surfaced in the UI, not raised
            problems[scale.id] = str(exc)

    return render(
        request,
        "dashboard/band_scale_list.html",
        page_context(request, scales=scales, problems=problems),
    )


@staff_required
@require_POST
def band_scale_row_update(request, pk):
    scale = get_object_or_404(BandScale, pk=pk)
    for row in scale.rows.all():
        value = request.POST.get(f"band_{row.id}")
        if value:
            row.band = value
            row.save(update_fields=["band"])
    messages.success(request, f"Updated {scale.name}.")
    return redirect("dashboard:band-scale-list")
