import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.content.enums import Skill
from apps.content.seeding import seed_test
from apps.speaking.seeding import seed_topic
from apps.vocabulary.seeding import seed_section
from apps.writing.seeding import seed_task

DATASETS = ("reading", "listening", "writing", "speaking", "vocabulary")


class Command(BaseCommand):
    help = "Load seed/data/*.json into the content models. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(settings.BASE_DIR / "seed" / "data"),
            help="Directory holding the exported JSON files.",
        )
        parser.add_argument(
            "--only",
            action="append",
            choices=DATASETS,
            help="Seed only these datasets. Repeatable.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_dir():
            raise CommandError(f"{path} is not a directory. Run seed/export_from_frontend.mjs.")

        wanted = set(options["only"] or DATASETS)
        loaders = {
            "reading": lambda rows: self._tests(rows, Skill.READING),
            "listening": lambda rows: self._tests(rows, Skill.LISTENING),
            "writing": self._writing,
            "speaking": self._speaking,
            "vocabulary": self._vocabulary,
        }

        for name in DATASETS:
            if name not in wanted:
                continue
            source = path / f"{name}.json"
            if not source.exists():
                raise CommandError(f"Missing {source}.")
            rows = json.loads(source.read_text(encoding="utf-8"))
            count = loaders[name](rows)
            self.stdout.write(self.style.SUCCESS(f"{name:<11} {count:>3} records"))

    def _tests(self, rows, skill):
        for raw in rows:
            seed_test(raw, skill)
        return len(rows)

    def _writing(self, rows):
        for raw in rows:
            seed_task(raw)
        return len(rows)

    def _speaking(self, rows):
        for order, raw in enumerate(rows, start=1):
            seed_topic(raw, order)
        return len(rows)

    def _vocabulary(self, rows):
        for order, raw in enumerate(rows, start=1):
            seed_section(raw, order)
        return len(rows)
