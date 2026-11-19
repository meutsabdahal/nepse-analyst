from datetime import datetime
import logging
import re
import time

from nepse_analyst import deadline
from nepse_analyst.router import classify, price_range_metric
from nepse_analyst.guardrails import build_decline_response, append_disclaimer
from nepse_analyst.sql_generator import generate_and_execute
from nepse_analyst.retriever import search, get_corpus_stats
from nepse_analyst.database import get_connection
from nepse_analyst import llm
from nepse_analyst.config import TOP_K_RAG, NEWS_STALE_DAYS, REQUEST_TIMEOUT_SEC
from nepse_analyst.prompts import (
    build_sql_synthesis_prompt,
    build_rag_synthesis_prompt,
    build_direct_prompt,
)


logger = logging.getLogger("nepse_analyst.pipeline")


# Data freshness helpers


_LATEST_METRICS_SQL = """
WITH latest_fundamentals AS (
    SELECT
        symbol,
        fiscal_year,
        eps,
        pe_ratio,
        book_value,
        roe,
        net_profit,
        total_assets,
        revenue
    FROM fundamentals
    WHERE symbol = ?
    ORDER BY CAST(SUBSTR(fiscal_year, 1, 4) AS INT) DESC
    LIMIT 1
), latest_dividends AS (
    SELECT
        symbol,
        fiscal_year,
        cash_dividend,
        bonus_shares
    FROM dividends
    WHERE symbol = ?
    ORDER BY CAST(SUBSTR(fiscal_year, 1, 4) AS INT) DESC
    LIMIT 1
)
SELECT
    c.symbol,
    c.name,
    c.market_cap,
    lf.fiscal_year,
    lf.eps,
    lf.pe_ratio,
    lf.book_value,
    lf.roe,
    lf.net_profit,
    lf.total_assets,
    lf.revenue,
    ld.fiscal_year AS dividend_fy,
    ld.cash_dividend,
    ld.bonus_shares
FROM companies c
LEFT JOIN latest_fundamentals lf ON lf.symbol = c.symbol
LEFT JOIN latest_dividends ld ON ld.symbol = c.symbol
WHERE c.symbol = ?
LIMIT 1
"""


_PRICE_RANGE_52W_SQL = """
WITH ref AS (
    SELECT MAX(trade_date) AS max_date
    FROM price_history
    WHERE symbol = ?
)
SELECT
    ? AS symbol,
    ref.max_date AS latest_trade_date,
    MIN(ph.low_price) AS low_52w,
    MAX(ph.high_price) AS high_52w
FROM ref
LEFT JOIN price_history ph
    ON ph.symbol = ?
   AND ph.trade_date > date(ref.max_date, '-365 day')
"""


_DIVIDEND_STREAK_SQL = """
WITH paid AS (
    SELECT
        d.symbol,
        d.fiscal_year,
        CAST(SUBSTR(d.fiscal_year, 1, 4) AS INT) AS fy_start
    FROM dividends d
    JOIN companies c ON c.symbol = d.symbol
    WHERE (? IS NULL OR c.sector = ?)
      AND (
          COALESCE(d.cash_dividend, 0) > 0
          OR COALESCE(d.bonus_shares, 0) > 0
      )
), latest AS (
    SELECT symbol, MAX(fy_start) AS latest_fy_start
    FROM paid
    GROUP BY symbol
), windowed AS (
    SELECT
        p.symbol,
        p.fiscal_year,
        p.fy_start,
        l.latest_fy_start
    FROM paid p
    JOIN latest l ON l.symbol = p.symbol
    WHERE p.fy_start BETWEEN (l.latest_fy_start - ? + 1) AND l.latest_fy_start
), agg AS (
    SELECT
        symbol,
        MIN(fiscal_year) AS from_fy,
        MAX(fiscal_year) AS to_fy,
        COUNT(DISTINCT fy_start) AS years_paid
    FROM windowed
    GROUP BY symbol
)
SELECT
    c.symbol,
    c.name,
    c.sector,
    a.from_fy,
    a.to_fy,
    a.years_paid
FROM agg a
JOIN companies c ON c.symbol = a.symbol
WHERE a.years_paid = ?
ORDER BY a.to_fy DESC, c.symbol
LIMIT 20
"""


_DIVIDEND_SECTOR_COVERAGE_SQL = """
SELECT
    c.sector,
    COUNT(DISTINCT c.symbol) AS total_symbols,
    COUNT(DISTINCT d.symbol) AS symbols_with_dividend_rows
FROM companies c
LEFT JOIN dividends d ON d.symbol = c.symbol
WHERE c.is_active = 1
GROUP BY c.sector
ORDER BY c.sector
"""


def _format_metric_value(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.2f}"
    return str(value)


def _extract_last_n_years(query: str) -> int | None:
    """Extract a year window from queries like 'last 5 years'."""
    q = query.lower()
    match = re.search(r"(?:last|past)\s+(\d+)\s+years?", q)
    if match:
        return int(match.group(1))

    match = re.search(r"(\d+)\s+(?:consecutive\s+)?years?", q)
    if match:
        return int(match.group(1))

    return None


def _build_dividend_consistency_fallback(
    query: str, language: str, entities: dict
) -> dict | None:
    """Return deterministic answer for 'consistent dividend for last N years' queries."""
    q = query.lower()
    if entities.get("metric") != "dividend" and "dividend" not in q:
        return None
    if not any(token in q for token in ["consistent", "consistently", "consecutive"]):
        return None

    years = _extract_last_n_years(query)
    if years is None or years < 2:
        return None

    sector = entities.get("sector")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(_DIVIDEND_STREAK_SQL, (sector, sector, years, years))
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not rows:
        return None

    symbols = ", ".join(row["symbol"] for row in rows[:10])
    if len(rows) > 10:
        symbols += f", and {len(rows) - 10} more"

    sector_text = sector or "the market"
    if language == "ne":
        answer = (
            f"{sector_text} मा पछिल्ला {years} वर्ष लगातार लाभांश दिने कम्पनीहरू भेटिए: "
            f"{symbols}।"
        )
    else:
        answer = (
            f"In {sector_text}, these stocks have paid dividends consistently for the last "
            f"{years} years: {symbols}."
        )

    return {
        "answer": answer,
        "sql": _DIVIDEND_STREAK_SQL.strip(),
        "sql_rows": rows,
    }


def _build_dividend_sector_coverage_fallback(query: str, language: str) -> dict | None:
    """Return deterministic coverage summary for sector-wide dividend data queries."""
    q = query.lower()
    if "dividend" not in q:
        return None
    if "sector" not in q and "sectors" not in q:
        return None
    coverage_tokens = ["every", "all", "each", "available", "coverage", "not available"]
    if not any(token in q for token in coverage_tokens):
        return None

    conn = get_connection()
    try:
        cursor = conn.cursor()
        rows = [
            dict(row)
            for row in cursor.execute(_DIVIDEND_SECTOR_COVERAGE_SQL).fetchall()
        ]
    finally:
        conn.close()

    if not rows:
        return None

    partial = [
        r for r in rows if 0 < r["symbols_with_dividend_rows"] < r["total_symbols"]
    ]
    none = [r for r in rows if r["symbols_with_dividend_rows"] == 0]
    full = [
        r
        for r in rows
        if r["total_symbols"] > 0
        and r["symbols_with_dividend_rows"] == r["total_symbols"]
    ]

    total_symbols = sum(r["total_symbols"] for r in rows)
    covered_symbols = sum(r["symbols_with_dividend_rows"] for r in rows)
    coverage_pct = (covered_symbols * 100.0 / total_symbols) if total_symbols else 0.0

    if language == "ne":
        answer = (
            "हालको डेटासेटमा सबै sector मा dividend data उपलब्ध छैन। "
            f"कुल coverage: {covered_symbols}/{total_symbols} symbols "
            f"({coverage_pct:.1f}%)।"
        )
    else:
        answer = (
            "Dividend data is not available for every sector in the current dataset. "
            f"Overall coverage is {covered_symbols}/{total_symbols} symbols "
            f"({coverage_pct:.1f}%)."
        )

    if full:
        full_sectors = ", ".join(r["sector"] for r in full[:6])
        if language == "ne":
            answer += f" Full coverage भएका sector हरू: {full_sectors}."
        else:
            answer += f" Sectors with full coverage include: {full_sectors}."

    if partial:
        partial_preview = ", ".join(
            f"{r['sector']} ({r['symbols_with_dividend_rows']}/{r['total_symbols']})"
            for r in partial[:6]
        )
        if language == "ne":
            answer += f" Partial coverage उदाहरण: {partial_preview}."
        else:
            answer += f" Partial coverage examples: {partial_preview}."

    if none:
        none_sectors = ", ".join(r["sector"] for r in none[:6])
        if language == "ne":
            answer += f" कुनै dividend data नभएका sector: {none_sectors}."
        else:
            answer += f" Sectors with no dividend rows: {none_sectors}."

    return {
        "answer": answer,
        "sql": _DIVIDEND_SECTOR_COVERAGE_SQL.strip(),
        "sql_rows": rows,
    }


def _is_price_range_query(query: str, entities: dict) -> bool:
    """Detect requests for a 52-week style high/low range answer."""
    if entities.get("metric") in {"price_range", "price_high", "price_low"}:
        return True
    return price_range_metric(query) is not None


def _rows_have_price_range_values(rows: list[dict]) -> bool:
    """Check if SQL rows contain non-null high/low values."""
    if not rows:
        return False

    first = rows[0]
    high_keys = [k for k in first.keys() if "high" in k.lower()]
    low_keys = [k for k in first.keys() if "low" in k.lower()]
    candidate_keys = high_keys + low_keys
    if not candidate_keys:
        return False

    return any(first.get(k) is not None for k in candidate_keys)


def _build_symbol_price_range_fallback(
    query: str, language: str, entities: dict
) -> dict | None:
    """Return deterministic 52-week high/low answer for a single symbol."""
    symbol = entities.get("symbol")
    if not symbol or not _is_price_range_query(query, entities):
        return None

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM companies WHERE symbol = ?", (symbol,))
        company_row = cursor.fetchone()
        company_name = (
            company_row["name"] if company_row and company_row["name"] else symbol
        )

        cursor.execute(_PRICE_RANGE_52W_SQL, (symbol, symbol, symbol))
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return None

    row_dict = dict(row)
    row_dict["name"] = company_name
    high = row_dict.get("high_52w")
    low = row_dict.get("low_52w")
    latest_trade_date = row_dict.get("latest_trade_date")

    if latest_trade_date is None:
        if language == "ne":
            answer = (
                f"{company_name} ({symbol}) को price history हाल डेटासेटमा उपलब्ध छैन, "
                "त्यसैले 52-week high/low गणना गर्न सकिएन।"
            )
        else:
            answer = (
                f"Price history for {company_name} ({symbol}) is not available in the "
                "current dataset, so a 52-week high/low cannot be computed."
            )
        return {
            "answer": answer,
            "sql": _PRICE_RANGE_52W_SQL.strip(),
            "sql_rows": [row_dict],
        }

    if high is None and low is None:
        if language == "ne":
            answer = (
                f"{company_name} ({symbol}) का लागि {latest_trade_date} सम्म price history rows "
                "भए पनि high/low मान उपलब्ध नभएकाले 52-week range निकाल्न सकिएन।"
            )
        else:
            answer = (
                f"Price rows exist for {company_name} ({symbol}) up to {latest_trade_date}, "
                "but high/low values are missing, so the 52-week range cannot be computed."
            )
        return {
            "answer": answer,
            "sql": _PRICE_RANGE_52W_SQL.strip(),
            "sql_rows": [row_dict],
        }

    high_text = _format_metric_value(high) if high is not None else "N/A"
    low_text = _format_metric_value(low) if low is not None else "N/A"

    metric = entities.get("metric")
    if language == "ne":
        if metric == "price_high":
            answer = (
                f"{company_name} ({symbol}) को 52-week high ({latest_trade_date} सम्मको window) "
                f"{high_text} छ।"
            )
        elif metric == "price_low":
            answer = (
                f"{company_name} ({symbol}) को 52-week low ({latest_trade_date} सम्मको window) "
                f"{low_text} छ।"
            )
        else:
            answer = (
                f"{company_name} ({symbol}) को 52-week high {high_text} र low {low_text} छ "
                f"(window ending {latest_trade_date})।"
            )
    else:
        if metric == "price_high":
            answer = (
                f"The 52-week high for {company_name} ({symbol}) is {high_text} "
                f"(window ending {latest_trade_date})."
            )
        elif metric == "price_low":
            answer = (
                f"The 52-week low for {company_name} ({symbol}) is {low_text} "
                f"(window ending {latest_trade_date})."
            )
        else:
            answer = (
                f"The 52-week high for {company_name} ({symbol}) is {high_text} and "
                f"the 52-week low is {low_text} (window ending {latest_trade_date})."
            )

    return {
        "answer": answer,
        "sql": _PRICE_RANGE_52W_SQL.strip(),
        "sql_rows": [row_dict],
    }


def _build_symbol_metric_fallback(language: str, entities: dict) -> dict | None:
    """Return a deterministic metric answer for single-symbol SQL questions."""
    symbol = entities.get("symbol")
    metric = entities.get("metric")
    if not symbol or not metric:
        return None

    metric_map = {
        "eps": ("eps", "EPS", "fiscal_year"),
        "pe_ratio": ("pe_ratio", "P/E ratio", "fiscal_year"),
        "book_value": ("book_value", "book value", "fiscal_year"),
        "roe": ("roe", "ROE", "fiscal_year"),
        "net_profit": ("net_profit", "net profit", "fiscal_year"),
        "total_assets": ("total_assets", "total assets", "fiscal_year"),
        "revenue": ("revenue", "revenue", "fiscal_year"),
        "dividend": ("cash_dividend", "cash dividend", "dividend_fy"),
        "bonus_shares": ("bonus_shares", "bonus shares", "dividend_fy"),
        "market_cap": ("market_cap", "market capitalisation", None),
    }
    metric_spec = metric_map.get(metric)
    if not metric_spec:
        return None

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(_LATEST_METRICS_SQL, (symbol, symbol, symbol))
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return None

    row_dict = dict(row)
    field, label, fy_field = metric_spec
    value = row_dict.get(field)
    if value is None:
        return None

    company_name = row_dict.get("name") or symbol
    value_text = _format_metric_value(value)
    fy = row_dict.get(fy_field) if fy_field else None

    if language == "ne":
        if fy:
            answer = f"{company_name} ({symbol}) को पछिल्लो {label} FY {fy} मा {value_text} छ।"
        else:
            answer = f"{company_name} ({symbol}) को {label} {value_text} छ।"
    else:
        if fy:
            answer = (
                f"The latest {label} for {company_name} ({symbol}) is "
                f"{value_text} in FY {fy}."
            )
        else:
            answer = f"The {label} for {company_name} ({symbol}) is {value_text}."

    return {
        "answer": answer,
        "sql": _LATEST_METRICS_SQL.strip(),
        "sql_rows": [row_dict],
    }


def _get_db_freshness() -> str:
    """Return the most recent trade_date in price_history as a readable string."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM price_history")
        result = cursor.fetchone()
        conn.close()
        date_str = result[0] if result and result[0] else "unknown"
        return f"Price data last updated: {date_str}"
    except Exception:
        return "Price data freshness unknown"


def _get_news_freshness() -> str:
    """Return the most recent article date from the ChromaDB corpus."""
    try:
        stats = get_corpus_stats()
        return f"News data last updated: {stats['latest_date']} ({stats['total_documents']} articles)"
    except Exception:
        return "News data freshness unknown"


def _get_news_staleness_warning(language: str) -> str | None:
    """Return a warning when the news corpus is older than the configured threshold."""
    try:
        stats = get_corpus_stats()
        latest = stats.get("latest_date")
        total = stats.get("total_documents")
        if not latest or latest == "unknown":
            return None

        age_days = (
            datetime.utcnow().date() - datetime.strptime(latest, "%Y-%m-%d").date()
        ).days
        if age_days <= NEWS_STALE_DAYS:
            return None

        if language == "ne":
            return (
                "समाचार कोष पुरानो हुन सक्छ। "
                f"अन्तिम अपडेट: {latest} ({total} लेख), लगभग {age_days} दिन अगाडि।"
            )

        return (
            "The news corpus appears stale. "
            f"Last update: {latest} ({total} articles), about {age_days} days ago."
        )
    except Exception:
        return None


def _fallback_sql_synthesis(rows: list[dict], language: str) -> str:
    """Create a concise non-LLM summary when synthesis model calls fail."""
    if not rows:
        if language == "ne":
            return "क्वेरी सफल भयो, तर कुनै पङ्क्ति नतिजा फेला परेन।"
        return "The query executed successfully, but no rows were returned."

    top_rows = rows[:3]
    if language == "ne":
        lines = [f"क्वेरी सफल भयो। कुल {len(rows)} पङ्क्ति प्राप्त भयो। शीर्ष नतिजा:"]
    else:
        lines = [
            f"Query executed successfully. Retrieved {len(rows)} row(s). Top results:"
        ]

    for row in top_rows:
        parts = [f"{k}: {v}" for k, v in row.items()]
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def _fallback_rag_synthesis(passages: list[dict], language: str) -> str:
    """Create a concise non-LLM summary from retrieved passages."""
    if not passages:
        if language == "ne":
            return "यस प्रश्नका लागि सम्बन्धित समाचार भेटिएन।"
        return "No relevant news passages were found for this query."

    top = passages[:3]
    if language == "ne":
        lines = ["प्राप्त समाचार अंशका आधारमा मुख्य शीर्षकहरू:"]
    else:
        lines = ["Based on retrieved passages, here are the most relevant headlines:"]

    for p in top:
        published_at = p.get("published_at", "")
        title = p.get("title", "Untitled")
        score = p.get("relevance_score", 0.0)
        lines.append(f"- [{score:.3f}] {published_at} | {title}")
    return "\n".join(lines)


# Route handlers


def _response(
    route: str | None,
    language: str,
    answer: str,
    *,
    success: bool = True,
    sql: str | None = None,
    sql_rows: list | None = None,
    passages: list | None = None,
    answer_source: str | None = None,
    data_freshness: str | None = None,
    error: str | None = None,
) -> dict:
    """The response every pathway returns (see ``run`` for the fields).

    ``answer_source`` defaults to the route in lower case ("rag", "direct").
    """
    return {
        "success": success,
        "answer": append_disclaimer(answer, language),
        "route": route,
        "sql": sql,
        "sql_rows": sql_rows or [],
        "answer_source": answer_source or (route or "").lower(),
        "passages": passages or [],
        "query_language": language,
        "data_freshness": data_freshness,
        "error": error,
    }


def _rule_response(answer_source: str, rule: dict, language: str) -> dict:
    """Response for an answer built by one of the keyword-triggered SQL rules."""
    return _response(
        "SQL",
        language,
        rule["answer"],
        sql=rule.get("sql"),
        sql_rows=rule.get("sql_rows"),
        answer_source=answer_source,
        data_freshness=_get_db_freshness(),
    )


# Keyword-triggered rule answers tried, in this order, when the generated SQL
# fails or returns no rows. The first one that applies answers. The lambdas
# look the builders up when called, so tests can replace them.
_SQL_RULE_FALLBACKS = (
    ("rule:dividend_streak", lambda q, lang, ent: _build_dividend_consistency_fallback(q, lang, ent)),
    ("rule:price_range_52w", lambda q, lang, ent: _build_symbol_price_range_fallback(q, lang, ent)),
    ("rule:latest_metric", lambda q, lang, ent: _build_symbol_metric_fallback(lang, ent)),
)


def _first_rule_answer(query: str, language: str, entities: dict) -> dict | None:
    for answer_source, build in _SQL_RULE_FALLBACKS:
        rule = build(query, language, entities)
        if rule:
            return _rule_response(answer_source, rule, language)
    return None


def _handle_sql(query: str, language: str, entities: dict) -> dict:
    """Execute the Text-to-SQL pathway."""
    coverage = _build_dividend_sector_coverage_fallback(query, language)
    if coverage:
        return _rule_response("rule:dividend_sector_coverage", coverage, language)

    result = generate_and_execute(query)

    if not result["success"] or not result["rows"]:
        rule_answer = _first_rule_answer(query, language, entities)
        if rule_answer:
            return rule_answer

    if not result["success"]:
        # The database error stays in "error" (logged with the request ID by run()),
        # never in the answer.
        answer = (
            "I could not get the data for this question. It may not be in the current "
            "dataset, or it may help to ask it more specifically."
        )
        if language == "ne":
            answer = (
                "यो प्रश्नको लागि संरचित डेटा प्राप्त गर्न सकिएन। "
                "डेटा उपलब्ध नहुन सक्छ, वा प्रश्नलाई अझ स्पष्ट रूपमा सोध्दा मद्दत पुग्न सक्छ।"
            )
        return _response(
            "SQL",
            language,
            answer,
            success=False,
            sql=result.get("sql"),
            answer_source="generated_sql_failed",
            data_freshness=_get_db_freshness(),
            error=result["error"],
        )

    # Generated SQL for a 52-week question returned null-like high/low values.
    if _is_price_range_query(query, entities) and not _rows_have_price_range_values(result["rows"]):
        price_range = _build_symbol_price_range_fallback(query, language, entities)
        if price_range:
            return _rule_response("rule:price_range_52w", price_range, language)

    # Synthesise natural language answer from SQL result
    synthesis_prompt = build_sql_synthesis_prompt(
        query=query,
        sql=result["sql"],
        rows=result["rows"],
        columns=result["columns"],
        query_language=language,
        truncated=result.get("truncated", False),
    )
    try:
        answer = llm.call(synthesis_prompt, temperature=0.1)
    except Exception:
        answer = _fallback_sql_synthesis(result["rows"], language)

    return _response(
        "SQL",
        language,
        answer,
        sql=result["sql"],
        sql_rows=result["rows"],
        answer_source="generated_sql",
        data_freshness=_get_db_freshness(),
    )


def _handle_rag(query: str, language: str, entities: dict) -> dict:
    """Execute the multilingual RAG pathway."""
    if deadline.expired():  # e.g. the SQL half of a hybrid question used the whole budget
        return _response(
            "RAG", language, "", success=False,
            error="News search skipped: request time limit reached",
        )
    # Detected company/sector ranks matching articles higher; it does not filter.
    try:
        passages = search(
            query=query,
            top_k=TOP_K_RAG,
            boost_symbol=entities.get("symbol") or None,
            boost_sector=entities.get("sector") or None,
        )
    except Exception as e:
        answer = (
            "News retrieval is currently unavailable because the embedding/vector stack could not be loaded. "
            "Please verify model availability and retry."
        )
        if language == "ne":
            answer = (
                "समाचार खोज सुविधा हाल उपलब्ध छैन। " "एम्बेडिङ मोडेल वा भेक्टर स्टोर लोड हुन सकेन।"
            )
        return _response(
            "RAG", language, answer, success=False,
            data_freshness="News data freshness unknown", error=str(e),
        )

    if not passages:
        answer = (
            "No relevant news or announcements were found for this query in the current corpus. "
            "The news corpus is updated weekly — try again after the next refresh."
        )
        if language == "ne":
            answer = "यस प्रश्नसँग सम्बन्धित कुनै समाचार भेटिएन।"
        return _response(
            "RAG", language, answer, success=False,
            data_freshness=_get_news_freshness(), error="No passages retrieved",
        )

    synthesis_prompt = build_rag_synthesis_prompt(query, passages, language)
    try:
        answer = llm.call(synthesis_prompt, temperature=0.1)
    except Exception:
        answer = _fallback_rag_synthesis(passages, language)

    stale_warning = _get_news_staleness_warning(language)
    if stale_warning:
        answer = f"{stale_warning}\n\n{answer}"

    return _response("RAG", language, answer, passages=passages, data_freshness=_get_news_freshness())


def _handle_hybrid(query: str, language: str, entities: dict) -> dict:
    """
    Execute both SQL and RAG pathways and combine the results.
    Used when a question needs both structured data and news context.
    """
    sql_result = _handle_sql(query, language, entities)
    rag_result = _handle_rag(query, language, entities)

    # Combine both answers into a single response
    combined_parts = []
    if sql_result["success"] and sql_result.get("answer"):
        # Strip disclaimer from the SQL answer before combining (we'll add once at the end)
        sql_answer_clean = sql_result["answer"].split("\n\n---\n")[0]
        combined_parts.append(f"**Structured Data:**\n{sql_answer_clean}")
    if rag_result["success"] and rag_result.get("answer"):
        rag_answer_clean = rag_result["answer"].split("\n\n---\n")[0]
        combined_parts.append(f"**Recent News:**\n{rag_answer_clean}")

    if not combined_parts:
        combined = "I was unable to retrieve data for this question from either the database or news corpus."
    else:
        combined = "\n\n".join(combined_parts)

    return _response(
        "HYBRID",
        language,
        combined,
        success=sql_result["success"] or rag_result["success"],
        sql=sql_result.get("sql"),
        sql_rows=sql_result.get("sql_rows"),
        answer_source=sql_result.get("answer_source"),
        passages=rag_result.get("passages"),
        data_freshness=f"{_get_db_freshness()} | {_get_news_freshness()}",
    )


def _handle_direct(query: str, language: str) -> dict:
    """Handle general knowledge questions about NEPSE that need no data retrieval."""
    prompt = build_direct_prompt(query, language)
    answer = llm.call(prompt, temperature=0.2)  # slight temperature for more natural prose
    return _response("DIRECT", language, answer)


UNEXPECTED_ERROR_ANSWERS = {
    "en": "Something went wrong while answering this question. Please try again in a moment.",
    "ne": "यो प्रश्नको उत्तर दिँदा समस्या आयो। कृपया केही समयपछि फेरि प्रयास गर्नुहोस्।",
}


def _timeout_result(route: str, language: str, timeout_sec: float, error: str) -> dict:
    if language == "ne":
        answer = (
            f"यो प्रश्नको उत्तर {timeout_sec:g} सेकेन्डको समय सीमाभित्र तयार गर्न सकिएन। "
            "कृपया प्रश्नलाई अझ सानो वा स्पष्ट बनाएर फेरि प्रयास गर्नुहोस्।"
        )
    else:
        answer = (
            f"This question could not be answered within the {timeout_sec:g} s time limit. "
            "Please try a narrower or more specific question."
        )
    return _response(
        route, language, answer, success=False, answer_source="timeout",
        error=f"deadline_exceeded: {error}",
    )


# Main entry point


def run(query: str, request_id: str | None = None, timeout_sec: float | None = None) -> dict:
    """Answer one question within a time budget.

    ``timeout_sec`` (default REQUEST_TIMEOUT_SEC; 0 disables) is shared by every
    LLM call and SQL query the question makes; each gets at most the time left.
    """
    timeout_sec = REQUEST_TIMEOUT_SEC if timeout_sec is None else timeout_sec
    with deadline.request_deadline(timeout_sec):
        return _run(query, request_id, timeout_sec)


def _run(query: str, request_id: str | None, timeout_sec: float) -> dict:
    """
    Process a natural language query end-to-end.
    This is the single function the chat API calls.

    Returns:
    {
        "success":        bool,
        "answer":         str,      # final answer with disclaimer appended
        "route":          str,      # 'SQL' | 'RAG' | 'HYBRID' | 'DIRECT' | 'OOS'
        "guardrail_type": str|None, # 'prediction' | 'advice' | 'unknown' | None
        "sql":            str|None, # generated SQL (for transparency panel)
        "sql_rows":       list,     # raw rows (for transparency panel)
        "answer_source":  str,      # what produced the answer: 'generated_sql', 'rule:<name>'
                                    # (keyword-triggered SQL in this module), 'guardrail', 'rag', ...
        "passages":       list,     # retrieved news passages (for transparency panel)
        "query_language": str,      # 'en' | 'ne' | 'mixed'
        "data_freshness": str|None, # human-readable freshness string
        "error":          str|None
    }
    """
    query = query.strip()
    if not query:
        empty = _response(None, "en", "Please enter a question.", success=False, error="Empty query")
        empty["guardrail_type"] = None
        return empty

    # Step 1 — Classify and route
    routing = classify(query)
    route = routing["route"]
    language = routing["language"]
    entities = routing["entities"]
    guardrail = routing.get("guardrail")

    logger.info(
        "route_selected request_id=%s route=%s guardrail=%s language=%s confidence=%s",
        request_id,
        route,
        guardrail,
        language,
        routing.get("confidence"),
    )

    # Step 2 — Guardrail intercept
    if route == "OOS" or guardrail:
        decline_type = guardrail or "unknown"
        decline = build_decline_response(query, decline_type)
        decline["guardrail_type"] = decline_type
        decline["answer_source"] = "guardrail"
        decline.setdefault("sql_rows", [])
        logger.info(
            "route_short_circuit request_id=%s route=OOS guardrail_type=%s",
            request_id,
            decline_type,
        )
        return decline

    # Step 3 — Dispatch to the correct pathway
    dispatch_started = time.perf_counter()
    try:
        if route == "SQL":
            result = _handle_sql(query, language, entities)
        elif route == "RAG":
            result = _handle_rag(query, language, entities)
        elif route == "HYBRID":
            result = _handle_hybrid(query, language, entities)
        elif route == "DIRECT":
            result = _handle_direct(query, language)
        else:
            result = _handle_sql(query, language, entities)  # safe fallback
    except deadline.DeadlineExceeded as e:
        logger.warning(
            "pipeline_deadline_exceeded request_id=%s route=%s timeout_sec=%s error=%s",
            request_id,
            route,
            timeout_sec,
            str(e),
        )
        result = _timeout_result(route, language, timeout_sec, str(e))
    except Exception as e:
        logger.exception(
            "pipeline_unhandled_error request_id=%s route=%s error=%s",
            request_id,
            route,
            str(e),
        )
        result = _response(
            route,
            language,
            UNEXPECTED_ERROR_ANSWERS.get(language, UNEXPECTED_ERROR_ANSWERS["en"]),
            success=False,
            answer_source="error",
            error=str(e),
        )

    dispatch_ms = (time.perf_counter() - dispatch_started) * 1000.0
    logger.info(
        "route_completed request_id=%s route=%s success=%s latency_ms=%.2f",
        request_id,
        result.get("route"),
        result.get("success"),
        dispatch_ms,
    )
    if result.get("error"):
        # The detail (database errors, exception text) is for the logs only;
        # users get the plain answer and the request ID.
        logger.warning(
            "route_error request_id=%s route=%s answer_source=%s sql=%r error=%s",
            request_id,
            result.get("route"),
            result.get("answer_source"),
            result.get("sql"),
            result.get("error"),
        )

    result["guardrail_type"] = None
    return result
