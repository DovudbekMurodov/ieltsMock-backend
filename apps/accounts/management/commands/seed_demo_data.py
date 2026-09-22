"""Create demo accounts so dashboard pages are built against realistic data.

Building analytics views against empty tables makes "no data" and "broken
query" look identical. Attempt history is added here once the attempts app
lands; for now this seeds the people.
"""

import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

FIRST_NAMES = [
    "Aziza", "Bekzod", "Dilnoza", "Eldor", "Feruza", "Gulnora", "Hasan",
    "Iroda", "Jasur", "Kamola", "Lola", "Madina", "Nodir", "Oybek",
    "Sardor", "Shahzod", "Umida", "Zilola", "Rustam", "Nilufar",
]
LAST_NAMES = [
    "Karimov", "Yusupova", "Rahimov", "Tosheva", "Nazarov", "Islomova",
    "Qodirov", "Saidova", "Turgunov", "Ergasheva",
]

DEMO_PASSWORD = "demo-password-1234"  # noqa: S105 - local demo data only


class Command(BaseCommand):
    help = "Create demo staff and student accounts. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=25)
        parser.add_argument("--seed", type=int, default=20260922, help="RNG seed.")

    @transaction.atomic
    def handle(self, *args, **options):
        # Deterministic demo names; nothing here is security-sensitive.
        rng = random.Random(options["seed"])  # noqa: S311

        staff_created = 0
        for email, first, last in [
            ("editor@preppath.test", "Content", "Editor"),
            ("analyst@preppath.test", "Data", "Analyst"),
        ]:
            _, created = User.objects.get_or_create(
                email=email,
                defaults={"first_name": first, "last_name": last, "is_staff": True},
            )
            staff_created += created

        students_created = 0
        for index in range(options["students"]):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            _, created = User.objects.get_or_create(
                email=f"student{index + 1:02d}@preppath.test",
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "target_band": rng.choice(["6.0", "6.5", "7.0", "7.5", "8.0"]),
                    "country": "UZ",
                    "timezone": "Asia/Tashkent",
                },
            )
            students_created += created

        for user in User.objects.filter(email__endswith="@preppath.test"):
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])

        self.stdout.write(
            self.style.SUCCESS(
                f"staff +{staff_created}, students +{students_created} "
                f"(password for all demo accounts: {DEMO_PASSWORD})"
            )
        )
