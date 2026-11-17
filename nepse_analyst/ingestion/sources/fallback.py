"""Compose several PriceSources into one, tried in order."""

from __future__ import annotations

from collections import Counter

from nepse_analyst.ingestion.records import IndexBar, PriceBar
from nepse_analyst.ingestion.sources.base import PriceSource


class FallbackPriceSource:
    """Try each source in order; the first non-empty result wins.

    ``available()`` probes every source once and skips the ones that fail,
    so a dead upstream costs one probe instead of one timeout per symbol.
    """

    def __init__(self, sources: list[PriceSource]) -> None:
        if not sources:
            raise ValueError("FallbackPriceSource needs at least one source")
        self.sources = list(sources)
        self.name = " -> ".join(s.name for s in self.sources)
        self._active: list[PriceSource] = list(self.sources)
        self.served_by: Counter[str] = Counter()

    def available(self) -> bool:
        status = {s.name: s.available() for s in self.sources}
        print("Price source preflight: " + ", ".join(f"{k}={v}" for k, v in status.items()))
        self._active = [s for s in self.sources if status[s.name]]
        return bool(self._active)

    def fetch_price_history(self, symbol: str) -> list[PriceBar]:
        errors: list[str] = []
        for source in self._active:
            try:
                bars = source.fetch_price_history(symbol)
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
                continue
            if bars:
                self.served_by[source.name] += 1
                return bars
        detail = f" ({'; '.join(errors)})" if errors else ""
        raise RuntimeError(f"No history rows returned from any available provider{detail}")

    def fetch_index_history(self) -> list[IndexBar]:
        for source in self._active:
            try:
                bars = source.fetch_index_history()
            except Exception as exc:
                print(f"[{source.name}] index history failed: {exc}")
                continue
            if bars:
                print(f"Loaded {len(bars)} index rows from {source.name}.")
                return bars
        return []

    def close(self) -> None:
        for source in self.sources:
            close = getattr(source, "close", None)
            if callable(close):
                close()
