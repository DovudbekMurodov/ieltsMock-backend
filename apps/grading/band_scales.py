"""Indicative raw-score to band conversions.

These are the widely published approximations, not an official table. Real
conversions shift by a question or so between test papers, and published
sources disagree with one another -- which is exactly why the scale is stored
as editable rows rather than constants. Treat these as a starting point for the
content owner to adjust.

Each list must cover 0..40 contiguously; BandScale.validate_rows() enforces it.
"""

ACADEMIC_READING = [
    (39, 40, "9.0"),
    (37, 38, "8.5"),
    (35, 36, "8.0"),
    (33, 34, "7.5"),
    (30, 32, "7.0"),
    (27, 29, "6.5"),
    (23, 26, "6.0"),
    (19, 22, "5.5"),
    (15, 18, "5.0"),
    (13, 14, "4.5"),
    (10, 12, "4.0"),
    (8, 9, "3.5"),
    (6, 7, "3.0"),
    (4, 5, "2.5"),
    (3, 3, "2.0"),
    (2, 2, "1.5"),
    (1, 1, "1.0"),
    (0, 0, "0.0"),
]

LISTENING = [
    (39, 40, "9.0"),
    (37, 38, "8.5"),
    (35, 36, "8.0"),
    (32, 34, "7.5"),
    (30, 31, "7.0"),
    (26, 29, "6.5"),
    (23, 25, "6.0"),
    (18, 22, "5.5"),
    (16, 17, "5.0"),
    (13, 15, "4.5"),
    (10, 12, "4.0"),
    (8, 9, "3.5"),
    (6, 7, "3.0"),
    (4, 5, "2.5"),
    (3, 3, "2.0"),
    (2, 2, "1.5"),
    (1, 1, "1.0"),
    (0, 0, "0.0"),
]

SCALES = [
    ("Academic Reading (indicative)", "reading", ACADEMIC_READING),
    ("Listening (indicative)", "listening", LISTENING),
]

NOTES = (
    "Indicative conversion, not an official table. Published sources disagree "
    "and real papers shift by about a question. Review before relying on it."
)
