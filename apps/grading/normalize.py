"""Answer normalisation -- the only implementation in the system.

The frontend compares answers in four separate places and is free to drift.
Everything here happens once, server-side, so a change to the rules applies
everywhere at once.
"""

import re
import unicodedata

ARTICLES = ("a", "an", "the")

# Written as code points rather than literals: the characters are visually
# identical to the ASCII ones they fold into, which is the whole problem.
APOSTROPHES = dict.fromkeys(
    (0x2018, 0x2019, 0x02BC, 0x2032),  # curly quotes, modifier apostrophe, prime
    "'",
)
DASHES = dict.fromkeys(
    (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212),  # hyphens, dashes, minus
    "-",
)

WHITESPACE = re.compile(r"\s+")
EDGE_PUNCTUATION = re.compile(r"^[^\w\d]+|[^\w\d]+$", re.UNICODE)


def normalize(
    value,
    *,
    fold_case: bool = True,
    collapse_whitespace: bool = True,
    strip_edge_punctuation: bool = True,
    strip_articles: bool = False,
    plural_variants: bool = False,
) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    # NFKC first: without it a curly apostrophe and a typed one differ, and the
    # source content is full of curly apostrophes, en-dashes and currency signs.
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(APOSTROPHES).translate(DASHES)

    if collapse_whitespace:
        text = WHITESPACE.sub(" ", text).strip()
    if fold_case:
        # casefold, not lower: handles cases lower() gets wrong (e.g. "ß").
        text = text.casefold()
    if strip_edge_punctuation:
        text = EDGE_PUNCTUATION.sub("", text)
    if strip_articles:
        words = text.split(" ")
        if len(words) > 1 and words[0] in ARTICLES:
            text = " ".join(words[1:])
    if plural_variants:
        text = singularise(text)

    return text


def singularise(text: str) -> str:
    """Crude English de-pluralisation, used only when a group opts in.

    Off by default on purpose: real IELTS marks a singular/plural mismatch
    wrong, because grammatical form is part of what is being assessed. The
    accepted answers in the source data include bare "net" and the pair
    "twice"/"two", so silently accepting "nets" would both overstate scores and
    teach the wrong habit. Prefer adding an explicit accepted answer, which is
    three seconds of work in the dashboard and leaves an audit trail.
    """
    if len(text) > 3 and text.endswith("ies"):
        return text[:-3] + "y"
    if len(text) > 3 and text.endswith(("ses", "xes", "zes", "ches", "shes")):
        return text[:-2]
    if len(text) > 2 and text.endswith("s") and not text.endswith(("ss", "us", "is")):
        return text[:-1]
    return text


def normalize_for_group(value, group) -> str:
    """Apply the matching rules configured on a question group."""
    from apps.content.enums import MatchMode

    if group.match_mode == MatchMode.EXACT:
        # Still case- and whitespace-insensitive: a user is choosing from a
        # list here, so only transport noise can differ.
        return normalize(value, strip_edge_punctuation=False)

    return normalize(
        value,
        strip_articles=group.allow_article_omission,
        plural_variants=group.allow_plural_variants,
    )
