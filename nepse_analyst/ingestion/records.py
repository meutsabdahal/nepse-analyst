"""Normalized records that every ingestion source returns.

Sources know nothing about SQLite or ChromaDB; they only produce these records.
The loader owns all persistence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    symbol: str
    name: str
    sector: str
    listed_shares: int | None = None
    paid_up_value: float | None = None
    total_paid_up: float | None = None
    is_active: int = 1


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    trade_date: str  # ISO yyyy-mm-dd
    close_price: float
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    volume: int | None = None
    turnover: float | None = None


@dataclass(frozen=True)
class IndexBar:
    trade_date: str  # ISO yyyy-mm-dd
    index_name: str  # canonical: NEPSE, Banking, Hydropower
    close_value: float
    open_value: float | None = None
    change_points: float | None = None
    change_percent: float | None = None
    turnover: float | None = None


@dataclass(frozen=True)
class Fundamental:
    symbol: str
    fiscal_year: str  # YYYY/YY (Nepali FY)
    eps: float | None = None
    pe_ratio: float | None = None
    book_value: float | None = None
    roe: float | None = None
    net_profit: float | None = None
    total_assets: float | None = None
    revenue: float | None = None


@dataclass(frozen=True)
class Dividend:
    symbol: str
    fiscal_year: str
    cash_dividend: float | None = None
    bonus_shares: float | None = None
    book_close_date: str | None = None
    announced_date: str | None = None


@dataclass(frozen=True)
class IPOIssue:
    company_name: str
    symbol: str | None = None
    issue_date: str | None = None
    listing_date: str | None = None
    issue_price: float | None = None
    shares_issued: int | None = None
    total_applicants: int | None = None
    allotment_per_person: int | None = None
    oversubscription_rate: float | None = None


@dataclass(frozen=True)
class NewsArticle:
    url: str
    source: str
    title: str
    content: str
    published_at: str = ""  # ISO yyyy-mm-dd or ""
    language: str = "unknown"
