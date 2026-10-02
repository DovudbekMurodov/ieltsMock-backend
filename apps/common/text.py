"""Text helpers shared by the content apps."""

import re

BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def split_bold(text: str) -> list[dict]:
    """Split ``a **b** c`` into ordered {text, bold} parts.

    Returned by the API so the frontend does not have to parse markers itself,
    and so nothing has to render author-supplied HTML to show a bold word.
    """
    parts = []
    cursor = 0
    for match in BOLD_PATTERN.finditer(text):
        if match.start() > cursor:
            parts.append({"text": text[cursor : match.start()], "bold": False})
        parts.append({"text": match.group(1), "bold": True})
        cursor = match.end()
    if cursor < len(text):
        parts.append({"text": text[cursor:], "bold": False})
    return parts
