from .models import RevealPolicy


def build_task_payload(task, *, include_model_answers: bool) -> dict:
    data = {
        "id": task.slug,
        "taskNumber": task.task_number,
        "type": task.get_type_display(),
        "typeKey": task.type,
        "prompt": task.prompt,
        "image": task.image.url if task.image else None,
        "suggestedTimeMinutes": task.suggested_time_minutes,
        "targetWords": task.target_words,
        "revealPolicy": task.reveal_policy,
    }
    if include_model_answers:
        data["modelAnswers"] = [
            {
                "id": answer.id,
                "band": str(answer.band) if answer.band is not None else None,
                # Paragraph breaks are significant; never normalise this string.
                "body": answer.body,
                "paragraphs": answer.paragraphs,
            }
            for answer in task.model_answers.order_by("order")
        ]
    return data


def model_answers_visible(task) -> bool:
    return task.reveal_policy == RevealPolicy.ALWAYS
