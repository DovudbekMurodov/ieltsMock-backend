"""Nightly aggregation.

Every function here is idempotent and takes an explicit date, which is what
makes running them from a timer safe: a missed night is one flag away from
fixed, and a double run changes nothing.
"""

import statistics
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.attempts.models import AttemptAnswer, AttemptStatus, TestAttempt
from apps.content.models import Test

from .models import DailyMetric, QuestionStat, TestStat, UserProgress


def _submitted_on(date):
    return TestAttempt.objects.filter(
        submitted_at__date=date
    ).exclude(status=AttemptStatus.IN_PROGRESS)


def rollup_daily_metrics(date) -> int:
    attempts = _submitted_on(date)
    started = TestAttempt.objects.filter(started_at__date=date)

    metrics = {
        ("attempts.submitted", ""): attempts.count(),
        ("attempts.started", ""): started.count(),
        ("attempts.expired", ""): attempts.filter(status=AttemptStatus.EXPIRED).count(),
        ("users.active", ""): attempts.exclude(user__isnull=True).values("user").distinct().count(),
        ("attempts.guest", ""): attempts.filter(user__isnull=True).count(),
    }
    for skill in ("reading", "listening"):
        metrics[("attempts.submitted", skill)] = attempts.filter(test__skill=skill).count()

    for (key, dimension), value in metrics.items():
        DailyMetric.objects.update_or_create(
            date=date, metric_key=key, dimension_key=dimension, defaults={"value_int": value}
        )

    average = attempts.aggregate(v=Avg("percent"))["v"]
    DailyMetric.objects.update_or_create(
        date=date,
        metric_key="attempts.avg_percent",
        dimension_key="",
        defaults={"value_int": int(average or 0), "value_dec": average},
    )
    return len(metrics) + 1


def rollup_test_stats(date) -> int:
    written = 0
    for test in Test.objects.all():
        attempts = _submitted_on(date).filter(test=test)
        started = TestAttempt.objects.filter(test=test, started_at__date=date).count()
        if not attempts.exists() and not started:
            continue

        # `is not None`, not truthiness: a zero-second attempt is a real
        # value and belongs in the median.
        durations = [a.duration_seconds for a in attempts if a.duration_seconds is not None]
        aggregate = attempts.aggregate(p=Avg("percent"), b=Avg("band"))
        TestStat.objects.update_or_create(
            test=test,
            date=date,
            defaults={
                "attempts": started,
                "completions": attempts.count(),
                "avg_percent": aggregate["p"],
                "avg_band": aggregate["b"],
                "median_duration_s": int(statistics.median(durations)) if durations else None,
            },
        )
        written += 1
    return written


def rollup_question_stats(date) -> int:
    rows = (
        AttemptAnswer.objects.filter(attempt__submitted_at__date=date)
        .values("question_id")
        .annotate(seen=Count("id"), correct=Count("id", filter=Q(is_correct=True)))
    )
    for row in rows:
        seen = row["seen"] or 0
        QuestionStat.objects.update_or_create(
            question_id=row["question_id"],
            date=date,
            defaults={
                "seen": seen,
                "correct": row["correct"],
                "accuracy": round(row["correct"] / seen * 100, 2) if seen else 0,
            },
        )
    return len(rows)


def rollup_user_progress() -> int:
    """Current standing, not a daily series -- upsert over the whole history."""
    rows = (
        TestAttempt.objects.exclude(status=AttemptStatus.IN_PROGRESS)
        .exclude(user__isnull=True)
        .values("user_id", "test__skill")
        .annotate(attempts=Count("id"), avg_percent=Avg("percent"))
    )
    written = 0
    for row in rows:
        history = (
            TestAttempt.objects.filter(user_id=row["user_id"], test__skill=row["test__skill"])
            .exclude(status=AttemptStatus.IN_PROGRESS)
            .order_by("-submitted_at")
        )
        bands = [a.band for a in history if a.band is not None]
        latest = history.first()
        UserProgress.objects.update_or_create(
            user_id=row["user_id"],
            skill=row["test__skill"],
            defaults={
                "attempts": row["attempts"],
                "avg_percent": row["avg_percent"],
                "best_band": max(bands) if bands else None,
                "latest_band": bands[0] if bands else None,
                "streak_days": _streak(history),
                "last_active_at": latest.submitted_at if latest else None,
            },
        )
        written += 1
    return written


def _streak(history) -> int:
    """Consecutive days ending today or yesterday."""
    days = sorted({a.submitted_at.date() for a in history if a.submitted_at}, reverse=True)
    if not days:
        return 0

    today = timezone.now().date()
    if (today - days[0]).days > 1:
        return 0

    streak, cursor = 1, days[0]
    for day in days[1:]:
        if (cursor - day).days == 1:
            streak += 1
            cursor = day
        elif (cursor - day).days > 1:
            break
    return streak


def rollup_for(date) -> dict:
    return {
        "daily_metrics": rollup_daily_metrics(date),
        "test_stats": rollup_test_stats(date),
        "question_stats": rollup_question_stats(date),
    }


def rollup_range(start, end) -> dict:
    totals = {"daily_metrics": 0, "test_stats": 0, "question_stats": 0}
    day = start
    while day <= end:
        for key, value in rollup_for(day).items():
            totals[key] += value
        day += timedelta(days=1)
    totals["user_progress"] = rollup_user_progress()
    return totals
