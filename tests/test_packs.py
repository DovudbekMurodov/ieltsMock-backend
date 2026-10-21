import pytest
from django.urls import reverse

from apps.content.models import Pack, Test
from apps.speaking.models import SpeakingTopic
from apps.writing.models import WritingTask

pytestmark = pytest.mark.django_db


def results(client, name, **params):
    response = client.get(reverse(f"api:{name}"), params)
    assert response.status_code == 200
    return response.json()["results"]


def test_list_items_carry_their_pack_and_follow_pack_order(seeded_content, client):
    first, second = Test.objects.filter(skill="reading").order_by("slug")[:2]
    early = Pack.objects.create(slug="volume-1", skill="reading", title="Volume 1", order=0)
    # The second test goes first in its pack, so the list must not fall back to title order.
    for test, position in ((first, 2), (second, 1)):
        test.pack, test.pack_position, test.pack_label = early, position, f"Test {position}"
        test.save()

    items = results(client, "test-list", skill="reading")
    packed = [item for item in items if item["pack"]]

    assert [item["id"] for item in packed] == [second.slug, first.slug]
    assert packed[0]["pack"] == {
        "id": "volume-1",
        "title": "Volume 1",
        "description": "",
        "order": 0,
    }
    assert packed[0]["packPosition"] == 1
    assert packed[0]["packLabel"] == "Test 1"


def test_content_outside_a_pack_says_so(seeded_content, client):
    item = results(client, "test-list", skill="listening")[0]

    assert item["pack"] is None
    assert item["packPosition"] is None
    assert item["packLabel"] == ""


def test_writing_and_speaking_lists_carry_packs(seeded_content, client):
    task = WritingTask.objects.first()
    topic = SpeakingTopic.objects.first()
    writing = Pack.objects.create(slug="w-1", skill="writing", title="Writing 1")
    speaking = Pack.objects.create(slug="s-1", skill="speaking", title="Speaking 1")
    WritingTask.objects.filter(pk=task.pk).update(
        pack=writing, pack_position=1, pack_label="Test 1"
    )
    SpeakingTopic.objects.filter(pk=topic.pk).update(
        pack=speaking, pack_position=1, pack_label="Test 1"
    )

    written = {item["id"]: item for item in results(client, "writing-list")}
    spoken = {item["id"]: item for item in results(client, "speaking-list")}

    assert written[task.slug]["pack"]["id"] == "w-1"
    assert spoken[topic.slug]["pack"]["id"] == "s-1"
