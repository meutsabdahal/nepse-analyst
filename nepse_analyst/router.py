import re
from nepse_analyst import llm
from nepse_analyst.guardrails import get_guardrail_type
from nepse_analyst.language_detector import detect_language
from nepse_analyst.database import get_connection
from nepse_analyst.prompts import build_router_prompt

# Valid route labels returned by the LLM
_VALID_ROUTES = {"SQL", "RAG", "HYBRID", "DIRECT", "OOS"}

# Sector aliases — maps common user phrasings to the exact DB sector name
_SECTOR_ALIASES = {
    "bank": "Commercial Banks",
    "banks": "Commercial Banks",
    "banking": "Commercial Banks",
    "commercial bank": "Commercial Banks",
    "hydro": "Hydropower",
    "hydropower": "Hydropower",
    "hydro power": "Hydropower",
    "life insurance": "Life Insurance",
    "insurance": "Life Insurance",
    "development bank": "Development Banks",
    "dev bank": "Development Banks",
    "microfinance": "Microfinance",
    "finance": "Finance Companies",
    "non-life": "Non-Life Insurance",
    "hotel": "Hotels & Tourism",
    "tourism": "Hotels & Tourism",
    "manufacturing": "Manufacturing",
    "telecom": "Telecom",
    "mutual fund": "Mutual Funds",
}


def _load_symbols() -> set[str]:
    """Load all company symbols from the DB for entity extraction."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM companies WHERE is_active = 1")
        symbols = {row[0] for row in cursor.fetchall()}
        conn.close()
        return symbols
    except Exception:
        return set()


# Module-level symbol cache — loaded once, avoids repeated DB hits
_SYMBOLS: set[str] = set()


def _get_symbols() -> set[str]:
    global _SYMBOLS
    if not _SYMBOLS:
        _SYMBOLS = _load_symbols()
    return _SYMBOLS


def extract_entities(query: str) -> dict:
    """
    Extract structured entities from a natural language query.
    Returns: {'symbol': str|None, 'sector': str|None, 'metric': str|None, 'time_period': str|None}
    """
    q_upper = query.upper()
    q_lower = query.lower()

    # Symbol detection — check if any known symbol appears in the query
    detected_symbol = None
    for symbol in _get_symbols():
        # Match as whole word to avoid partial matches (e.g. 'NIC' inside 'NICA')
        if re.search(r"\b" + re.escape(symbol) + r"\b", q_upper):
            detected_symbol = symbol
            break

    # Sector detection — check aliases
    detected_sector = None
    for alias, canonical in _SECTOR_ALIASES.items():
        if alias in q_lower:
            detected_sector = canonical
            break

    # Metric detection — what financial metric is being asked about
    metric = None
    metric_keywords = {
        "eps": "eps",
        "earnings per share": "eps",
        "p/e": "pe_ratio",
        "pe ratio": "pe_ratio",
        "price to earnings": "pe_ratio",
        "book value": "book_value",
        "roe": "roe",
        "return on equity": "roe",
        "dividend": "dividend",
        "bonus share": "bonus_shares",
        "market cap": "market_cap",
        "turnover": "turnover",
        "52-week": "price_range",
        "52 week": "price_range",
        "high": "price_high",
        "low": "price_low",
        "net profit": "net_profit",
        "revenue": "revenue",
    }
    for kw, metric_name in metric_keywords.items():
        if kw in q_lower:
            metric = metric_name
            break

    # Time period detection
    time_period = None
    if any(
        t in q_lower
        for t in ["last year", "past year", "1 year", "one year", "52-week"]
    ):
        time_period = "1_year"
    elif any(
        t in q_lower
        for t in ["last 3 years", "3 years", "three years", "3 consecutive"]
    ):
        time_period = "3_years"
    elif any(t in q_lower for t in ["last month", "30 days", "past month"]):
        time_period = "30_days"
    elif any(t in q_lower for t in ["latest", "current", "recent", "now", "today"]):
        time_period = "latest"

    return {
        "symbol": detected_symbol,
        "sector": detected_sector,
        "metric": metric,
        "time_period": time_period,
    }


def classify(query: str) -> dict:
    """
    Main router function. Returns a routing decision dict.

    Return structure:
    {
        "route":      str,    # 'SQL' | 'RAG' | 'HYBRID' | 'DIRECT' | 'OOS'
        "guardrail":  str|None,  # 'prediction' | 'advice' | None
        "language":   str,    # 'en' | 'ne' | 'mixed'
        "entities":   dict,   # output of extract_entities()
        "confidence": str     # 'high' | 'low' (based on whether LLM agreed with guardrail)
    }
    """
    language = detect_language(query)
    entities = extract_entities(query)

    # Guardrail check FIRST — before any LLM call
    guardrail = get_guardrail_type(query)
    if guardrail:
        return {
            "route": "OOS",
            "guardrail": guardrail,
            "language": language,
            "entities": entities,
            "confidence": "high",  # keyword match = high confidence
        }

    # LLM classification
    prompt = build_router_prompt(query, language, entities)
    try:
        raw = llm.call(prompt, temperature=0.0)
        route = raw.strip().upper().split()[0]  # take first word, uppercase
        if route not in _VALID_ROUTES:
            route = "SQL"  # safe fallback — SQL is the most common case
        confidence = "high"
    except Exception as e:
        # LLM call failed — apply heuristic fallback routing
        route = _heuristic_route(query, language, entities)
        confidence = "low"

    # OOS from LLM — also run through guardrail builder
    if route == "OOS" and not guardrail:
        guardrail = (
            "prediction"  # assume prediction if LLM classifies OOS but keywords missed
        )

    return {
        "route": route,
        "guardrail": guardrail,
        "language": language,
        "entities": entities,
        "confidence": confidence,
    }


def _heuristic_route(query: str, language: str, entities: dict) -> str:
    """
    Fallback routing when the LLM call fails.
    Uses entity detection and keyword matching only.
    """
    q_lower = query.lower()
    news_signals = [
        "news",
        "announcement",
        "agm",
        "recent",
        "latest news",
        "regulatory",
        "policy",
        "समाचार",
        "घोषणा",
    ]
    structured_signals = [
        "eps",
        "p/e",
        "dividend",
        "price",
        "turnover",
        "market cap",
        "book value",
        "ipo",
        "index",
        "roe",
    ]
    if any(s in q_lower for s in news_signals):
        if any(s in q_lower for s in structured_signals):
            return "HYBRID"
        return "RAG"
    if any(s in q_lower for s in structured_signals) or entities.get("metric"):
        return "SQL"
    if any(s in q_lower for s in ["what is", "how does", "explain", "define"]):
        return "DIRECT"
    return "SQL"  # default — most queries are structured data queries
