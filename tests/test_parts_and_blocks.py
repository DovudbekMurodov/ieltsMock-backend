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


def _create(staff, **overrides):
    payload = {
        "title": "Full paper",
        "skill": Skill.READING,
        "time_limit_minutes": 60,
        "parts": "part-1",
        "description": "",
        "difficulty": "",
    }
    return staff.post(reverse("dashboard:test-create"), {**payload, **overrides})


def test_a_full_paper_is_built_with_all_its_parts(staff):
    """A full reading paper is three passages. One section was created
    regardless and nothing could add a second, so a full paper was
    unbuildable."""
    _create(staff, title="Full paper", parts="full-3")

    test = Test.objects.get(title="Full paper")
    assert [s.title for s in test.sections.order_by("order")] == ["Part 1", "Part 2", "Part 3"]


def test_a_full_listening_paper_is_four_parts(staff):
    _create(staff, title="Listening paper", skill=Skill.LISTENING, parts="full-4")

    test = Test.objects.get(title="Listening paper")
    assert [s.title for s in test.sections.order_by("order")] == [
        "Part 1",
        "Part 2",
        "Part 3",
        "Part 4",
    ]


def test_a_single_part_test_is_named_for_the_part_it_is(staff):
    """It took the test's own title, so a test called "a" showed a tab called
    "a" — which says nothing about which part of a paper it is."""
    _create(staff, title="One passage", parts="part-3")

    assert Test.objects.get(title="One passage").sections.get().title == "Part 3"


def test_the_form_offers_every_shape_of_paper(staff):
    body = staff.get(reverse("dashboard:test-create")).content.decode()

    for shape in ("part-1", "part-2", "part-3", "part-4", "full-3", "full-4"):
        assert f'value="{shape}"' in body


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
    _create(staff, title="Three parts", parts="full-3")

    assert Test.objects.get(title="Three parts").status == PublishStatus.DRAFT


def test_the_editor_shows_one_part_at_a_time(staff, draft):
    """Three parts stacked down one column put the passage editor below the
    fold three times over. The page carries a tab per part now."""
    Section.objects.create(test=draft, order=2, title="Part 2")
    body = staff.get(reverse("dashboard:test-edit", args=[draft.pk])).content.decode()

    for section in draft.sections.all():
        assert f"part === {section.pk}" in body


def test_each_part_tab_carries_its_question_count(staff, draft):
    """Annotated in the view, so the tabs do not fire a query each."""
    response = staff.get(reverse("dashboard:test-edit", args=[draft.pk]))

    section = response.context["test"].sections.get()
    assert hasattr(section, "questions_count")


def test_the_slug_is_generated_from_the_title(staff):
    """The field is gone from the form entirely. Inventing a unique URL by hand
    for every test is a chore with nothing at the end of it, and getting it
    wrong is an error on the one field the author cared least about."""
    _create(staff, title="The Globe Theatre")

    assert Test.objects.get(title="The Globe Theatre").slug == "the-globe-theatre"


def test_no_page_asks_for_a_slug(staff):
    create = staff.get(reverse("dashboard:test-create")).content.decode()
    _create(staff, title="The Globe Theatre")
    test = Test.objects.get(title="The Globe Theatre")
    edit = staff.get(reverse("dashboard:test-edit", args=[test.pk])).content.decode()

    for body in (create, edit):
        assert 'name="slug"' not in body


def test_a_generated_slug_steps_aside_for_one_already_taken(staff):
    Test.objects.create(
        skill=Skill.READING, slug="the-globe-theatre", title="Older", time_limit_minutes=20
    )

    _create(staff, title="The Globe Theatre")

    created = Test.objects.get(title="The Globe Theatre")
    assert created.slug.startswith("the-globe-theatre-")
    assert created.slug != "the-globe-theatre"


def test_renaming_a_test_keeps_its_url(staff, draft):
    """The slug is the public URL; a rename must not break the links to it."""
    staff.post(
        reverse("dashboard:hx-test-meta", args=[draft.pk]),
        {
            "title": "Renamed",
            "skill": draft.skill,
            "description": "",
            "time_limit_minutes": 25,
            "difficulty": "",
            "version": draft.version,
        },
    )
    draft.refresh_from_db()

    assert draft.title == "Renamed"
    assert draft.slug == "draft-parts"
