from .models import SpeakingItemKind


def build_topic_payload(topic) -> dict:
    items = list(topic.items.order_by("part", "kind", "order"))

    def texts(part, kind):
        return [i.text for i in items if i.part == part and i.kind == kind]

    cue = getattr(topic, "cue_card", None)
    return {
        "id": topic.slug,
        "topic": topic.title,
        "part1": texts(1, SpeakingItemKind.QUESTION),
        "part2": (
            {
                "title": cue.title,
                "bullets": texts(2, SpeakingItemKind.BULLET),
                "prepSeconds": cue.prep_seconds,
                "speakSeconds": cue.speak_seconds,
            }
            if cue
            else None
        ),
        "part3": texts(3, SpeakingItemKind.QUESTION),
        "phrases": texts(3, SpeakingItemKind.PHRASE),
    }
