import re

import pytest
from django.urls import reverse

from apps.content.models import AnswerKey, Test
from apps.vocabulary.models import VocabularySection

pytestmark = pytest.mark.django_db


# --- the one that matters most -------------------------------------------------


def published_tests():
    return list(Test.objects.filter(published_payload__isnull=False).order_by("slug"))


ANSWER_BEARING_KEYS = {
    "answer",
    "answers",
    "answerkey",
    "answerkeys",
    "acceptedanswers",
    "correct",
    "iscorrect",
    "correctoption",
    "correctoptionid",
    "explanation",
    "value",
}

# Exact allowlists rather than a denylist: a field added to the public payload
# has to be added here deliberately, so nothing new slips out unnoticed.
QUESTION_KEYS = {"id", "number", "type", "prompt", "options"}
OPTION_KEYS = {"id", "label", "text"}


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def test_public_payloads_contain_no_answer_bearing_keys(seeded_content):
    """The correct answer must not be recoverable from a delivery payload.

    An MCQ's correct option text legitimately appears -- it is one of the four
    choices. What must never appear is anything marking which one it is.
    """
    offenders = []
    for test in published_tests():
        for key in walk_keys(test.published_payload):
            if key.lower().replace("_", "") in ANSWER_BEARING_KEYS:
                offenders.append(f"{test.slug}: {key!r}")

    assert not offenders, "answer-bearing keys in public payloads:\n" + "\n".join(offenders)


def test_public_question_and_option_fields_match_the_allowlist(seeded_content):
    for test in published_tests():
        for section in test.published_payload["sections"]:
            for group in section["groups"]:
                for option in group.get("options", []):
                    assert set(option) <= OPTION_KEYS, f"{test.slug}: {set(option) - OPTION_KEYS}"
                for question in group["questions"]:
                    extra = set(question) - QUESTION_KEYS
                    assert not extra, f"{test.slug} q{question['number']}: {extra}"
                    for option in question.get("options", []):
                        assert set(option) <= OPTION_KEYS


def test_gap_and_tfng_answers_are_absent_from_their_question_text(seeded_content):
    """These types carry no options, so their answers have nowhere legitimate to be.

    Matched on word boundaries against the prompt only. Comparing against a JSON
    dump instead would false-positive on single-digit answers, which collide
    with the id and number fields.
    """
    prompts = {}
    for test in published_tests():
        for section in test.published_payload["sections"]:
            for group in section["groups"]:
                if group["type"] not in {"gap", "tfng"}:
                    continue
                for question in group["questions"]:
                    assert "options" not in question
                    prompts[(test.slug, question["number"])] = question["prompt"]

    leaks = []
    for key in AnswerKey.objects.select_related("question__test", "question__group"):
        if key.question.group.type not in {"gap", "tfng"}:
            continue
        prompt = prompts.get((key.question.test.slug, key.question.number))
        if prompt and re.search(rf"\b{re.escape(key.value)}\b", prompt, re.IGNORECASE):
            leaks.append(
                f"{key.question.test.slug} q{key.question.number}: "
                f"{key.value!r} appears in its own prompt"
            )

    assert not leaks, "answers visible in their own prompt:\n" + "\n".join(leaks)


def test_the_number_of_options_does_not_reveal_the_answer(seeded_content):
    """Every MCQ offers four options; a short list would narrow the answer down."""
    for test in published_tests():
        for section in test.published_payload["sections"]:
            for group in section["groups"]:
                if group["type"] == "mcq":
                    assert all(len(q["options"]) == 4 for q in group["questions"])
                if group["type"] == "matching":
                    assert len(group["options"]) == 6


# --- payload shape -------------------------------------------------------------


def test_detail_payload_shape(seeded_content, client):
    response = client.get(reverse("api:test-detail", args=["twilight-zone"]))
    payload = response.json()

    assert response.status_code == 200
    assert payload["id"] == "twilight-zone"
    assert payload["skill"] == "reading"
    assert payload["timeLimitMinutes"] == 20
    assert payload["questionCount"] == 12

    section = payload["sections"][0]
    assert len(section["blocks"]) == 6
    assert section["blocks"][0]["label"] == "A"

    types = [g["type"] for g in section["groups"]]
    assert types == ["tfng", "mcq", "gap", "matching"]

    tfng, mcq, gap, matching = section["groups"]
    assert all("options" not in q for q in tfng["questions"])
    assert all(len(q["options"]) == 4 for q in mcq["questions"])
    assert all("options" not in q for q in gap["questions"])
    # The shared heading pool lives on the group, not repeated per question.
    assert len(matching["options"]) == 6
    assert all("options" not in q for q in matching["questions"])


def test_listening_payload_uses_speaker_labels(seeded_content, client):
    response = client.get(reverse("api:test-detail", args=["booking-campsite"]))
    block = response.json()["sections"][0]["blocks"][0]

    assert "speaker" in block
    assert "label" not in block


def test_list_filters_by_skill(seeded_content, client):
    reading = client.get(reverse("api:test-list"), {"skill": "reading"}).json()
    listening = client.get(reverse("api:test-list"), {"skill": "listening"}).json()

    assert reading["count"] == 6
    assert listening["count"] == 5
    assert {r["skill"] for r in reading["results"]} == {"reading"}


def test_list_rejects_an_unknown_skill(seeded_content, client):
    assert client.get(reverse("api:test-list"), {"skill": "telepathy"}).status_code == 400


def test_unpublished_test_is_not_served(seeded_content, client):
    test = Test.objects.get(slug="silk-road-revival")
    Test.objects.filter(pk=test.pk).update(status="draft")
    try:
        response = client.get(reverse("api:test-detail", args=["silk-road-revival"]))
        assert response.status_code == 404
    finally:
        Test.objects.filter(pk=test.pk).update(status="published")


# --- other content types -------------------------------------------------------


def test_vocabulary_payload_pre_parses_bold_markers(seeded_content, client):
    payload = client.get(reverse("api:vocabulary-detail", args=["academic-writing"])).json()
    word = payload["words"][0]

    assert payload["wordCount"] == len(payload["words"])
    assert "**" in word["example"]
    assert sum(1 for part in word["exampleParts"] if part["bold"]) == 1
    assert "".join(p["text"] for p in word["exampleParts"]) == word["example"].replace("**", "")


def test_writing_detail_preserves_paragraph_breaks(seeded_content, client):
    payload = client.get(reverse("api:writing-detail", args=["remote-work"])).json()
    answer = payload["modelAnswers"][0]

    assert "\n\n" in answer["body"]
    assert answer["paragraphs"] == answer["body"].split("\n\n")


def test_writing_list_withholds_model_answers(seeded_content, client):
    payload = client.get(reverse("api:writing-list")).json()

    assert payload["count"] == 5
    assert all("modelAnswers" not in task for task in payload["results"])


def test_speaking_payload_shape(seeded_content, client):
    payload = client.get(reverse("api:speaking-detail", args=["hometown"])).json()

    assert len(payload["part1"]) == 5
    assert len(payload["part3"]) == 4
    assert len(payload["phrases"]) == 5
    assert len(payload["part2"]["bullets"]) == 4
    assert payload["part2"]["prepSeconds"] == 60
    assert payload["part2"]["speakSeconds"] == 120


# --- caching -------------------------------------------------------------------


def test_conditional_get_returns_304_with_no_body(seeded_content, client):
    url = reverse("api:test-detail", args=["twilight-zone"])
    first = client.get(url)
    second = client.get(url, HTTP_IF_NONE_MATCH=first["ETag"])

    assert first.status_code == 200
    assert second.status_code == 304
    assert second.content == b""


def test_public_endpoints_are_shared_cacheable(seeded_content, client):
    response = client.get(reverse("api:test-detail", args=["twilight-zone"]))

    assert "public" in response["Cache-Control"]
    assert "stale-while-revalidate" in response["Cache-Control"]
    # A shared cache must not reuse one origin's CORS headers for another.
    assert "Origin" in response["Vary"]


def test_non_public_responses_default_to_no_store(seeded_content, client):
    response = client.get("/healthz")

    assert "no-store" in response["Cache-Control"] or "no-cache" in response["Cache-Control"]


def test_etag_changes_when_content_changes(seeded_content, client):
    from apps.content.publishing import publish_test

    url = reverse("api:test-detail", args=["urban-heat-islands"])
    before = client.get(url)["ETag"]

    test = Test.objects.get(slug="urban-heat-islands")
    original = test.title
    test.title = "Urban Heat Islands (revised)"
    test.save(update_fields=["title"])
    publish_test(test)
    try:
        assert client.get(url)["ETag"] != before
    finally:
        test.title = original
        test.save(update_fields=["title"])
        publish_test(test)


def test_republishing_unchanged_content_keeps_the_same_etag(seeded_content):
    from apps.content.publishing import publish_test

    test = Test.objects.get(slug="museum-tour")
    before = test.payload_etag
    publish_test(test)

    assert test.payload_etag == before


# --- query budget --------------------------------------------------------------


def test_detail_costs_one_metadata_query_plus_one_payload_query(
    seeded_content, client, django_assert_num_queries
):
    # Deliberately not folded into one query: fetching the payload during the
    # conditional check would load the body on every 304, which is the cost a
    # 304 exists to avoid.
    with django_assert_num_queries(2):
        client.get(reverse("api:test-detail", args=["twilight-zone"]))


def test_a_304_never_loads_the_payload(seeded_content, client, django_assert_num_queries):
    url = reverse("api:test-detail", args=["twilight-zone"])
    etag = client.get(url)["ETag"]

    with django_assert_num_queries(1):
        response = client.get(url, HTTP_IF_NONE_MATCH=etag)

    assert response.status_code == 304


def test_list_does_not_scale_with_question_count(seeded_content, client, django_assert_num_queries):
    # Two queries regardless of how many tests or questions exist.
    with django_assert_num_queries(2):
        client.get(reverse("api:test-list"))


def test_vocabulary_detail_has_the_same_query_budget(
    seeded_content, client, django_assert_num_queries
):
    with django_assert_num_queries(2):
        client.get(reverse("api:vocabulary-detail", args=["everyday-speaking"]))


def test_vocabulary_sections_are_all_published(seeded_content):
    assert VocabularySection.objects.filter(published_payload__isnull=True).count() == 0
