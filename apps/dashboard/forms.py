from django import forms

from apps.content.models import AnswerKey, Option, Question, QuestionGroup, Section, Test
from apps.content.slugs import unique_slug
from apps.speaking.models import SpeakingCueCard, SpeakingItem, SpeakingTopic
from apps.vocabulary.models import VocabularySection, VocabularyWord
from apps.writing.models import WritingModelAnswer, WritingTask

TEXT_INPUT = {"class": "input"}
TEXTAREA = {"class": "input", "rows": 3}


class TestForm(forms.ModelForm):
    """No slug field: the URL is made from the title and never typed.

    Inventing a unique URL by hand for every test is a chore with nothing at
    the end of it, and getting it wrong is a "test with this slug already
    exists" error on the one field the author cared least about.

    An existing slug is left alone when a test is edited. It is the public URL,
    so renaming a test must not break the links to it.
    """

    def save(self, commit=True):
        test = super().save(commit=False)
        if not test.slug:
            test.slug = unique_slug(Test, test.title)
        if commit:
            test.save()
            self._save_m2m()
        return test

    class Meta:
        model = Test
        fields = ("title", "skill", "description", "time_limit_minutes", "difficulty")
        widgets = {
            "title": forms.TextInput(attrs=TEXT_INPUT),
            "skill": forms.Select(attrs=TEXT_INPUT),
            "description": forms.Textarea(attrs=TEXTAREA),
            "time_limit_minutes": forms.NumberInput(attrs=TEXT_INPUT),
            "difficulty": forms.Select(attrs=TEXT_INPUT),
        }


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ("title", "instructions", "transcript_visibility", "playback_policy")
        widgets = {
            "title": forms.TextInput(attrs=TEXT_INPUT),
            "instructions": forms.Textarea(attrs=TEXTAREA),
            "transcript_visibility": forms.Select(attrs=TEXT_INPUT),
            "playback_policy": forms.Select(attrs=TEXT_INPUT),
        }


class QuestionGroupForm(forms.ModelForm):
    class Meta:
        model = QuestionGroup
        fields = (
            "type",
            "heading",
            "instructions",
            "allow_article_omission",
            "allow_plural_variants",
        )
        widgets = {
            "type": forms.Select(attrs=TEXT_INPUT),
            "heading": forms.Textarea(attrs={**TEXTAREA, "rows": 2}),
            "instructions": forms.Textarea(attrs={**TEXTAREA, "rows": 2}),
        }


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ("prompt", "explanation")
        widgets = {
            "prompt": forms.Textarea(attrs={**TEXTAREA, "rows": 2}),
            "explanation": forms.Textarea(attrs={**TEXTAREA, "rows": 2}),
        }


class OptionForm(forms.ModelForm):
    class Meta:
        model = Option
        fields = ("label", "text")
        widgets = {
            "label": forms.TextInput(attrs={**TEXT_INPUT, "placeholder": "A"}),
            "text": forms.TextInput(attrs=TEXT_INPUT),
        }


class AnswerKeyForm(forms.ModelForm):
    class Meta:
        model = AnswerKey
        fields = ("value",)
        widgets = {"value": forms.TextInput(attrs=TEXT_INPUT)}


class VocabularySectionForm(forms.ModelForm):
    class Meta:
        model = VocabularySection
        fields = ("title", "slug", "order", "status")
        widgets = {
            "title": forms.TextInput(attrs=TEXT_INPUT),
            "slug": forms.TextInput(attrs=TEXT_INPUT),
            "order": forms.NumberInput(attrs=TEXT_INPUT),
            "status": forms.Select(attrs=TEXT_INPUT),
        }


class VocabularyWordForm(forms.ModelForm):
    class Meta:
        model = VocabularyWord
        fields = ("headword", "pos", "definition", "example")
        widgets = {
            "headword": forms.TextInput(attrs=TEXT_INPUT),
            "pos": forms.Select(attrs=TEXT_INPUT),
            "definition": forms.TextInput(attrs=TEXT_INPUT),
            "example": forms.TextInput(
                attrs={**TEXT_INPUT, "placeholder": "Use **bold** around the word in context"}
            ),
        }


class BulkWordForm(forms.Form):
    """Paste a whole word list at once, one per line.

    Typing a hundred words through four boxes each is the slowest job in the
    dashboard, so the importer takes the same tab-separated shape people
    already keep these lists in.
    """

    text = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "input font-mono text-xs",
                "rows": 10,
                "placeholder": (
                    "One word per line, tab or | separated:\n"
                    "Substantial | adjective | Fairly large in amount. | "
                    "The policy led to a **substantial** drop.\n"
                ),
            }
        )
    )
    replace = forms.BooleanField(required=False)


def parse_words(text: str) -> tuple[list[dict], list[str]]:
    """Return (parsed rows, rejected lines). Never silently drops input."""
    rows, rejected = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # maxsplit=3 so a separator inside the example survives: rejoining the
        # tail would silently rewrite the sentence.
        separator = "\t" if "\t" in line else "|"
        parts = [p.strip() for p in line.split(separator, 3)]
        if len(parts) < 4 or not parts[0]:
            rejected.append(line)
            continue
        headword, pos, definition, example = parts
        if example.count("**") != 2:
            rejected.append(f"{line}   (needs exactly one **bold** span)")
            continue
        rows.append(
            {
                "headword": headword,
                "pos": pos.lower(),
                "definition": definition,
                "example": example.strip(),
            }
        )
    return rows, rejected


class WritingTaskForm(forms.ModelForm):
    class Meta:
        model = WritingTask
        fields = (
            "slug", "task_number", "type", "prompt", "image",
            "suggested_time_minutes", "target_words", "status", "reveal_policy",
        )
        widgets = {
            "slug": forms.TextInput(attrs=TEXT_INPUT),
            "task_number": forms.NumberInput(attrs=TEXT_INPUT),
            "type": forms.Select(attrs=TEXT_INPUT),
            "prompt": forms.Textarea(attrs={**TEXTAREA, "rows": 4}),
            "suggested_time_minutes": forms.NumberInput(attrs=TEXT_INPUT),
            "target_words": forms.NumberInput(attrs=TEXT_INPUT),
            "status": forms.Select(attrs=TEXT_INPUT),
            "reveal_policy": forms.Select(attrs=TEXT_INPUT),
        }


class WritingModelAnswerForm(forms.ModelForm):
    class Meta:
        model = WritingModelAnswer
        fields = ("band", "body")
        widgets = {
            "band": forms.TextInput(attrs={**TEXT_INPUT, "placeholder": "7.5"}),
            # No strip: blank lines between paragraphs are load-bearing.
            "body": forms.Textarea(attrs={"class": "input font-mono text-xs", "rows": 16}),
        }


class SpeakingTopicForm(forms.ModelForm):
    class Meta:
        model = SpeakingTopic
        fields = ("title", "slug", "order", "status")
        widgets = {
            "title": forms.TextInput(attrs=TEXT_INPUT),
            "slug": forms.TextInput(attrs=TEXT_INPUT),
            "order": forms.NumberInput(attrs=TEXT_INPUT),
            "status": forms.Select(attrs=TEXT_INPUT),
        }


class SpeakingCueCardForm(forms.ModelForm):
    class Meta:
        model = SpeakingCueCard
        fields = ("title", "prep_seconds", "speak_seconds")
        widgets = {
            "title": forms.TextInput(attrs=TEXT_INPUT),
            "prep_seconds": forms.NumberInput(attrs=TEXT_INPUT),
            "speak_seconds": forms.NumberInput(attrs=TEXT_INPUT),
        }


class SpeakingItemForm(forms.ModelForm):
    class Meta:
        model = SpeakingItem
        fields = ("text",)
        widgets = {"text": forms.TextInput(attrs=TEXT_INPUT)}
