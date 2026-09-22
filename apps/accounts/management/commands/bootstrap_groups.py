"""Create the staff roles.

Django's own permission framework is sufficient here; a bespoke RBAC layer
would be a rewrite of something that already works.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

CONTENT_APPS = ["content", "vocabulary", "writing", "speaking"]

ROLES = {
    "Content Editor": {
        "apps": CONTENT_APPS,
        "actions": ["add", "change", "view"],
    },
    "Content Publisher": {
        "apps": [*CONTENT_APPS, "grading"],
        "actions": ["add", "change", "delete", "view"],
    },
    "Analyst": {
        "apps": [*CONTENT_APPS, "grading", "accounts"],
        "actions": ["view"],
    },
}


class Command(BaseCommand):
    help = "Create or update the staff permission groups. Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        for name, spec in ROLES.items():
            group, created = Group.objects.get_or_create(name=name)
            permissions = Permission.objects.filter(
                content_type__app_label__in=spec["apps"],
                codename__regex=r"^(" + "|".join(spec["actions"]) + ")_",
            )
            group.permissions.set(permissions)
            verb = "created" if created else "updated"
            self.stdout.write(f"  {verb:8} {name:<20} {permissions.count():>3} permissions")

        self.stdout.write(self.style.SUCCESS(f"{len(ROLES)} groups ready"))
