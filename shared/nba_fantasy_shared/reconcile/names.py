"""Name normalization used for cross-source matching and search.

Verified pairs: "Lonnie Walker IV" == "Lonnie Walker", "Patrick Baldwin Jr." == "Patrick Baldwin",
"Nikola Jokić" == "nikola jokic", "A.J. Lawson" == "aj lawson".
"""

from __future__ import annotations

import re
import unicodedata

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_NON_LETTERS = re.compile(r"[^a-z ]")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_name(text: str | None) -> str:
    if not text:
        return ""
    lowered = strip_accents(text).lower()
    letters = _NON_LETTERS.sub("", lowered)
    without_suffix = _SUFFIXES.sub("", letters)
    return " ".join(without_suffix.split())
