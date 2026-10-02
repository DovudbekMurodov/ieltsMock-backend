import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.common.models import PublishStatus
from apps.content.enums import BlockKind, Skill
from apps.content.models import Block, Section, Test
from apps.content.publishing import build_test_payload, published_queryset

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff(client):
    client.force_login(
        User.objects.create_user(email="editor@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


@pytest.fixture
def draft(db):
    test = Test.objects.create(
        skill=Skill.READING, slug="draft-parts", title="Draft", time_limit_minutes=20
    )
    Section.objects.create(test=test, order=1, title="Part 1")
    return test


# --- parts ---------------------------------------------------------------


def test_a_test_can_be_created_with_several_parts(staff):
    """A full reading paper is three passages. One section was created
    regardless and nothing could add a second, so a full paper was
    unbuildable."""
    staff.post(
        reverse("dashboard:test-create"),
        {
            "title": "Full paper",
            "slug": "full-paper",
            "skill": Skill.READING,
            "time_limit_minutes": 60,
            "parts": "3",
            "description": "",
            "difficulty": "",
        },
    )

    test = Test.objects.get(slug="full-paper")
    assert [s.title for s in test.sections.order_by("order")] == ["Part 1", "Part 2", "Part 3"]


def test_a_single_part_test_takes_the_test_title(staff):
    staff.post(
        reverse("dashboard:test-create"),
        {
            "title": "One passage",
            "slug": "one-passage",
            "skill": Skill.READING,
            "time_limit_minutes": 20,
            "parts": "1",
            "description": "",
            "difficulty": "",
        },
    )

    assert Test.objects.get(slug="one-passage").sections.get().title == "One passage"


def test_a_part_can_be_added_afterwards(staff, draft):
    staff.post(reverse("dashboard:section-create", args=[draft.pk]))

    assert draft.sections.count() == 2
    assert draft.sections.order_by("order").last().title == "Part 2"


def test_a_part_can_be_renamed(staff, draft):
    section = draft.sections.get()

    staff.post(reverse("dashboard:hx-section", args=[section.pk]), {"title": "Reading Passage 1"})

    section.refresh_from_db()
    assert section.title == "Reading Passage 1"


def test_the_last_part_cannot_be_deleted(staff, draft):
    """Deleting it would leave a test with nowhere to put anything."""
    section = draft.sections.get()

    response = staff.delete(reverse("dashboard:hx-section", args=[section.pk]))

    assert response.status_code == 400
    assert draft.sections.count() == 1


def test_a_part_can_be_deleted_when_it_is_not_the_last(staff, draft):
    Section.objects.create(test=draft, order=2, title="Part 2")

    staff.delete(reverse("dashboard:hx-section", args=[draft.sections.order_by("order").last().pk]))

    assert draft.sections.count() == 1


# --- block kinds ---------------------------------------------------------


def test_a_heading_or_divider_can_be_added_by_hand(staff, draft):
    """The paste box takes a whole passage; a single heading had no route."""
    section = draft.sections.get()

    staff.post(reverse("dashboard:hx-block-create", args=[section.pk]), {"kind": "heading"})
    staff.post(reverse("dashboard:hx-block-create", args=[section.pk]), {"kind": "rule"})

    assert list(section.blocks.order_by("order").values_list("kind", flat=True)) == [
        "heading",
        "rule",
    ]


def test_an_unknown_block_kind_is_refused(staff, draft):
    response = staff.post(
        reverse("dashboard:hx-block-create", args=[draft.sections.get().pk]), {"kind": "iframe"}
    )

    assert response.status_code == 404


def test_the_kind_reaches_the_published_payload(staff, draft):
    section = draft.sections.get()
    Block.objects.create(section=section, order=1, kind=BlockKind.HEADING, text="The Globe")
    Block.objects.create(section=section, order=2, kind=BlockKind.RULE, text="")

    payload = build_test_payload(published_queryset().get(pk=draft.pk))
    blocks = payload["sections"][0]["blocks"]

    assert [b["kind"] for b in blocks] == ["heading", "rule"]


def test_bold_markers_are_split_server_side():
    """The payload carries structure, not markup.

    Shipping the raw string would mean the app rendering author-supplied HTML
    to show a bold word, which is the one thing a content editor must never
    make possible.
    """
    test = Test.objects.create(
        skill=Skill.READING, slug="bolded", title="Bolded", time_limit_minutes=20
    )
    section = Section.objects.create(test=test, order=1, title="Part 1")
    Block.objects.create(section=section, order=1, text="Opened in **1599** nearby.")

    payload = build_test_payload(published_queryset().get(pk=test.pk))
    parts = payload["sections"][0]["blocks"][0]["parts"]

    assert parts == [
        {"text": "Opened in ", "bold": False},
        {"text": "1599", "bold": True},
        {"text": " nearby.", "bold": False},
    ]


def test_a_divider_carries_no_parts(staff, draft):
    section = draft.sections.get()
    Block.objects.create(section=section, order=1, kind=BlockKind.RULE, text="")

    payload = build_test_payload(published_queryset().get(pk=draft.pk))

    assert payload["sections"][0]["blocks"][0]["parts"] == []


def test_the_editor_page_offers_every_block_kind(staff, draft):
    body = staff.get(reverse("dashboard:test-edit", args=[draft.pk])).content.decode()

    for _, label in BlockKind.choices:
        assert f"+ {label}" in body


def test_an_imported_draft_is_still_a_draft_with_several_parts(staff):
    """Parts on create must not quietly publish anything."""
    staff.post(
        reverse("dashboard:test-create"),
        {
            "title": "Three parts",
            "slug": "three-parts",
            "skill": Skill.READING,
            "time_limit_minutes": 60,
            "parts": "3",
            "description": "",
            "difficulty": "",
        },
    )

    assert Test.objects.get(slug="three-parts").status == PublishStatus.DRAFT
