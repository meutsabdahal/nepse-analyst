"""What the data covers, with dates, for the chat's first screen.

Read from the database and the news index on each request, so the page never
promises more than is loaded (it used to offer "recent news" while the news
corpus ended in 2016). A dataset that is missing or empty is left out.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from nepse_analyst.chat_helpers import _age_days
from nepse_analyst.config import NEWS_STALE_DAYS, PRICE_STALE_DAYS
from nepse_analyst.database import get_connection

_FY_ORDER = "CAST(SUBSTR(fiscal_year, 1, 4) AS INT)"


def _item(label: str, detail: str, latest: str | None = None, stale_after: int | None = None,
          today: date | None = None) -> dict[str, Any]:
    """One row: ``stale`` when ``latest`` is more than ``stale_after`` days before today."""
    age = _age_days(latest, today or date.today()) if stale_after is not None else None
    return {
        "label": label,
        "detail": detail,
        "stale": age is not None and age > stale_after,
        "age_days": age,
    }


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _database_items(conn, today: date) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    row = conn.execute(
        f"SELECT fiscal_year, COUNT(DISTINCT symbol) FROM fundamentals "
        f"WHERE eps IS NOT NULL OR pe_ratio IS NOT NULL OR book_value IS NOT NULL "
        f"GROUP BY fiscal_year ORDER BY {_FY_ORDER} DESC LIMIT 1"
    ).fetchone()
    if row and row[0]:
        items.append(_item(
            "Fundamentals",
            f"EPS, P/E and book value for FY {row[0]} ({_plural(row[1], 'company', 'companies')})",
        ))

    row = conn.execute(
        f"SELECT (SELECT fiscal_year FROM dividends ORDER BY {_FY_ORDER} ASC LIMIT 1), "
        f"(SELECT fiscal_year FROM dividends ORDER BY {_FY_ORDER} DESC LIMIT 1)"
    ).fetchone()
    if row and row[1]:
        items.append(_item("Dividends", f"Cash and bonus dividends, FY {row[0]} to FY {row[1]}"))

    row = conn.execute("SELECT MAX(trade_date), COUNT(DISTINCT symbol) FROM price_history").fetchone()
    if row and row[0]:
        items.append(_item(
            "Prices",
            f"Daily prices for {_plural(row[1], 'company', 'companies')}, up to {row[0]}",
            latest=row[0], stale_after=PRICE_STALE_DAYS, today=today,
        ))

    rows = conn.execute(
        "SELECT index_name, MIN(trade_date), MAX(trade_date) FROM indices "
        "GROUP BY index_name ORDER BY index_name = 'NEPSE' DESC, index_name"
    ).fetchall()
    if rows:
        names = [r[0] for r in rows]
        start, end = min(r[1] for r in rows), max(r[2] for r in rows)
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        items.append(_item(
            "Indices",
            f"{listed}, {start} to {end}",
            latest=end, stale_after=PRICE_STALE_DAYS, today=today,
        ))

    row = conn.execute("SELECT COUNT(*), MIN(listing_date), MAX(listing_date) FROM ipos").fetchone()
    if row and row[0] and row[2]:
        items.append(_item("IPOs", f"{_plural(row[0], 'listing')}, {row[1]} to {row[2]}"))

    return items


def _news_item(today: date) -> dict[str, Any] | None:
    from nepse_analyst.retriever import get_corpus_stats

    stats = get_corpus_stats()
    total = stats.get("total_documents") or 0
    earliest, latest = stats.get("earliest_date"), stats.get("latest_date")
    if not total or not latest or latest == "unknown":
        return None
    span = f"all from {latest}" if earliest == latest else f"{earliest} to {latest}"
    return _item(
        "News",
        f"{_plural(total, 'article')}, {span}",
        latest=latest, stale_after=NEWS_STALE_DAYS, today=today,
    )


def data_coverage(today: date | None = None) -> list[dict[str, Any]]:
    """Each dataset's label, what it covers with dates, and whether it is out of date.

    ``stale`` uses the same thresholds as the freshness chip under answers
    (PRICE_STALE_DAYS for prices and indices, NEWS_STALE_DAYS for news).
    Fundamentals, dividends and IPOs are yearly or historical and never flagged.
    """
    today = today or date.today()
    items: list[dict[str, Any]] = []
    try:
        conn = get_connection()
        try:
            items.extend(_database_items(conn, today))
        finally:
            conn.close()
    except Exception:
        pass
    try:
        news = _news_item(today)
    except Exception:
        news = None
    if news:
        items.append(news)
    return items
