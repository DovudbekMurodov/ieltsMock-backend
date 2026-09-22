"""Close attempts whose clock ran out and were never submitted.

Idempotent and backfillable, which is what makes running it from a timer safe:
a missed night costs nothing and a double run is harmless.
"""

from django.core.management.base import BaseCommand

from apps.attempts.services import expire_stale_attempts


class Command(BaseCommand):
    help = "Score and close abandoned attempts past their deadline."

    def handle(self, *args, **options):
        closed = expire_stale_attempts()
        self.stdout.write(self.style.SUCCESS(f"closed {closed} stale attempt(s)"))
