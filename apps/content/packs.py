"""The pack fields every list item carries, so the client can group without a second request."""


def pack_payload(pack) -> dict | None:
    if pack is None:
        return None
    return {
        "id": pack.slug,
        "title": pack.title,
        "description": pack.description,
        "order": pack.order,
    }


def pack_fields(item) -> dict:
    """`pack`, `packPosition` and `packLabel` for a Test, WritingTask or SpeakingTopic."""
    return {
        "pack": pack_payload(item.pack),
        "packPosition": item.pack_position,
        "packLabel": item.pack_label,
    }
