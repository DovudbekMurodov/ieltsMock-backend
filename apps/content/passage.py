"""The passage as one document, in both directions.

The author writes in a single editor: type, select a word and make it bold, put
the caret on a line and make it a title. That is how every other writing tool
works, and a column of one-paragraph boxes is not.

The model underneath is still one row per paragraph, because the published
payload is JSON the app renders directly -- a stored HTML string would mean the
app running author-supplied markup to show a heading. So this module is the
join between the two. ``editor_html`` builds the document out of the rows and
``save_passage`` takes it apart again, and neither side ever trusts the other's
markup: what comes back from the browser is a list of {kind, text} with the
text as plain characters.
"""

from django.db import transaction
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from apps.common.text import split_bold

from .enums import BlockKind
from .models import Block

# A title opens a part of the paper, a heading sits inside it. Both are
# headings in the payload; only the weight differs, which is why the app
# renders them as h2 and h3 rather than as two unrelated things.
TAGS = {BlockKind.SECTION: "h2", BlockKind.HEADING: "h3"}


def _letter(index: int) -> str:
    """A, B, C ... then plain numbers once the alphabet runs out."""
    return chr(ord("A") + index) if index < 26 else str(index + 1)


def editor_html(blocks, *, as_transcript: bool = False) -> str:
    """The stored rows as one document the browser can edit.

    Every piece of author text goes through ``escape`` on the way out, and the
    only markup added is this module's own: two heading levels, paragraphs,
    rules and <strong>. That is what makes the ``mark_safe`` at the end true.
    """
    document = []

    for block in blocks:
        if block.kind == BlockKind.RULE:
            document.append("<hr>")
            continue

        body = "".join(
            format_html("<strong>{}</strong>", part["text"])
            if part["bold"]
            else escape(part["text"])
            for part in split_bold(block.text)
        )

        # A speaker belongs in the line the author edits -- "Tutor: Good
        # morning" is how a transcript reads, and splitting it back out is this
        # module's job, not the author's.
        if as_transcript and block.label and block.kind == BlockKind.PARAGRAPH:
            body = escape(f"{block.label}: ") + body

        tag = TAGS.get(block.kind, "p")
        document.append(f"<{tag}>{body or '<br>'}</{tag}>")

    return mark_safe("".join(document))  # noqa: S308 - built from escaped parts only


def is_lettered(blocks) -> bool:
    """Whether this passage's paragraphs carry A, B, C labels.

    Read back off the data rather than stored as a flag of its own: the labels
    are the state, and a second field recording that they exist is a thing that
    can disagree with them.
    """
    return any(b.label for b in blocks if b.kind == BlockKind.PARAGRAPH)


def save_passage(section, items, *, letter: bool = False, as_transcript: bool = False) -> None:
    """Replace this section's blocks with the document the editor sent.

    Replacing rather than patching: the editor owns the whole document, and
    working out which paragraph is which after an author has split one in two
    and deleted another is a diff nobody needs. Nothing points at a Block, so
    the rows are free to be recreated.
    """
    rows = []

    for item in items:
        kind = item.get("kind")
        if kind not in BlockKind.values:
            kind = BlockKind.PARAGRAPH

        if kind == BlockKind.RULE:
            rows.append([kind, "", ""])
            continue

        text = (item.get("text") or "").strip()
        if not text:
            continue

        label = ""
        if as_transcript and kind == BlockKind.PARAGRAPH:
            speaker, _, said = text.partition(":")
            if said.strip():
                label, text = speaker.strip()[:60], said.strip()

        rows.append([kind, label, text])

    if letter and not as_transcript:
        # Lettering is a property of the passage, not of each paragraph, so it
        # is one switch and the letters follow the order on screen. Headings
        # and rules are skipped: an IELTS passage letters its paragraphs.
        index = 0
        for row in rows:
            if row[0] == BlockKind.PARAGRAPH:
                row[1] = _letter(index)
                index += 1

    with transaction.atomic():
        section.blocks.all().delete()
        Block.objects.bulk_create(
            Block(section=section, order=order, kind=kind, label=label, text=text)
            for order, (kind, label, text) in enumerate(rows, start=1)
        )
