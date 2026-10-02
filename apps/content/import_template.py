"""The document an author hands to an AI, and the brief that goes with it.

Kept in Python rather than as a static file so the two can never disagree with
the importer that reads them — the rules written here are the rules
`importing.validate` enforces, and both live one import away from each other.
"""

import json

# Deliberately small. A template long enough to show every option is a template
# nobody reads to the end of; this shows one of each question type and leaves
# the rest to the brief below.
TEMPLATE = {
    "title": "The History of Coffee",
    "skill": "reading",
    "timeLimitMinutes": 20,
    "difficulty": "medium",
    "description": "A short academic passage with mixed question types.",
    "passage": {
        "title": "The History of Coffee",
        "paragraphs": [
            {"label": "A", "text": "Replace this with the first paragraph of the passage."},
            {"label": "B", "text": "Replace this with the second paragraph."},
        ],
    },
    "groups": [
        {
            "heading": "",
            "instructions": (
                "Do the following statements agree with the information in the passage?"
            ),
            "questions": [
                {
                    "number": 1,
                    "type": "tfng",
                    "prompt": "Coffee was first cultivated in Ethiopia.",
                    "answer": "TRUE",
                    "explanation": "Optional. Shown to the candidate after they submit.",
                }
            ],
        },
        {
            "heading": "",
            "instructions": "Choose the correct letter.",
            "questions": [
                {
                    "number": 2,
                    "type": "mcq",
                    "prompt": "According to the passage, coffee spread to Europe mainly through:",
                    "options": ["Venetian traders", "Portuguese sailors", "Ottoman expansion"],
                    "answer": "Ottoman expansion",
                }
            ],
        },
        {
            "heading": "Coffee in the 17th century\nKey dates",
            "instructions": "Write NO MORE THAN TWO WORDS for each answer.",
            "questions": [
                {
                    "number": 3,
                    "type": "gap",
                    "prompt": "The first London coffee house opened in ______.",
                    "acceptedAnswers": ["1652", "sixteen fifty-two"],
                }
            ],
        },
        {
            "heading": "",
            "instructions": "Choose the correct heading for each paragraph.",
            "questions": [
                {
                    "number": 4,
                    "type": "matching",
                    "prompt": "Which heading best fits paragraph A?",
                    "options": [
                        "The origins of the plant",
                        "Coffee reaches the West",
                        "Modern production",
                    ],
                    "answer": "The origins of the plant",
                }
            ],
        },
    ],
}


BRIEF = """\
# Filling in an IELTS test for PrepPath

Give this file and these notes to the model, ask it to return the same JSON
with the content replaced, then import the result. Nothing is published by the
import — the test lands as a draft for you to read first.

## The shape

One JSON object describes one test.

| Key | Required | Notes |
|---|---|---|
| `title` | yes | What the candidate sees in the test list. |
| `skill` | yes | `"reading"` or `"listening"`. |
| `timeLimitMinutes` | yes | A whole number. |
| `difficulty` | no | `"easy"`, `"medium"` or `"hard"`. |
| `description` | no | One line, shown on the card. |
| `slug` | no | **Leave it out.** The URL is generated from the title and made unique. |
| `passage` | reading | `{ "title": …, "paragraphs": [ { "label": "A", "text": … } ] }` |
| `transcript` | listening | `{ "title": …, "lines": [ { "speaker": "Guide", "text": … } ] }` |
| `groups` | yes | See below. |

A listening test may use the reading spelling and a reading test the listening
one; both are read. Write whichever is natural.

## Groups

A group is one numbered instruction block — the thing IELTS prints as
"Questions 1-6". It carries two pieces of text of its own:

- `heading` — the title of what is being completed, e.g. `"The Globe"`. Shown
  once above the group. Use `\\n` for a second line.
- `instructions` — the rubric, e.g. `"Write NO MORE THAN TWO WORDS."`

Every question in a group must be the same `type`.

If you have no headings or rubrics to set, you can skip `groups` entirely and
put a flat `"questions": [...]` list at the top level. Consecutive questions of
the same type are grouped automatically.

## Question types

**`tfng`** — `prompt`, and `answer` as exactly `"TRUE"`, `"FALSE"` or
`"NOT GIVEN"`.

**`mcq`** — `prompt`, `options` (two or more strings), and `answer` repeating
one of those strings **exactly**.

**`gap`** — `prompt` with `______` where the blank falls, and `acceptedAnswers`
listing every spelling to accept. Matching folds case, spacing and punctuation,
so `"ninety"` and `"90"` are two entries but `"Ninety"` is not needed.

**`matching`** — `prompt`, `options` (the shared pool), and `answer` repeating
one of them exactly. **Every matching question in one group must list the
identical `options` array**, because they are drawing from one pool. If two
matching tasks have different pools, put them in separate groups.

`explanation` is optional on any question and is shown after submission.

## Numbering

`number` is what the candidate sees. Number continuously across the whole test,
starting at 1, and do not repeat a number.

## What the import will refuse

Everything wrong with the file is reported at once, each problem naming its
question:

- an `answer` that is not one of the `options`
- a `tfng` answer that is not one of the three allowed strings
- a `gap` question with no `acceptedAnswers`
- two questions sharing a number
- matching questions in one group with different option pools
- an empty prompt or an empty paragraph

A test cannot be published until every question has an accepted answer, so a
draft that is missing some is fine to import and finish by hand.
"""


def template_json() -> str:
    return json.dumps(TEMPLATE, indent=2, ensure_ascii=False)
