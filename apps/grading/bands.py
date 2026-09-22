"""Raw score to band, with an honest account of the uncertainty.

Current tests carry 10-12 questions while the published scales are defined
over 40. Scaling up means each raw question is worth 3.3 points, and near the
middle of the reading curve one raw point is often half a band -- so a single
wrong answer can move the reported band by about 1.5. Reporting "6.5" from a
12-question test would be noise with a decimal point on it.

So a low-confidence attempt reports a range, and the point estimate is kept
only for internal trending.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import BandScale

OFFICIAL_TOTAL = 40


@dataclass
class BandEstimate:
    band: Decimal | None
    band_low: Decimal | None
    band_high: Decimal | None
    confidence: str  # "high" | "low"
    scaled_raw: int
    scale_id: int | None

    @property
    def is_estimate(self) -> bool:
        return self.confidence == "low"


def round_to_half_band(value) -> Decimal:
    """IELTS bands move in halves."""
    doubled = (Decimal(value) * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (doubled / 2).quantize(Decimal("0.1"))


def default_scale(skill) -> BandScale | None:
    return BandScale.objects.filter(skill=skill, is_default=True).first()


def scale_raw(raw_score: int, raw_total: int, scale_total: int = OFFICIAL_TOTAL) -> int:
    if raw_total <= 0:
        return 0
    return round(raw_score / raw_total * scale_total)


def estimate(raw_score: int, raw_total: int, scale: BandScale | None) -> BandEstimate:
    if scale is None:
        return BandEstimate(None, None, None, "low", 0, None)

    scaled = scale_raw(raw_score, raw_total, scale.raw_total)
    band = scale.lookup(scaled)

    confident = raw_total >= scale.min_questions_for_confidence
    if confident:
        return BandEstimate(band, band, band, "high", scaled, scale.id)

    # One raw question either way, expressed on the published scale.
    low = scale.lookup(scale_raw(max(raw_score - 1, 0), raw_total, scale.raw_total))
    high = scale.lookup(scale_raw(min(raw_score + 1, raw_total), raw_total, scale.raw_total))
    return BandEstimate(band, low, high, "low", scaled, scale.id)


def payload(estimate_: BandEstimate) -> dict:
    """The shape the API returns. Raw numbers always accompany the band."""
    return {
        "band": str(estimate_.band) if estimate_.band is not None else None,
        "bandRange": (
            [str(estimate_.band_low), str(estimate_.band_high)]
            if estimate_.band_low is not None and estimate_.band_high is not None
            else None
        ),
        "bandConfidence": estimate_.confidence,
        "bandIsEstimate": estimate_.is_estimate,
        "scaledRaw": estimate_.scaled_raw,
        "scaleTotal": OFFICIAL_TOTAL,
    }
