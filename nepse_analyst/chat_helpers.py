from __future__ import annotations

from typing import Any

from nepse_analyst.database import get_connection


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


def build_passage_preview(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim passage payloads for cleaner API responses and smaller frontend payloads."""
    output: list[dict[str, Any]] = []
    for passage in passages[:8]:
        content = str(passage.get("content") or "").strip()
        output.append(
            {
                "title": str(passage.get("title") or "Untitled"),
                "source": str(passage.get("source") or "unknown"),
                "published_at": str(passage.get("published_at") or "unknown"),
                "relevance_score": passage.get("relevance_score"),
                "content_preview": content[:420]
                + ("..." if len(content) > 420 else ""),
            }
        )
    return output
