from django import forms

from apps.content.models import AnswerKey, Block, Option, Question, QuestionGroup, Section, Test

TEXT_INPUT = {"class": "input"}
TEXTAREA = {"class": "input", "rows": 3}


class TestForm(forms.ModelForm):
    class Meta:
        model = Test
        fields = ("title", "slug", "skill", "description", "time_limit_minutes", "difficulty")
        widgets = {
            "title": forms.TextInput(attrs=TEXT_INPUT),
            "slug": forms.TextInput(attrs=TEXT_INPUT),
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


class BlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = ("label", "text")
        widgets = {
            "label": forms.TextInput(attrs={**TEXT_INPUT, "placeholder": "A / Speaker"}),
            "text": forms.Textarea(attrs={**TEXTAREA, "rows": 4}),
        }


class QuestionGroupForm(forms.ModelForm):
    class Meta:
        model = QuestionGroup
        fields = ("type", "instructions", "allow_article_omission", "allow_plural_variants")
        widgets = {
            "type": forms.Select(attrs=TEXT_INPUT),
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


class BulkBlockForm(forms.Form):
    """Paste a whole passage or transcript at once.

    Entering 6 paragraphs one box at a time is the slowest part of authoring a
    test, so this is the highest-leverage input in the editor.
    """

    text = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "input font-mono text-xs",
                "rows": 12,
                "placeholder": (
                    "Paste a passage: blank lines separate paragraphs, labelled A, B, C...\n\n"
                    "Or a transcript, one line each:\n"
                    "Tutor: Good morning.\n"
                    "Student: Hello."
                ),
            }
        )
    )
    replace = forms.BooleanField(required=False, initial=True)


def parse_blocks(text: str, *, as_transcript: bool) -> list[tuple[str, str]]:
    """Split pasted text into (label, body) pairs."""
    if as_transcript:
        blocks = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            speaker, _, body = line.partition(":")
            if body.strip():
                blocks.append((speaker.strip(), body.strip()))
            else:
                # No colon: treat it as a continuation of the previous speaker.
                if blocks:
                    blocks[-1] = (blocks[-1][0], f"{blocks[-1][1]} {line}")
                else:
                    blocks.append(("", line))
        return blocks

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return [
        (chr(ord("A") + index) if index < 26 else str(index + 1), paragraph)
        for index, paragraph in enumerate(paragraphs)
    ]
