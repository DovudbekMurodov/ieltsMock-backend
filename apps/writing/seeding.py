from django.db import transaction

from apps.common.models import PublishStatus

from .models import WritingModelAnswer, WritingTask, WritingTaskType

# The source stores the human label; map it back onto the stored enum value.
TYPE_BY_LABEL = {label: value for value, label in WritingTaskType.choices}


class UnknownWritingType(RuntimeError):
    pass


@transaction.atomic
def seed_task(raw: dict) -> WritingTask:
    try:
        task_type = TYPE_BY_LABEL[raw["type"]]
    except KeyError as exc:
        raise UnknownWritingType(
            f"{raw['id']}: unrecognised writing task type {raw['type']!r}. "
            f"Known types: {', '.join(sorted(TYPE_BY_LABEL))}"
        ) from exc

    task, _ = WritingTask.objects.update_or_create(
        slug=raw["id"],
        defaults={
            "task_number": 2,
            "type": task_type,
            "prompt": raw["prompt"],
            "suggested_time_minutes": raw["suggestedTimeMinutes"],
            "target_words": raw["targetWords"],
            "status": PublishStatus.PUBLISHED,
        },
    )
    task.model_answers.all().delete()
    # Stored verbatim: the blank-line paragraph breaks are load-bearing.
    WritingModelAnswer.objects.create(task=task, body=raw["modelAnswer"], order=1)
    return task
