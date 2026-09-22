from django.urls import reverse

from apps.content.enums import Skill
from apps.content.models import AudioAsset, Test
from apps.speaking.models import SpeakingTopic
from apps.vocabulary.models import VocabularySection
from apps.writing.models import WritingTask


def build_nav(request):
    current = request.path

    def item(label, url_name, icon, count=None, **kwargs):
        url = reverse(url_name, kwargs=kwargs) if kwargs else reverse(url_name)
        return {
            "label": label,
            "url": url,
            "icon": icon,
            "count": count,
            # Prefix match so a detail page keeps its section highlighted,
            # except for the overview which would otherwise always match.
            "active": current == url or (url != "/dashboard/" and current.startswith(url)),
        }

    return [
        item("Overview", "dashboard:overview", "◴"),
        {"divider": "Content"},
        item(
            "Reading",
            "dashboard:test-list",
            "▤",
            Test.objects.filter(skill=Skill.READING).count(),
        ),
        item(
            "Listening",
            "dashboard:listening-list",
            "▶",
            Test.objects.filter(skill=Skill.LISTENING).count(),
        ),
        item("Writing", "dashboard:writing-list", "✎", WritingTask.objects.count()),
        item("Speaking", "dashboard:speaking-list", "◌", SpeakingTopic.objects.count()),
        item("Audio", "dashboard:audio-library", "\u266a", AudioAsset.objects.count()),
        item(
            "Vocabulary",
            "dashboard:vocabulary-list",
            "◈",
            VocabularySection.objects.count(),
        ),
        {"divider": "People"},
        item("Students", "dashboard:user-list", "○"),
        item("Attempts", "dashboard:attempt-list", "◑"),
        {"divider": "Settings"},
        item("Band scales", "dashboard:band-scale-list", "▣"),
    ]


def page_context(request, **extra):
    return {"nav_items": build_nav(request), **extra}
