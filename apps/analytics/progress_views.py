"""One read endpoint for the signed-in candidate's own standing.

UserProgress already stores most of this, but it is written by the nightly
`rollup_metrics` command, so a candidate who finishes a test and opens the
dashboard would be told they have done nothing. Progress a person can watch
move has to be computed when it is asked for, so this reads the attempts
directly and leaves UserProgress to the staff reporting it was built for.

The overall band is the part worth being careful about. A real IELTS overall is
the mean of four skills, and this API has bands for two of them — writing only
once a human has graded it, and speaking not at all. So the response reports
which skills went into the number rather than presenting a two-skill average as
if it were an exam result.
"""

from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attempts.models import AttemptStatus, TestAttempt
from apps.grading.bands import round_to_half_band
from apps.writing.models import WritingSubmission


def _live_streak(days) -> int:
    """Consecutive days of activity ending today or yesterday.

    Same rule as rollups._streak, but counting every kind of practice rather
    than test attempts alone: a day spent on writing is not a day off.
    """
    days = sorted(set(days), reverse=True)
    if not days:
        return 0

    today = timezone.now().date()
    if (today - days[0]).days > 1:
        return 0

    streak, cursor = 1, days[0]
    for day in days[1:]:
        gap = (cursor - day).days
        if gap == 1:
            streak += 1
            cursor = day
        elif gap > 1:
            break
    return streak


def _decimal_or_none(value):
    return str(value) if value is not None else None


@extend_schema(
    operation_id="myProgress",
    summary="This user's live progress across skills",
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_progress(request):
    attempts = list(
        TestAttempt.objects.filter(user=request.user)
        .exclude(status=AttemptStatus.IN_PROGRESS)
        .select_related("test")
        .order_by("-submitted_at")
    )

    graded_writing = list(
        WritingSubmission.objects.filter(user=request.user, feedback__isnull=False)
        .select_related("feedback")
        .order_by("-submitted_at")
    )

    by_skill = {}
    for attempt in attempts:
        by_skill.setdefault(attempt.test.skill, []).append(attempt)

    skills = []
    for skill, history in sorted(by_skill.items()):
        bands = [a.band for a in history if a.band is not None]
        percents = [a.percent for a in history if a.percent is not None]
        latest = history[0]
        skills.append(
            {
                "skill": skill,
                "attempts": len(history),
                "bestBand": _decimal_or_none(max(bands) if bands else None),
                "latestBand": _decimal_or_none(bands[0] if bands else None),
                # Averaged over attempts rather than over questions: a 40
                # question test and a 10 question one say equally much about
                # how the candidate is doing today.
                "avgPercent": _decimal_or_none(
                    round(sum(percents) / len(percents), 2) if percents else None
                ),
                "lastActiveAt": latest.submitted_at,
                # The same caveat the attempt itself carries. Most seeded tests
                # are short, so most of these are estimates.
                "bandConfidence": latest.band_confidence,
            }
        )

    if graded_writing:
        writing_bands = [s.feedback.overall for s in graded_writing]
        skills.append(
            {
                "skill": "writing",
                "attempts": len(graded_writing),
                "bestBand": _decimal_or_none(max(writing_bands)),
                "latestBand": _decimal_or_none(writing_bands[0]),
                "avgPercent": None,
                "lastActiveAt": graded_writing[0].submitted_at,
                # A human read it, so unlike a short mock this is not an estimate.
                "bandConfidence": "high",
            }
        )

    contributing = [s["skill"] for s in skills if s["latestBand"] is not None]
    latest_bands = [Decimal(s["latestBand"]) for s in skills if s["latestBand"] is not None]
    overall = round_to_half_band(sum(latest_bands) / len(latest_bands)) if latest_bands else None

    all_percents = [a.percent for a in attempts if a.percent is not None]
    accuracy = round(sum(all_percents) / len(all_percents), 2) if all_percents else None

    activity_days = [a.submitted_at.date() for a in attempts if a.submitted_at]
    activity_days += [s.submitted_at.date() for s in graded_writing if s.submitted_at]

    return Response(
        {
            "streakDays": _live_streak(activity_days),
            "accuracy": _decimal_or_none(accuracy),
            "overallBand": _decimal_or_none(overall),
            # Four skills make an IELTS overall. Anything short of that is an
            # average of what we happen to have, and saying so is the
            # difference between a useful signal and a made-up score.
            "overallBandIsPartial": len(contributing) < 4,
            "contributingSkills": contributing,
            "totalAttempts": len(attempts),
            "skills": skills,
        }
    )
