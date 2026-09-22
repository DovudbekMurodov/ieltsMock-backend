"""Normalisation and band-conversion rules, exercised against the real content."""

from decimal import Decimal

import pytest

from apps.grading.bands import estimate, round_to_half_band, scale_raw
from apps.grading.normalize import normalize

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "submitted,expected",
    [
        ("two-thirds", "two-thirds"),
        ("  Two-Thirds  ", "two-thirds"),  # padding and case
        ("TWO-THIRDS", "two-thirds"),
        ("two–thirds", "two-thirds"),  # en dash typed instead of hyphen
        ("two  thirds", "two thirds"),  # doubled inner space collapses
        ("twilight zone’s", "twilight zone's"),  # curly apostrophe
        ("twilight zone's", "twilight zone's"),
        ("£4.50", "4.50"),  # currency symbol is edge punctuation
        ("4.50.", "4.50"),  # trailing full stop
        ("NOT GIVEN", "not given"),
        ("", ""),
        (None, ""),
        ("   ", ""),
    ],
)
def test_normalisation_folds_transport_noise(submitted, expected):
    assert normalize(submitted) == expected


def test_normalisation_keeps_articles_unless_asked():
    assert normalize("the bicycle") == "the bicycle"
    assert normalize("the bicycle", strip_articles=True) == "bicycle"
    # A single-word answer that happens to be an article is left alone.
    assert normalize("the", strip_articles=True) == "the"


@pytest.mark.parametrize("plural", ["nets", "boxes", "libraries"])
def test_plural_tolerance_is_off_by_default(plural):
    """Real IELTS marks a singular/plural mismatch wrong.

    The source data contains a bare "net" as an accepted answer, so accepting
    "nets" would both overstate scores and teach the wrong habit. Adding an
    explicit accepted answer in the dashboard is the supported route.
    """
    assert normalize(plural) == plural


@pytest.mark.parametrize(
    "plural,singular", [("nets", "net"), ("boxes", "box"), ("libraries", "library")]
)
def test_plural_tolerance_works_when_a_group_opts_in(plural, singular):
    assert normalize(plural, plural_variants=True) == singular


@pytest.mark.parametrize("unchanged", ["glass", "campus", "analysis"])
def test_singularising_leaves_words_that_merely_end_in_s(unchanged):
    assert normalize(unchanged, plural_variants=True) == unchanged


# --- band conversion -----------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [(6.0, "6.0"), (6.24, "6.0"), (6.25, "6.5"), (6.74, "6.5"), (6.75, "7.0"), (0, "0.0")],
)
def test_bands_round_to_halves(value, expected):
    assert str(round_to_half_band(value)) == expected


@pytest.mark.parametrize(
    "raw,total,expected", [(12, 12, 40), (6, 12, 20), (0, 12, 0), (10, 10, 40), (5, 10, 20)]
)
def test_raw_scores_scale_onto_the_published_total(raw, total, expected):
    assert scale_raw(raw, total) == expected


def test_scale_raw_handles_an_empty_test():
    assert scale_raw(0, 0) == 0


@pytest.mark.parametrize(
    "scaled,band",
    [(40, "9.0"), (39, "9.0"), (38, "8.5"), (30, "7.0"), (29, "6.5"), (23, "6.0"), (0, "0.0")],
)
def test_reading_scale_boundaries(seeded_content, scaled, band):
    from apps.grading.bands import default_scale

    assert str(default_scale("reading").lookup(scaled)) == band


@pytest.mark.parametrize("scaled,band", [(40, "9.0"), (32, "7.5"), (30, "7.0"), (18, "5.5")])
def test_listening_scale_differs_from_reading(seeded_content, scaled, band):
    from apps.grading.bands import default_scale

    assert str(default_scale("listening").lookup(scaled)) == band


def test_short_tests_report_low_confidence_and_a_range(seeded_content):
    from apps.grading.bands import default_scale

    result = estimate(9, 12, default_scale("reading"))

    assert result.confidence == "low"
    assert result.is_estimate
    assert result.band_low < result.band_high
    # One question either way moves the reported band by more than a full band
    # on a 12-question test, which is exactly why a range is reported.
    assert result.band_high - result.band_low >= Decimal("1.0")


def test_a_full_length_test_reports_a_single_band(seeded_content):
    from apps.grading.bands import default_scale

    result = estimate(30, 40, default_scale("reading"))

    assert result.confidence == "high"
    assert not result.is_estimate
    assert result.band == result.band_low == result.band_high


def test_every_current_test_is_too_short_for_a_confident_band(seeded_content):
    from apps.content.models import Test
    from apps.grading.bands import default_scale

    for test in Test.objects.all():
        scale = default_scale(test.skill)
        result = estimate(test.question_count, test.question_count, scale)
        assert result.confidence == "low", f"{test.slug} unexpectedly reports high confidence"
