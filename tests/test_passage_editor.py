"""The passage is written in one editor and stored as structured rows.

The two directions have to agree: what `editor_html` puts on the page must
come back out of `save_passage` unchanged, or an author loses work by opening
a part and closing it again.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.content.enums import BlockKind, Skill
from apps.content.models import Block, Section, Test
from apps.content.passage import editor_html, is_lettered, save_passage

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff(client):
    client.force_login(
        User.objects.create_user(email="writer@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


@pytest.fixture
def section(db):
    test = Test.objects.create(
        skill=Skill.READING, slug="one-document", title="One document", time_limit_minutes=20
    )
    return Section.objects.create(test=test, order=1, title="Part 1")


@pytest.fixture
def transcript(db):
    test = Test.objects.create(
        skill=Skill.LISTENING, slug="one-transcript", title="Spoken", time_limit_minutes=30
    )
    return Section.objects.create(test=test, order=1, title="Part 1")


def post(staff, section, blocks, letter=False):
    return staff.post(
        reverse("dashboard:hx-passage", args=[section.pk]),
        data=json.dumps({"blocks": blocks, "letter": letter}),
        content_type="application/json",
    )


def rows(section):
    return [(b.kind, b.label, b.text) for b in section.blocks.order_by("order")]


# --- saving --------------------------------------------------------------


def test_the_document_is_stored_as_one_row_per_paragraph(staff, section):
    """The editor is one surface; the payload is JSON the app renders directly,
    so what it holds is structure rather than the editor's markup."""
    response = post(
        staff,
        section,
        [
            {"kind": "section", "text": "The Globe"},
            {"kind": "paragraph", "text": "It opened in 1599."},
            {"kind": "rule", "text": ""},
            {"kind": "heading", "text": "Afterwards"},
            {"kind": "paragraph", "text": "It burned down."},
        ],
    )

    assert response.status_code == 204
    assert rows(section) == [
        ("section", "", "The Globe"),
        ("paragraph", "", "It opened in 1599."),
        ("rule", "", ""),
        ("heading", "", "Afterwards"),
        ("paragraph", "", "It burned down."),
    ]


def test_saving_replaces_the_whole_passage(staff, section):
    """The editor owns the document. Patching row by row would mean working out
    which paragraph is which after one was split in two and another deleted."""
    Block.objects.create(section=section, order=1, text="Gone")

    post(staff, section, [{"kind": "paragraph", "text": "Here instead"}])

    assert rows(section) == [("paragraph", "", "Here instead")]


def test_bold_survives_the_round_trip(staff, section):
    post(staff, section, [{"kind": "paragraph", "text": "Opened in **1599** nearby."}])

    assert editor_html(section.blocks.all()) == "<p>Opened in <strong>1599</strong> nearby.</p>"


def test_empty_paragraphs_are_dropped(staff, section):
    """Pressing Enter twice is how a person makes room to think, not a request
    for an empty paragraph in the payload."""
    post(
        staff,
        section,
        [
            {"kind": "paragraph", "text": "One"},
            {"kind": "paragraph", "text": "   "},
            {"kind": "paragraph", "text": "Two"},
        ],
    )

    assert rows(section) == [("paragraph", "", "One"), ("paragraph", "", "Two")]


def test_a_divider_survives_having_no_text(staff, section):
    post(staff, section, [{"kind": "rule", "text": ""}])

    assert rows(section) == [("rule", "", "")]


def test_an_unknown_kind_becomes_a_paragraph(staff, section):
    """Refusing would lose the words. A paragraph is the safe reading of
    anything a future editor sends that this one does not know."""
    post(staff, section, [{"kind": "iframe", "text": "Still my words"}])

    assert rows(section) == [("paragraph", "", "Still my words")]


def test_markup_in_the_text_is_stored_as_characters(staff, section):
    """The one thing a content editor must never make possible is the app
    rendering author-supplied markup."""
    post(staff, section, [{"kind": "paragraph", "text": "<script>alert(1)</script>"}])

    assert section.blocks.get().text == "<script>alert(1)</script>"
    assert "<script>" not in editor_html(section.blocks.all())


def test_a_body_that_is_not_json_is_refused(staff, section):
    response = staff.post(
        reverse("dashboard:hx-passage", args=[section.pk]),
        data="not json at all",
        content_type="application/json",
    )

    assert response.status_code == 400


def test_a_document_without_blocks_is_refused(staff, section):
    response = staff.post(
        reverse("dashboard:hx-passage", args=[section.pk]),
        data=json.dumps({"letter": True}),
        content_type="application/json",
    )

    assert response.status_code == 400


def test_the_passage_is_staff_only(client, section):
    response = client.post(
        reverse("dashboard:hx-passage", args=[section.pk]),
        data=json.dumps({"blocks": []}),
        content_type="application/json",
    )

    assert response.status_code in (302, 403)
    assert not section.blocks.exists()


# --- lettering -----------------------------------------------------------


def test_lettering_is_one_switch_for_the_whole_passage(staff, section):
    """It is a property of the passage, not of each paragraph: A, B, C follow
    the order on screen, and headings are not paragraphs."""
    post(
        staff,
        section,
        [
            {"kind": "section", "text": "The Globe"},
            {"kind": "paragraph", "text": "First"},
            {"kind": "paragraph", "text": "Second"},
        ],
        letter=True,
    )

    assert rows(section) == [
        ("section", "", "The Globe"),
        ("paragraph", "A", "First"),
        ("paragraph", "B", "Second"),
    ]


def test_turning_lettering_off_clears_the_letters(staff, section):
    post(staff, section, [{"kind": "paragraph", "text": "First"}], letter=True)
    post(staff, section, [{"kind": "paragraph", "text": "First"}], letter=False)

    assert rows(section) == [("paragraph", "", "First")]


def test_lettering_is_read_back_off_the_labels(section):
    """No flag of its own, because a second field recording that the labels
    exist is a thing that can disagree with them."""
    Block.objects.create(section=section, order=1, label="A", text="First")

    assert is_lettered(section.blocks.all())
    assert not is_lettered([Block(kind=BlockKind.PARAGRAPH, label="", text="First")])


def test_lettering_runs_past_z(section):
    save_passage(
        section,
        [{"kind": "paragraph", "text": f"Paragraph {n}"} for n in range(27)],
        letter=True,
    )

    assert section.blocks.order_by("order").last().label == "27"


# --- transcripts ---------------------------------------------------------


def test_a_speaker_is_split_off_the_line(staff, transcript):
    """"Tutor: Good morning" is how a transcript reads. Splitting it back out
    is the editor's job, not the author's."""
    post(
        staff,
        transcript,
        [
            {"kind": "paragraph", "text": "Tutor: Good morning."},
            {"kind": "paragraph", "text": "Student: Hello."},
        ],
    )

    assert rows(transcript) == [
        ("paragraph", "Tutor", "Good morning."),
        ("paragraph", "Student", "Hello."),
    ]


def test_a_line_without_a_speaker_keeps_all_of_its_text(staff, transcript):
    post(staff, transcript, [{"kind": "paragraph", "text": "A long pause."}])

    assert rows(transcript) == [("paragraph", "", "A long pause.")]


def test_a_speaker_comes_back_into_the_editor_with_the_line(transcript):
    Block.objects.create(section=transcript, order=1, label="Tutor", text="Good morning.")

    assert editor_html(transcript.blocks.all(), as_transcript=True) == (
        "<p>Tutor: Good morning.</p>"
    )


def test_a_transcript_is_never_lettered(staff, transcript):
    """A, B, C down the margin of a conversation means nothing."""
    post(staff, transcript, [{"kind": "paragraph", "text": "Just talking."}], letter=True)

    assert transcript.blocks.get().label == ""


# --- the page ------------------------------------------------------------


def test_the_editor_page_carries_the_document_and_the_tools(staff, section):
    Block.objects.create(section=section, order=1, kind=BlockKind.SECTION, text="The Globe")
    Block.objects.create(section=section, order=2, text="Opened in **1599**.")

    body = staff.get(reverse("dashboard:test-edit", args=[section.test.pk])).content.decode()

    assert "<h2>The Globe</h2>" in body
    assert "<strong>1599</strong>" in body
    assert 'contenteditable="true"' in body
    for tool in (">Title<", ">Heading<", ">Text<"):
        assert tool in body


def test_the_preview_renders_what_was_saved(staff, section):
    """Built from the published payload's own blocks, so a preview cannot show
    something that would not survive publishing."""
    post(
        staff,
        section,
        [
            {"kind": "section", "text": "The Globe"},
            {"kind": "paragraph", "text": "Opened in **1599**."},
            {"kind": "rule", "text": ""},
        ],
    )

    body = staff.get(reverse("dashboard:hx-passage-preview", args=[section.pk])).content.decode()

    assert "The Globe" in body
    assert "<strong>1599</strong>" in body
    assert "<hr" in body


def test_the_preview_escapes_what_the_author_typed(staff, section):
    post(staff, section, [{"kind": "paragraph", "text": "<img src=x onerror=alert(1)>"}])

    body = staff.get(reverse("dashboard:hx-passage-preview", args=[section.pk])).content.decode()

    assert "<img src=x" not in body
    assert "&lt;img" in body


def test_an_empty_part_renders_an_empty_editor(staff, section):
    body = staff.get(reverse("dashboard:test-edit", args=[section.test.pk])).content.decode()

    assert 'data-placeholder=' in body


def test_the_staff_preview_draws_the_passage_like_the_app(staff, section):
    """It printed the **bold** markers as characters and gave every block a
    stray "." where a label would go, because it predated both and was never
    taught about kinds."""
    section.test.status = "published"
    section.test.save(update_fields=["status"])
    post(
        staff,
        section,
        [
            {"kind": "section", "text": "The Globe"},
            {"kind": "paragraph", "text": "Opened in **1599**."},
        ],
    )

    body = staff.get(reverse("dashboard:test-preview", args=[section.test.pk])).content.decode()

    assert "**1599**" not in body
    assert "<strong>1599</strong>" in body
    assert "<h2" in body
