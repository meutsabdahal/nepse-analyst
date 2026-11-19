from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

from nepse_analyst.config import NEWS_STALE_DAYS, PRICE_STALE_DAYS
from nepse_analyst.database import get_connection
from nepse_analyst.number_format import percent, plain, rupee_amount, rupees


def extract_symbol_from_result(result: dict[str, Any], query: str) -> str | None:
    """Try SQL rows first, then query tokens, to locate a company symbol."""
    for row in result.get("sql_rows", []) or []:
        symbol = row.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            return symbol.strip().upper()

    tokens = [token.strip(" ,.?()[]{}:;!\"'") for token in query.split()]
    candidates = {
        token.upper()
        for token in tokens
        if token.isascii() and token.isalpha() and 2 <= len(token) <= 6
    }
    if not candidates:
        return None

    conn = get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(candidates))
        sql = (
            "SELECT symbol FROM companies "
            f"WHERE symbol IN ({placeholders}) "
            "ORDER BY symbol LIMIT 1"
        )
        cursor.execute(sql, tuple(sorted(candidates)))
        row = cursor.fetchone()
        if row and row["symbol"]:
            return str(row["symbol"]).strip().upper()
        return None
    finally:
        conn.close()


def fetch_quick_facts(symbol: str) -> dict[str, Any] | None:
    """Fetch compact company facts used by the chat side panel."""
    query = """
    WITH latest_price AS (
        SELECT symbol, close_price, trade_date
        FROM price_history
        WHERE symbol = ?
        ORDER BY trade_date DESC
        LIMIT 1
    ), latest_fundamentals AS (
        SELECT symbol, fiscal_year, pe_ratio, eps, book_value, roe
        FROM fundamentals
        WHERE symbol = ?
        ORDER BY CAST(SUBSTR(fiscal_year, 1, 4) AS INT) DESC
        LIMIT 1
    ), latest_dividend AS (
        SELECT symbol, fiscal_year, cash_dividend, bonus_shares
        FROM dividends
        WHERE symbol = ?
        ORDER BY CAST(SUBSTR(fiscal_year, 1, 4) AS INT) DESC
        LIMIT 1
    ), range_52w AS (
        WITH ref AS (
            SELECT MAX(trade_date) AS max_date
            FROM price_history
            WHERE symbol = ?
        )
        SELECT
            MIN(low_price) AS low_52w,
            MAX(high_price) AS high_52w
        FROM price_history, ref
        WHERE symbol = ?
          AND trade_date > date(max_date, '-365 day')
    )
    SELECT
        c.symbol,
        c.name,
        c.sector,
        c.market_cap,
        lp.close_price,
        lp.trade_date,
        lf.fiscal_year,
        lf.pe_ratio,
        lf.eps,
        lf.book_value,
        lf.roe,
        ld.cash_dividend,
        ld.bonus_shares,
        ld.fiscal_year AS dividend_fy,
        r.low_52w,
        r.high_52w
    FROM companies c
    LEFT JOIN latest_price lp ON lp.symbol = c.symbol
    LEFT JOIN latest_fundamentals lf ON lf.symbol = c.symbol
    LEFT JOIN latest_dividend ld ON ld.symbol = c.symbol
    LEFT JOIN range_52w r ON 1 = 1
    WHERE c.symbol = ?
    LIMIT 1
    """

    conn = get_connection()
    try:
        cursor = conn.cursor()
        params = (symbol, symbol, symbol, symbol, symbol, symbol)
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()


_SOURCE_NAMES = {"sharesansar": "ShareSansar", "nepse_alpha": "NepseAlpha", "merolagani": "Merolagani"}


def _safe_url(value: Any) -> str | None:
    """The article link, if it is an http(s) URL (never javascript: or data:)."""
    url = str(value or "").strip()
    return url if urlparse(url).scheme in ("http", "https") and urlparse(url).netloc else None


def build_passage_preview(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The news cards under an answer.

    ``number`` matches the [n] citations in the answer: the answer prompt numbers
    passages from 1 in this same order. The retrieval score is not sent; it means
    nothing to readers.
    """
    output: list[dict[str, Any]] = []
    for number, passage in enumerate(passages[:8], start=1):
        content = str(passage.get("content") or "").strip()
        source = str(passage.get("source") or "").strip()
        output.append(
            {
                "number": number,
                "title": str(passage.get("title") or "Untitled"),
                "url": _safe_url(passage.get("url")),
                "source": source or "unknown",
                "source_name": _SOURCE_NAMES.get(source.lower(), source.replace("_", " ").title() or "Unknown source"),
                "published_at": str(passage.get("published_at") or "unknown"),
                "content_preview": content[:420] + ("..." if len(content) > 420 else ""),
            }
        )
    return output


# Answers that could not be produced do not claim a source.
_NO_DATA_SOURCES = {"generated_sql_failed", "timeout", "error"}


def _articles(count: int) -> str:
    return f"{count} news article" + ("" if count == 1 else "s")


def answer_basis(result: dict[str, Any]) -> dict[str, Any] | None:
    """What an answer is based on, for the label shown under it.

    Returns ``{"kind", "label", "news_articles"}``, or None for an answer that
    failed (it is based on nothing, and the page shows a reference instead).
    ``kind`` is one of "database", "news", "database_and_news",
    "general_knowledge" (the model alone, nothing checked) or "declined".
    """
    route = result.get("route")
    if route == "OOS":
        return {"kind": "declined", "label": "Declined", "news_articles": 0}
    if not result.get("success"):
        return None
    if route == "DIRECT":
        return {"kind": "general_knowledge", "label": "General knowledge, no data checked", "news_articles": 0}

    articles = len(result.get("passages") or [])
    used_database = route in ("SQL", "HYBRID") and bool(result.get("sql")) and (
        result.get("answer_source") not in _NO_DATA_SOURCES
    )
    if used_database and articles:
        return {
            "kind": "database_and_news",
            "label": f"From the database and {_articles(articles)}",
            "news_articles": articles,
        }
    if used_database:
        return {"kind": "database", "label": "From the database", "news_articles": 0}
    if articles:
        return {"kind": "news", "label": f"From {_articles(articles)}", "news_articles": articles}
    return None


def _latest_price_date() -> str | None:
    try:
        conn = get_connection()
        try:
            return conn.execute("SELECT MAX(trade_date) FROM price_history").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def _latest_news_date() -> str | None:
    try:
        from nepse_analyst.retriever import get_corpus_stats

        latest = get_corpus_stats().get("latest_date")
    except Exception:
        return None
    return latest if latest and latest != "unknown" else None


def _age_days(iso_date: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(iso_date)).days if iso_date else None
    except ValueError:
        return None


def data_freshness(today: date | None = None) -> dict[str, Any]:
    """How current the price data and the news corpus are, for the chip under every answer.

    Each is "stale" when it is older than PRICE_STALE_DAYS / NEWS_STALE_DAYS, or
    when its date is unknown (not built yet). ``warning`` explains which, or is None.
    """
    today = today or date.today()
    prices_to, news_to = _latest_price_date(), _latest_news_date()
    prices_age, news_age = _age_days(prices_to, today), _age_days(news_to, today)
    prices_stale = prices_age is None or prices_age > PRICE_STALE_DAYS
    news_stale = news_age is None or news_age > NEWS_STALE_DAYS

    problems = []
    if prices_stale:
        problems.append(
            f"Prices are {prices_age} days old." if prices_age is not None else "No price data is loaded."
        )
    if news_stale:
        problems.append(
            f"News is {news_age} days old." if news_age is not None else "No news is indexed."
        )
    return {
        "prices_to": prices_to,
        "news_to": news_to,
        "prices_age_days": prices_age,
        "news_age_days": news_age,
        "prices_stale": prices_stale,
        "news_stale": news_stale,
        "label": " · ".join(
            [f"Prices to {prices_to}" if prices_to else "No price data",
             f"News to {news_to}" if news_to else "No news data"]
        ),
        "warning": " ".join(problems) or None,
    }


def quick_fact_rows(facts: dict[str, Any]) -> list[dict[str, str | None]]:
    """The quick-facts tiles: label, value with its unit, and what date it is as of.

    Facts with no value are left out rather than shown as "N/A".
    """
    trade_date = facts.get("trade_date")
    fiscal_year = facts.get("fiscal_year")
    dividend_fy = facts.get("dividend_fy")
    on_trade_date = f"on {trade_date}" if trade_date else None
    in_fy = f"FY {fiscal_year}" if fiscal_year else None
    in_dividend_fy = f"FY {dividend_fy}" if dividend_fy else None

    low, high = facts.get("low_52w"), facts.get("high_52w")
    range_52w = f"{rupees(low)} – {rupees(high)}" if low is not None and high is not None else None

    candidates = [
        ("Sector", facts.get("sector"), None),
        ("Close", rupees(facts.get("close_price")), on_trade_date),
        ("Market cap", rupee_amount(facts.get("market_cap")), on_trade_date),
        ("52-week range", range_52w, f"to {trade_date}" if trade_date else None),
        ("P/E", plain(facts.get("pe_ratio")), in_fy),
        ("EPS", rupees(facts.get("eps")), in_fy),
        ("Book value", rupees(facts.get("book_value")), in_fy),
        ("ROE", percent(facts.get("roe")), in_fy),
        ("Cash dividend", percent(facts.get("cash_dividend")), in_dividend_fy),
        ("Bonus shares", percent(facts.get("bonus_shares")), in_dividend_fy),
    ]
    return [
        {"label": label, "value": value, "as_of": as_of}
        for label, value, as_of in candidates
        if value not in (None, "")
    ]
