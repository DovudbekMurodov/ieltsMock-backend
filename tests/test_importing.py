import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.common.models import PublishStatus
from apps.content.importing import ImportError_, import_test, validate
from apps.content.models import Option, Question, Test

pytestmark = pytest.mark.django_db
User = get_user_model()


def document(**overrides):
    base = {
        "title": "The History of Coffee",
        "skill": "reading",
        "timeLimitMinutes": 20,
        "passage": {
            "title": "The History of Coffee",
            "paragraphs": [{"label": "A", "text": "Coffee began in Ethiopia."}],
        },
        "groups": [
            {
                "heading": "Key dates",
                "instructions": "Write NO MORE THAN TWO WORDS.",
                "questions": [
                    {"number": 1, "type": "gap", "prompt": "Opened in ______.",
                     "acceptedAnswers": ["1652"]},
                ],
            }
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def staff(client):
    client.force_login(
        User.objects.create_user(email="editor@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


# --- what import produces -----------------------------------------------------


def test_an_imported_test_is_a_draft():
    """The whole point: a model wrote this, so a human reads it before it is live."""
    test = import_test(document())

    assert test.status == PublishStatus.DRAFT
    assert test.published_payload in (None, {}, [])


def test_the_group_keeps_its_heading_and_rubric_apart():
    test = import_test(document())
    group = test.sections.get().groups.get()

    assert group.heading == "Key dates"
    assert group.instructions == "Write NO MORE THAN TWO WORDS."


def test_every_question_type_round_trips():
    test = import_test(
        document(
            groups=[
                {"questions": [
                    {"number": 1, "type": "tfng", "prompt": "p", "answer": "true"},
                ]},
                {"questions": [
                    {"number": 2, "type": "mcq", "prompt": "p",
                     "options": ["a", "b"], "answer": "b"},
                ]},
                {"questions": [
                    {"number": 3, "type": "gap", "prompt": "p", "acceptedAnswers": ["x", "y"]},
                ]},
                {"questions": [
                    {"number": 4, "type": "matching", "prompt": "p",
                     "options": ["one", "two"], "answer": "two"},
                    {"number": 5, "type": "matching", "prompt": "q",
                     "options": ["one", "two"], "answer": "one"},
                ]},
            ]
        )
    )

    by_number = {q.number: q for q in Question.objects.filter(test=test)}
    # Case is folded on the way in, so "true" from a model is stored as the
    # string the scorer compares against.
    assert by_number[1].answer_keys.get().value == "TRUE"
    assert by_number[2].answer_keys.get().value == "b"
    assert sorted(k.value for k in by_number[3].answer_keys.all()) == ["x", "y"]
    assert by_number[4].answer_keys.get().value == "two"
    # One shared pool for the matching group, not one pool per question.
    assert Option.objects.filter(group=by_number[4].group, question__isnull=True).count() == 2


def test_a_flat_question_list_is_grouped_by_type():
    """Declaring groups buys headings; not declaring them should still work."""
    test = import_test(
        document(
            groups=None,
            questions=[
                {"number": 1, "type": "tfng", "prompt": "a", "answer": "TRUE"},
                {"number": 2, "type": "tfng", "prompt": "b", "answer": "FALSE"},
                {"number": 3, "type": "gap", "prompt": "c", "acceptedAnswers": ["x"]},
            ],
        )
    )

    groups = test.sections.get().groups.order_by("order")
    assert [g.type for g in groups] == ["tfng", "gap"]
    assert [g.questions.count() for g in groups] == [2, 1]


def test_a_listening_document_may_use_either_spelling():
    """passage/paragraphs/label and transcript/lines/speaker name the same slots."""
    test = import_test(
        document(
            skill="listening",
            passage=None,
            transcript={"title": "Museum tour", "lines": [{"speaker": "Guide", "text": "Hello."}]},
        )
    )

    block = test.sections.get().blocks.get()
    assert block.label == "Guide"
    assert block.text == "Hello."


# --- slugs --------------------------------------------------------------------


def test_the_slug_is_generated_from_the_title():
    test = import_test(document())
    assert test.slug == "the-history-of-coffee"


def test_importing_the_same_document_twice_does_not_collide():
    """The second import is a second test, not an error and not an overwrite.

    A slug in the document is a suggestion. Honouring it verbatim is how a
    re-import silently replaces the first one.
    """
    first = import_test(document(slug="coffee"))
    second = import_test(document(slug="coffee"))

    assert first.slug == "coffee"
    # A random tag rather than a counted one: counting makes the second
    # import's URL depend on how many came before it.
    assert second.slug.startswith("coffee-")
    assert second.slug != first.slug
    assert first.pk != second.pk


def test_a_third_import_keeps_counting():
    for _ in range(5):
        import_test(document(slug="coffee"))

    slugs = list(Test.objects.filter(slug__startswith="coffee").values_list("slug", flat=True))
    assert len(slugs) == 5
    assert len(set(slugs)) == 5, "every import must get its own URL"


def test_a_document_with_no_slug_is_fine():
    test = import_test(document())
    assert test.slug


# --- what it refuses ----------------------------------------------------------


def test_every_problem_is_reported_at_once():
    """One per upload would mean a dozen rounds on a file this size."""
    problems = validate(
        document(
            title="",
            skill="speaking",
            groups=[
                {"questions": [
                    {"number": 1, "type": "mcq", "prompt": "p",
                     "options": ["a", "b"], "answer": "c"},
                    {"number": 1, "type": "tfng", "prompt": "", "answer": "maybe"},
                ]}
            ],
        )
    )

    joined = " | ".join(problems)
    assert "title is required" in joined
    assert "skill must be" in joined
    assert "is not one of its options" in joined
    assert "prompt is empty" in joined
    assert "used twice" in joined


def test_a_matching_group_with_two_pools_is_refused():
    problems = validate(
        document(
            groups=[
                {"questions": [
                    {"number": 1, "type": "matching", "prompt": "a",
                     "options": ["x", "y"], "answer": "x"},
                    {"number": 2, "type": "matching", "prompt": "b",
                     "options": ["p", "q"], "answer": "p"},
                ]}
            ]
        )
    )

    assert any("different option pools" in p for p in problems)


def test_a_gap_question_needs_an_accepted_answer():
    problems = validate(
        document(groups=[{"questions": [{"number": 1, "type": "gap", "prompt": "p"}]}])
    )
    assert any("acceptedAnswers" in p for p in problems)


def test_nothing_is_written_when_the_document_is_rejected():
    before = Test.objects.count()

    with pytest.raises(ImportError_):
        import_test(document(title=""))

    assert Test.objects.count() == before


# --- the dashboard page -------------------------------------------------------


def test_import_requires_staff(client):
    assert client.get(reverse("dashboard:test-import")).status_code in (302, 404)


def test_pasting_a_document_lands_in_the_editor(staff):
    response = staff.post(
        reverse("dashboard:test-import"), {"document": json.dumps(document())}, follow=True
    )

    test = Test.objects.get(slug="the-history-of-coffee")
    assert response.redirect_chain[-1][0] == reverse("dashboard:test-edit", args=[test.pk])
    assert test.status == PublishStatus.DRAFT


def test_uploading_a_file_works_too(staff):
    upload = SimpleUploadedFile(
        "test.json", json.dumps(document()).encode(), content_type="application/json"
    )

    staff.post(reverse("dashboard:test-import"), {"file": upload})

    assert Test.objects.filter(slug="the-history-of-coffee").exists()


def test_broken_json_says_where(staff):
    before = Test.objects.count()

    response = staff.post(reverse("dashboard:test-import"), {"document": '{"title": "x",}'})

    assert Test.objects.count() == before
    assert "line 1" in response.content.decode()


def test_the_template_downloads_as_json(staff):
    response = staff.get(reverse("dashboard:test-import-template"))

    assert response["Content-Type"] == "application/json"
    # The template has to survive its own importer, or it is documentation for
    # a format nothing accepts.
    assert validate(json.loads(response.content)) == []


def test_the_page_shows_the_brief_and_the_template_link(staff):
    """The instructions are rendered from the module the validator lives in,
    so they cannot drift away from the rules they describe."""
    response = staff.get(reverse("dashboard:test-import"))
    body = response.content.decode()

    assert response.status_code == 200
    assert reverse("dashboard:test-import-template") in body
    assert "acceptedAnswers" in body


def test_the_page_renders_no_template_comments(staff):
    """Django's {# #} is single-line only.

    A multi-line one is not a comment at all — it renders as literal text,
    which is how an explanatory note ended up printed at the top of the brief.
    """
    body = staff.get(reverse("dashboard:test-import")).content.decode()

    assert "{#" not in body
    assert "#}" not in body
