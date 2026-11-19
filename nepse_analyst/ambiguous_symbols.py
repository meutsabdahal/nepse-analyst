"""Listed symbols that are also ordinary words or names.

A mention of one of these counts as the company only when the text backs it
up: the phrase from the company's name that tells it apart, or market context
right next to the symbol ("API shares", "shares of API"). Used by the query
router and by news tagging.
"""

from __future__ import annotations

import re

# Symbol -> distinguishing name phrase, or None when the listed name is the
# ordinary meaning itself and only market context can back it up.
AMBIGUOUS_SYMBOLS: dict[str, str | None] = {
    "API": "api power",  # Api Power Company; otherwise a software API ("NEPSE API")
    "SEBON": None,  # listed as "Securities Board of Nepal", which is the regulator
}

_CONTEXT_AFTER = re.compile(r"(?:'s)?\s+(?:shares?|stocks?|scrip|ltp)\b", re.IGNORECASE)
_CONTEXT_BEFORE = re.compile(r"\b(?:shares?|stocks?|scrip)\s+(?:of\s+)?$", re.IGNORECASE)


def name_phrase(symbol: str) -> re.Pattern[str] | None:
    """Pattern for the name phrase that backs up an ambiguous symbol, if it has one."""
    phrase = AMBIGUOUS_SYMBOLS.get(symbol)
    return re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE) if phrase else None


def mention_counts(symbol: str, text: str, start: int, end: int) -> bool:
    """Whether the symbol found at ``text[start:end]`` refers to the company."""
    if symbol not in AMBIGUOUS_SYMBOLS:
        return True
    phrase = name_phrase(symbol)
    if phrase and phrase.search(text):
        return True
    return bool(_CONTEXT_AFTER.match(text, end) or _CONTEXT_BEFORE.search(text[:start]))
