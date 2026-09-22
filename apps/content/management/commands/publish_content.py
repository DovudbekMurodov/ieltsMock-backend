"""Materialise public payloads for every published object.

Run after seeding or a bulk content edit. Idempotent: republishing unchanged
content produces the same ETag.
"""

from django.core.management.base import BaseCommand

from apps.common.caching import bump_content_version
from apps.common.models import PublishStatus
from apps.content.models import Test
from apps.content.publishing import publish_test
from apps.vocabulary.models import VocabularySection
from apps.vocabulary.publishing import publish_section


class Command(BaseCommand):
    help = "Build published_payload for tests and vocabulary sections."

    def add_arguments(self, parser):
        parser.add_argument("--slug", help="Publish only this slug.")

    def handle(self, *args, **options):
        slug = options.get("slug")

        tests = Test.objects.exclude(status=PublishStatus.ARCHIVED)
        sections = VocabularySection.objects.exclude(status=PublishStatus.ARCHIVED)
        if slug:
            tests = tests.filter(slug=slug)
            sections = sections.filter(slug=slug)

        for test in tests:
            publish_test(test)
            self.stdout.write(f"  test        {test.slug}  {test.payload_etag[:12]}")

        for section in sections:
            publish_section(section)
            self.stdout.write(f"  vocabulary  {section.slug}  {section.payload_etag[:12]}")

        bump_content_version()
        self.stdout.write(
            self.style.SUCCESS(f"published {tests.count()} tests, {sections.count()} sections")
        )
