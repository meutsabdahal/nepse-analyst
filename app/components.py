from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from nepse_analyst.database import execute_query


def _extract_symbol(result: dict[str, Any], query: str) -> str | None:
    # Prioritize symbols present in SQL rows.
    for row in result.get("sql_rows", []) or []:
        symbol = row.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            return symbol.strip().upper()

    # Fall back to uppercase tokens from query (2-6 chars) that exist in companies table.
    tokens = [t.strip(" ,.?()[]{}:") for t in query.split()]
    candidates = [t.upper() for t in tokens if t.isascii() and t.isalpha() and 2 <= len(t) <= 6]
    if not candidates:
        return None

    in_clause = ",".join([f"'{c}'" for c in sorted(set(candidates))])
    sql = (
        "SELECT symbol FROM companies "
        f"WHERE symbol IN ({in_clause}) "
        "ORDER BY symbol LIMIT 1"
    )
    found = execute_query(sql)
    if found["success"] and found["row_count"] > 0:
        return found["rows"][0]["symbol"]
    return None


def quick_facts(symbol: str) -> dict[str, Any]:
    facts_sql = f"""
    WITH latest_price AS (
        SELECT symbol, close_price, trade_date
        FROM price_history
        WHERE symbol = '{symbol}'
        ORDER BY trade_date DESC
        LIMIT 1
    ), latest_fundamentals AS (
        SELECT symbol, fiscal_year, pe_ratio, eps, book_value, roe
        FROM fundamentals
        WHERE symbol = '{symbol}'
        ORDER BY CAST(SUBSTR(fiscal_year, 1, 4) AS INT) DESC
        LIMIT 1
    ), latest_dividend AS (
        SELECT symbol, fiscal_year, cash_dividend, bonus_shares
        FROM dividends
        WHERE symbol = '{symbol}'
        ORDER BY CAST(SUBSTR(fiscal_year, 1, 4) AS INT) DESC
        LIMIT 1
    ), range_52w AS (
        WITH ref AS (
            SELECT MAX(trade_date) AS max_date
            FROM price_history
            WHERE symbol = '{symbol}'
        )
        SELECT
            MIN(low_price) AS low_52w,
            MAX(high_price) AS high_52w
        FROM price_history, ref
        WHERE symbol = '{symbol}'
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
    LEFT JOIN range_52w r ON 1=1
    WHERE c.symbol = '{symbol}'
    LIMIT 1
    """
    res = execute_query(facts_sql)
    if not res["success"] or res["row_count"] == 0:
        return {}
    return res["rows"][0]


def render_quick_facts(result: dict[str, Any], query: str) -> None:
    symbol = _extract_symbol(result, query)
    if not symbol:
        return

    facts = quick_facts(symbol)
    if not facts:
        return

    st.markdown("### Company Quick Facts")
    st.caption(f"{facts.get('symbol', '')} - {facts.get('name', '')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sector", facts.get("sector") or "N/A")
    c2.metric("Close Price", f"{facts.get('close_price') or 'N/A'}")
    c3.metric("P/E", f"{facts.get('pe_ratio') or 'N/A'}")
    c4.metric("EPS", f"{facts.get('eps') or 'N/A'}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Book Value", f"{facts.get('book_value') or 'N/A'}")
    c6.metric("ROE", f"{facts.get('roe') or 'N/A'}")
    c7.metric("Cash Dividend %", f"{facts.get('cash_dividend') or 'N/A'}")
    c8.metric("Bonus Shares %", f"{facts.get('bonus_shares') or 'N/A'}")

    st.caption(
        f"52-week range: {facts.get('low_52w') or 'N/A'} - {facts.get('high_52w') or 'N/A'} | "
        f"Price date: {facts.get('trade_date') or 'N/A'} | Fiscal year: {facts.get('fiscal_year') or 'N/A'}"
    )


def render_answer_card(result: dict[str, Any]) -> None:
    route = result.get("route") or "UNKNOWN"
    success = result.get("success", False)
    status_label = "Success" if success else "Partial / Failed"

    st.markdown("### Answer")
    st.caption(f"Route: {route} | Status: {status_label}")

    answer = result.get("answer") or "No response returned."
    st.markdown(answer)

    freshness = result.get("data_freshness")
    if freshness:
        st.info(f"Data freshness: {freshness}")

    error = result.get("error")
    if error:
        st.warning(f"Execution detail: {error}")


def render_source_panel(result: dict[str, Any]) -> None:
    with st.expander("Source Transparency", expanded=False):
        sql = result.get("sql")
        rows = result.get("sql_rows") or []
        passages = result.get("passages") or []

        if sql:
            st.markdown("#### SQL used")
            st.code(sql, language="sql")

        if rows:
            st.markdown("#### SQL rows (top preview)")
            preview = pd.DataFrame(rows[:20])
            st.dataframe(preview, use_container_width=True)

        if passages:
            st.markdown("#### Retrieved passages")
            for i, p in enumerate(passages, start=1):
                title = p.get("title", "Untitled")
                source = p.get("source", "unknown")
                pub = p.get("published_at", "unknown")
                score = p.get("relevance_score", "")
                st.markdown(f"{i}. {title}")
                st.caption(f"Source: {source} | Date: {pub} | Score: {score}")
                st.write((p.get("content") or "")[:400] + "...")

        if not sql and not rows and not passages:
            st.write("No source artifacts available for this response.")
