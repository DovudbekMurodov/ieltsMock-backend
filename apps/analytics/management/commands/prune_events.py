"""Drop raw events past their retention window.

The rollups keep the shape of the history, so the raw rows only need to live
long enough to be re-aggregated if a rollup was wrong.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.analytics.models import Event


class Command(BaseCommand):
    help = "Delete Event rows older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = Event.objects.filter(occurred_at__lt=cutoff)
        count = stale.count()

        if options["dry_run"]:
            self.stdout.write(f"would delete {count} event(s) before {cutoff:%Y-%m-%d}")
            return

        stale.delete()
        self.stdout.write(
            self.style.SUCCESS(f"deleted {count} event(s) before {cutoff:%Y-%m-%d}")
        )
