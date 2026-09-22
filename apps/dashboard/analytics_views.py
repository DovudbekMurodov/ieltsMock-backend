"""Analytics pages.

Historical numbers come from the rollup tables so these queries stay cheap as
the event table grows. Today is not in a rollup yet, so it is computed live
from a bounded query and cached briefly -- one day of events is always small.
"""

from datetime import timedelta

from django.core.cache import cache
from django.db.models import Avg, Count, F, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.analytics.models import DailyMetric, Event, QuestionStat, TestStat, UserProgress
from apps.attempts.models import AttemptStatus, TestAttempt
from apps.common.caching import versioned_key
from apps.content.models import Question, Test

from .access import staff_required
from .nav import page_context

TODAY_CACHE_SECONDS = 60


def today_counts() -> dict:
    """Live numbers for the current day, cached for a minute."""
    key = versioned_key("dashboard", "today")
    cached = cache.get(key)
    if cached is not None:
        return cached

    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    events = Event.objects.filter(occurred_at__gte=start)
    counts = {
        "events": events.count(),
        "starts": events.filter(name="test.started").count(),
        "submissions": events.filter(name="test.submitted").count(),
        "signups": events.filter(name="auth.signup").count(),
        "people": events.exclude(user__isnull=True).values("user").distinct().count(),
    }
    cache.set(key, counts, TODAY_CACHE_SECONDS)
    return counts


def series(metric_key: str, days: int, dimension: str = "") -> list[tuple[str, int]]:
    """A dense daily series -- missing days read as zero, not as a gap."""
    today = timezone.now().date()
    start = today - timedelta(days=days - 1)
    rows = {
        row["date"]: row["value_int"]
        for row in DailyMetric.objects.filter(
            metric_key=metric_key, dimension_key=dimension, date__gte=start
        ).values("date", "value_int")
    }
    return [
        ((start + timedelta(days=offset)).strftime("%d/%m"),
         rows.get(start + timedelta(days=offset), 0))
        for offset in range(days)
    ]


@staff_required
def analytics_overview(request):
    days = min(int(request.GET.get("days", 30)), 90)
    since = timezone.now() - timedelta(days=days)

    event_mix = (
        Event.objects.filter(occurred_at__gte=since)
        .values("name")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    return render(
        request,
        "dashboard/analytics.html",
        page_context(
            request,
            days=days,
            today=today_counts(),
            submissions=series("attempts.submitted", days),
            starts=series("attempts.started", days),
            active_users=series("users.active", days),
            reading=series("attempts.submitted", days, "reading"),
            listening=series("attempts.submitted", days, "listening"),
            event_mix=[(row["name"], row["total"]) for row in event_mix],
            top_tests=(
                TestStat.objects.filter(date__gte=since.date())
                .values("test__slug", "test__title")
                .annotate(total=Sum("completions"), avg=Avg("avg_percent"))
                .order_by("-total")[:8]
            ),
            leaders=(
                UserProgress.objects.select_related("user")
                .exclude(best_band__isnull=True)
                .order_by("-best_band")[:8]
            ),
            has_rollups=DailyMetric.objects.exists(),
        ),
    )


@staff_required
def question_analysis(request):
    """Which items are broken.

    Accuracy alone is not the signal -- a hard question is legitimate. What is
    suspicious is an item nearly everyone misses (usually a wrong key or an
    ambiguous prompt) or one nobody misses (usually a giveaway).
    """
    minimum = int(request.GET.get("min", 5))

    stats = (
        Question.objects.annotate(
            seen=Sum("stats__seen"),
            correct=Sum("stats__correct"),
        )
        .filter(seen__gte=minimum)
        .select_related("test", "group")
        .annotate(accuracy=100.0 * F("correct") / F("seen"))
    )

    return render(
        request,
        "dashboard/question_analysis.html",
        page_context(
            request,
            minimum=minimum,
            too_hard=stats.filter(accuracy__lt=25).order_by("accuracy")[:20],
            too_easy=stats.filter(accuracy__gt=95).order_by("-accuracy")[:20],
            counted=stats.count(),
            by_type=(
                QuestionStat.objects.values(type=F("question__group__type"))
                .annotate(seen=Sum("seen"), correct=Sum("correct"))
                .order_by("type")
            ),
        ),
    )


@staff_required
def test_analytics(request, slug):
    test = get_object_or_404(Test, slug=slug)
    attempts = TestAttempt.objects.filter(test=test).exclude(status=AttemptStatus.IN_PROGRESS)

    questions = (
        Question.objects.filter(test=test)
        .annotate(
            seen=Count("attemptanswer"),
            correct=Count("attemptanswer", filter=Q(attemptanswer__is_correct=True)),
        )
        .select_related("group")
        .order_by("number")
    )

    return render(
        request,
        "dashboard/test_analytics.html",
        page_context(
            request,
            test=test,
            attempts=attempts.count(),
            avg_percent=attempts.aggregate(v=Avg("percent"))["v"],
            questions=questions,
            stats=TestStat.objects.filter(test=test).order_by("-date")[:30],
        ),
    )
