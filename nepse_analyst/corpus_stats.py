"""News corpus stats, recorded on the Chroma collection when the index is built.

``index_news_in_chroma`` stores them in the collection's metadata, so they
travel with the index (and its backup) and cannot drift from it. The
retriever reads them back for the freshness line and the staleness warning,
without sampling articles or loading the embedding model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PREFIX = "corpus_"
_KEYS = ("total_documents", "dated_documents", "earliest_date", "latest_date", "built_at")


def summarize(published_dates: Iterable[str | None], built_at: str | None = None) -> dict:
    """Stats for a corpus from its articles' ``published_at`` values."""
    all_dates = list(published_dates)
    dated = sorted(d for d in all_dates if d and _ISO_DATE.fullmatch(d))
    return {
        "total_documents": len(all_dates),
        "dated_documents": len(dated),
        "earliest_date": dated[0] if dated else "unknown",
        "latest_date": dated[-1] if dated else "unknown",
        "built_at": built_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def to_collection_metadata(stats: dict) -> dict[str, str | int]:
    """Prefixed keys for Chroma collection metadata (scalar values only)."""
    return {_PREFIX + key: stats[key] for key in _KEYS}


def from_collection_metadata(metadata: dict | None) -> dict | None:
    """Stats recorded at build time, or None for an index built before they were recorded."""
    metadata = metadata or {}
    if not all(_PREFIX + key in metadata for key in _KEYS):
        return None
    return {key: metadata[_PREFIX + key] for key in _KEYS}
