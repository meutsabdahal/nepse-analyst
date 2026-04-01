from datetime import datetime
import re
from nepse_analyst.router import classify
from nepse_analyst.guardrails import build_decline_response, append_disclaimer
from nepse_analyst.sql_generator import generate_and_execute
from nepse_analyst.retriever import search, get_corpus_stats
from nepse_analyst.database import get_connection
from nepse_analyst import llm
from nepse_analyst.config import TOP_K_RAG, NEWS_STALE_DAYS
from nepse_analyst.prompts import (
    build_sql_synthesis_prompt,
    build_rag_synthesis_prompt,
    build_direct_prompt,
)


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


# Route handlers


def _handle_sql(query: str, language: str, entities: dict) -> dict:
    """Execute the Text-to-SQL pathway."""
    coverage_fallback = _build_dividend_sector_coverage_fallback(query, language)
    if coverage_fallback:
        return {
            "success": True,
            "answer": append_disclaimer(coverage_fallback["answer"], language),
            "route": "SQL",
            "sql": coverage_fallback.get("sql"),
            "sql_rows": coverage_fallback.get("sql_rows", []),
            "passages": [],
            "query_language": language,
            "data_freshness": _get_db_freshness(),
            "error": None,
        }

    result = generate_and_execute(query)

    if not result["success"]:
        dividend_fallback = _build_dividend_consistency_fallback(
            query, language, entities
        )
        if dividend_fallback:
            return {
                "success": True,
                "answer": append_disclaimer(dividend_fallback["answer"], language),
                "route": "SQL",
                "sql": dividend_fallback.get("sql"),
                "sql_rows": dividend_fallback.get("sql_rows", []),
                "passages": [],
                "query_language": language,
                "data_freshness": _get_db_freshness(),
                "error": None,
            }

        fallback = _build_symbol_metric_fallback(language, entities)
        if fallback:
            return {
                "success": True,
                "answer": append_disclaimer(fallback["answer"], language),
                "route": "SQL",
                "sql": fallback.get("sql"),
                "sql_rows": fallback.get("sql_rows", []),
                "passages": [],
                "query_language": language,
                "data_freshness": _get_db_freshness(),
                "error": None,
            }

        answer = (
            "I was unable to retrieve structured data for this question. "
            f"The database returned an error after {result['attempts']} attempts: "
            f"{result['error']}\n\n"
            "This may mean the data is not available in the current dataset. "
            "Please check the data freshness indicator."
        )
        if language == "ne":
            answer = (
                "यो प्रश्नको लागि संरचित डेटा प्राप्त गर्न सकिएन। "
                "डेटाबेसले त्रुटि दियो। डेटा उपलब्ध नहुन सक्छ।"
            )
        return {
            "success": False,
            "answer": append_disclaimer(answer, language),
            "route": "SQL",
            "sql": result.get("sql"),
            "sql_rows": [],
            "passages": [],
            "query_language": language,
            "data_freshness": _get_db_freshness(),
            "error": result["error"],
        }

    if not result["rows"]:
        dividend_fallback = _build_dividend_consistency_fallback(
            query, language, entities
        )
        if dividend_fallback:
            return {
                "success": True,
                "answer": append_disclaimer(dividend_fallback["answer"], language),
                "route": "SQL",
                "sql": dividend_fallback.get("sql"),
                "sql_rows": dividend_fallback.get("sql_rows", []),
                "passages": [],
                "query_language": language,
                "data_freshness": _get_db_freshness(),
                "error": None,
            }

        fallback = _build_symbol_metric_fallback(language, entities)
        if fallback:
            return {
                "success": True,
                "answer": append_disclaimer(fallback["answer"], language),
                "route": "SQL",
                "sql": fallback.get("sql"),
                "sql_rows": fallback.get("sql_rows", []),
                "passages": [],
                "query_language": language,
                "data_freshness": _get_db_freshness(),
                "error": None,
            }

    # Synthesise natural language answer from SQL result
    synthesis_prompt = build_sql_synthesis_prompt(
        query=query,
        sql=result["sql"],
        rows=result["rows"],
        columns=result["columns"],
        query_language=language,
    )
    answer = llm.call(synthesis_prompt, temperature=0.1)

    return {
        "success": True,
        "answer": append_disclaimer(answer, language),
        "route": "SQL",
        "sql": result["sql"],
        "sql_rows": result["rows"],
        "passages": [],
        "query_language": language,
        "data_freshness": _get_db_freshness(),
        "error": None,
    }


def _handle_rag(query: str, language: str, entities: dict) -> dict:
    """Execute the multilingual RAG pathway."""
    # Use entity metadata for filtered retrieval when a symbol is detected
    try:
        passages = search(
            query=query,
            top_k=TOP_K_RAG,
            symbol_filter=entities.get("symbol") or None,
            sector_filter=entities.get("sector") or None,
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
        return {
            "success": False,
            "answer": append_disclaimer(answer, language),
            "route": "RAG",
            "sql": None,
            "passages": [],
            "query_language": language,
            "data_freshness": "News data freshness unknown",
            "error": str(e),
        }

    if not passages:
        answer = (
            "No relevant news or announcements were found for this query in the current corpus. "
            "The news corpus is updated weekly — try again after the next refresh."
        )
        if language == "ne":
            answer = "यस प्रश्नसँग सम्बन्धित कुनै समाचार भेटिएन।"
        return {
            "success": False,
            "answer": append_disclaimer(answer, language),
            "route": "RAG",
            "sql": None,
            "passages": [],
            "query_language": language,
            "data_freshness": _get_news_freshness(),
            "error": "No passages retrieved",
        }

    synthesis_prompt = build_rag_synthesis_prompt(query, passages, language)
    answer = llm.call(synthesis_prompt, temperature=0.1)
    stale_warning = _get_news_staleness_warning(language)
    if stale_warning:
        answer = f"{stale_warning}\n\n{answer}"

    return {
        "success": True,
        "answer": append_disclaimer(answer, language),
        "route": "RAG",
        "sql": None,
        "passages": passages,
        "query_language": language,
        "data_freshness": _get_news_freshness(),
        "error": None,
    }


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

    return {
        "success": sql_result["success"] or rag_result["success"],
        "answer": append_disclaimer(combined, language),
        "route": "HYBRID",
        "sql": sql_result.get("sql"),
        "sql_rows": sql_result.get("sql_rows", []),
        "passages": rag_result.get("passages", []),
        "query_language": language,
        "data_freshness": f"{_get_db_freshness()} | {_get_news_freshness()}",
        "error": None,
    }


def _handle_direct(query: str, language: str) -> dict:
    """Handle general knowledge questions about NEPSE that need no data retrieval."""
    prompt = build_direct_prompt(query, language)
    answer = llm.call(
        prompt, temperature=0.2
    )  # slight temperature for more natural prose
    return {
        "success": True,
        "answer": append_disclaimer(answer, language),
        "route": "DIRECT",
        "sql": None,
        "passages": [],
        "query_language": language,
        "data_freshness": None,
        "error": None,
    }


# Main entry point


def run(query: str) -> dict:
    """
    Process a natural language query end-to-end.
    This is the single function the chat API calls.

    Returns:
    {
        "success":        bool,
        "answer":         str,      # final answer with disclaimer appended
        "route":          str,      # 'SQL' | 'RAG' | 'HYBRID' | 'DIRECT' | 'OOS'
        "guardrail_type": str|None, # 'prediction' | 'advice' | None
        "sql":            str|None, # generated SQL (for transparency panel)
        "sql_rows":       list,     # raw rows (for transparency panel)
        "passages":       list,     # retrieved news passages (for transparency panel)
        "query_language": str,      # 'en' | 'ne' | 'mixed'
        "data_freshness": str|None, # human-readable freshness string
        "error":          str|None
    }
    """
    query = query.strip()
    if not query:
        return {
            "success": False,
            "answer": "Please enter a question.",
            "route": None,
            "guardrail_type": None,
            "sql": None,
            "sql_rows": [],
            "passages": [],
            "query_language": "en",
            "data_freshness": None,
            "error": "Empty query",
        }

    # Step 1 — Classify and route
    routing = classify(query)
    route = routing["route"]
    language = routing["language"]
    entities = routing["entities"]
    guardrail = routing.get("guardrail")

    # Step 2 — Guardrail intercept
    if route == "OOS" or guardrail:
        decline = build_decline_response(query, guardrail or "prediction")
        decline["guardrail_type"] = guardrail
        return decline

    # Step 3 — Dispatch to the correct pathway
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
    except Exception as e:
        result = {
            "success": False,
            "answer": append_disclaimer(
                f"An unexpected error occurred while processing your question: {str(e)}",
                language,
            ),
            "route": route,
            "sql": None,
            "sql_rows": [],
            "passages": [],
            "query_language": language,
            "data_freshness": None,
            "error": str(e),
        }

    result["guardrail_type"] = None
    return result
