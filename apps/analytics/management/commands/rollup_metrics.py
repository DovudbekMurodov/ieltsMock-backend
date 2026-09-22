"""Aggregate a day (or a range) into the rollup tables.

Idempotent and backfillable by design: --since repairs a gap, and running twice
over the same day changes nothing. That property is what makes a timer safe to
rely on.
"""

from datetime import date as date_cls
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.analytics.rollups import rollup_range, rollup_user_progress


def parse_date(value: str) -> date_cls:
    try:
        return date_cls.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"{value!r} is not a YYYY-MM-DD date.") from exc


class Command(BaseCommand):
    help = "Roll up attempts into daily metrics, test stats and question stats."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="A single day (YYYY-MM-DD). Defaults to yesterday.")
        parser.add_argument("--since", help="Backfill from this day up to yesterday.")
        parser.add_argument(
            "--include-today",
            action="store_true",
            help="Also roll up today, which is otherwise still changing.",
        )

    def handle(self, *args, **options):
        today = timezone.now().date()
        end = today if options["include_today"] else today - timedelta(days=1)

        if options["since"]:
            start = parse_date(options["since"])
        elif options["date"]:
            start = end = parse_date(options["date"])
        else:
            start = end

        if start > end:
            raise CommandError(f"{start} is after {end}; nothing to do.")

        totals = rollup_range(start, end)
        rollup_user_progress()

        span = f"{start}" if start == end else f"{start}..{end}"
        self.stdout.write(
            self.style.SUCCESS(
                f"{span}: {totals['daily_metrics']} metrics, {totals['test_stats']} test stats, "
                f"{totals['question_stats']} question stats"
            )
        )
