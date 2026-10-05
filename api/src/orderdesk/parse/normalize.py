"""Text normalisation shared by retrieval and the fuzzy baseline."""

from __future__ import annotations

import re
import unicodedata

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
_AR_MAP = str.maketrans(
    {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": ""}
)
_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Lower-case Latin, unify Arabic letter variants, Arabic-Indic digits to ASCII, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text).translate(ARABIC_DIGITS)
    t = _DIACRITICS.sub("", t).translate(_AR_MAP).lower()
    t = re.sub(r"[^\w\s.]", " ", t)
    return _SPACE.sub(" ", t).strip()


def numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", norm(text))
