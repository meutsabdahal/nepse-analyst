"""Company/sector tags on news documents, shared by indexing and retrieval.

ChromaDB 0.5 metadata values must be scalars, so an article tagged with
several companies stores one boolean key per tag (``sym_NABIL: True``,
``sec_commercial_banks: True``) plus comma-joined ``symbols``/``sectors``
strings for display. The retriever filters on the boolean keys.
"""

from __future__ import annotations

import re

TAG_SEPARATOR = ", "


def symbol_key(symbol: str) -> str:
    return f"sym_{symbol.strip().upper()}"


def sector_key(sector: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", sector.strip().lower()).strip("_")
    return f"sec_{slug}"


def tag_metadata(symbols: list[str], sectors: list[str]) -> dict[str, str | bool]:
    meta: dict[str, str | bool] = {
        "symbol": symbols[0] if symbols else "",
        "sector": sectors[0] if sectors else "",
        "symbols": TAG_SEPARATOR.join(symbols),
        "sectors": TAG_SEPARATOR.join(sectors),
    }
    meta.update({symbol_key(s): True for s in symbols})
    meta.update({sector_key(s): True for s in sectors})
    return meta


def split_tags(value: str | None) -> list[str]:
    return [s for t in (value or "").split(TAG_SEPARATOR.strip()) if (s := t.strip())]
