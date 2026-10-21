import io
import json

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.content.models import Test
from apps.speaking.models import SpeakingTopic
from apps.writing.models import WritingTask

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, db):
    client.force_login(
        User.objects.create_user(email="papers@example.com", password="pw-test-1234", is_staff=True)
    )
    return client


def preview(client, kind, key, **params):
    return client.get(reverse("dashboard:paper-preview", args=[kind, key]), params)


def export(client, kind, key, **params):
    return client.get(reverse("dashboard:paper-export", args=[kind, key]), params)


def a_test(skill):
    return Test.objects.filter(skill=skill).order_by("slug").first()


def test_the_paper_is_staff_only(seeded_content, client, user):
    test = a_test("reading")
    client.force_login(user)

    assert preview(client, "test", test.pk).status_code == 404
    assert export(client, "test", test.pk, format="pdf").status_code == 404


def test_the_preview_shows_every_question_and_the_answer_key(seeded_content, staff_client):
    test = a_test("reading")
    page = preview(staff_client, "test", test.pk).content.decode()

    assert "READING PASSAGE 1" in page
    assert "ANSWER KEY" in page
    for question in test.questions.all():
        assert f'<b class="n">{question.number}</b>' in page


def test_unticking_the_answer_key_leaves_it_out(seeded_content, staff_client):
    test = a_test("reading")
    page = preview(staff_client, "test", test.pk, format="pdf").content.decode()

    assert "ANSWER KEY" not in page


@pytest.mark.parametrize("skill", ["reading", "listening"])
def test_pdf_and_word_are_real_files(seeded_content, staff_client, skill):
    test = a_test(skill)

    pdf = export(staff_client, "test", test.pk, format="pdf", answers="1", transcript="1")
    docx = export(staff_client, "test", test.pk, format="docx", answers="1", transcript="1")

    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert docx.content.startswith(b"PK")  # a zip, which is what .docx is
    assert "attachment" in docx["Content-Disposition"]


def test_word_carries_the_questions_and_the_key(seeded_content, staff_client):
    from docx import Document

    test = a_test("listening")
    body = export(staff_client, "test", test.pk, format="docx", answers="1").content
    text = "\n".join(p.text for p in Document(io.BytesIO(body)).paragraphs)

    assert "PART 1" in text
    assert "ANSWER KEY" in text
    first = test.questions.order_by("number").first()
    assert first.prompt.split("______")[0].strip()[:20] in text


def test_json_hides_answers_unless_asked(seeded_content, staff_client):
    test = a_test("reading")

    without = json.loads(export(staff_client, "test", test.pk, format="json").content)
    with_answers = json.loads(
        export(staff_client, "test", test.pk, format="json", answers="1").content
    )

    first = lambda data: data["sections"][0]["groups"][0]["questions"][0]  # noqa: E731
    assert "answers" not in first(without)
    assert first(with_answers)["answers"]


def test_writing_and_speaking_export(seeded_content, staff_client):
    task = WritingTask.objects.first()
    topic = SpeakingTopic.objects.first()

    assert preview(staff_client, "writing", task.slug).status_code == 200
    assert export(staff_client, "writing", task.slug, format="pdf").content.startswith(b"%PDF")
    assert preview(staff_client, "speaking", topic.slug).status_code == 200
    assert export(staff_client, "speaking", topic.slug, format="docx").content.startswith(b"PK")


def test_an_unknown_kind_or_format_is_a_404(seeded_content, staff_client):
    test = a_test("reading")

    assert preview(staff_client, "vocabulary", "anything").status_code == 404
    assert export(staff_client, "test", test.pk, format="exe").status_code == 404
