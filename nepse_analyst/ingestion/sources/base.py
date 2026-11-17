"""Source interfaces. Swap any implementation without touching the loader.

Each source may optionally define ``close()``; the loader calls it when done.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nepse_analyst.ingestion.records import (
    Company,
    Dividend,
    Fundamental,
    IndexBar,
    IPOIssue,
    NewsArticle,
    PriceBar,
)


@runtime_checkable
class CompanySource(Protocol):
    name: str

    def fetch_companies(self) -> list[Company]: ...


@runtime_checkable
class PriceSource(Protocol):
    """Daily OHLCV for listed symbols plus NEPSE / sub-index history."""

    name: str

    def available(self) -> bool:
        """Cheap preflight probe. False means the loader should not rely on it."""
        ...

    def fetch_price_history(self, symbol: str) -> list[PriceBar]: ...

    def fetch_index_history(self) -> list[IndexBar]: ...


@runtime_checkable
class FundamentalsSource(Protocol):
    name: str

    def fetch_fundamentals(
        self, symbol: str
    ) -> tuple[list[Fundamental], list[Dividend]]: ...


@runtime_checkable
class IPOSource(Protocol):
    name: str

    def fetch_ipos(self) -> list[IPOIssue]: ...


@runtime_checkable
class NewsSource(Protocol):
    name: str

    def fetch_news(self, limit: int | None = None) -> list[NewsArticle]: ...
