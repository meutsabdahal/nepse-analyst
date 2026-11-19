import re

from nepse_analyst import ambiguous_symbols, llm
from nepse_analyst.config import ROUTER_TIMEOUT_SEC
from nepse_analyst.database import get_connection
from nepse_analyst.guardrails import get_guardrail_type
from nepse_analyst.language_detector import detect_language
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
    "non-life insurance": "Non-Life Insurance",
    "non life insurance": "Non-Life Insurance",
    "hotel": "Hotels & Tourism",
    "tourism": "Hotels & Tourism",
    "manufacturing": "Manufacturing",
    "telecom": "Telecom",
    "mutual fund": "Mutual Funds",
}

# Longest alias first, so "development bank" wins over "bank" and "microfinance"
# over "finance". Each alias must start a word: "life insurance" does not match
# inside "non-life insurance". The end is left open so plurals ("banks") match.
_SECTOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(r"(?<![\w-])" + re.escape(alias)), canonical)
    for alias, canonical in sorted(_SECTOR_ALIASES.items(), key=lambda item: (-len(item[0]), item[0]))
)


# Financial metric keywords, checked in this order on word boundaries ("eps"
# not inside "NEPSE" or "steps", "roe" not inside "heroes"); a plural "s" is allowed.
_METRIC_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("eps", "eps"),
    ("earnings per share", "eps"),
    ("p/e", "pe_ratio"),
    ("pe ratio", "pe_ratio"),
    ("price to earnings", "pe_ratio"),
    ("book value", "book_value"),
    ("roe", "roe"),
    ("return on equity", "roe"),
    ("dividend", "dividend"),
    ("bonus share", "bonus_shares"),
    ("market cap", "market_cap"),
    ("turnover", "turnover"),
    ("net profit", "net_profit"),
    ("revenue", "revenue"),
)
_METRIC_PATTERNS = tuple(
    (re.compile(r"(?<!\w)" + re.escape(kw) + r"s?(?!\w)"), metric) for kw, metric in _METRIC_KEYWORDS
)

# The 52-week price range needs explicit wording; "high" and "low" alone are
# too common ("highest EPS", "below book value").
_FIFTY_TWO_WEEK = re.compile(r"(?<!\w)52[\s-]?weeks?(?!\w)")
_HIGH_AND_LOW = re.compile(r"\b(?:high\s*(?:and|&|/|-)\s*low|low\s*(?:and|&|/|-)\s*high)\b")
_HIGH = re.compile(r"\bhigh\b")
_LOW = re.compile(r"\blow\b")


def price_range_metric(query: str) -> str | None:
    """'price_range', 'price_high' or 'price_low' for a 52-week high/low question, else None.

    Requires "52-week" (or "52 week") or "high and low". With "52-week" and only
    one of the words "high" / "low", the question asks for just that end.
    """
    q = query.lower()
    if _HIGH_AND_LOW.search(q):
        return "price_range"
    if not _FIFTY_TWO_WEEK.search(q):
        return None
    has_high, has_low = bool(_HIGH.search(q)), bool(_LOW.search(q))
    if has_high and not has_low:
        return "price_high"
    if has_low and not has_high:
        return "price_low"
    return "price_range"


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


def _sort_symbols(symbols: set[str]) -> tuple[str, ...]:
    """Sort symbols so extraction is deterministic and prefers more specific matches."""
    return tuple(sorted(symbols, key=lambda symbol: (-len(symbol), symbol)))


# Module-level symbol cache — loaded once, avoids repeated DB hits
_SYMBOLS: tuple[str, ...] = tuple()


def _get_symbols() -> tuple[str, ...]:
    global _SYMBOLS
    if not _SYMBOLS:
        _SYMBOLS = _sort_symbols(_load_symbols())
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
        # Match as whole word to avoid partial matches (e.g. 'NIC' inside 'NICA').
        # Symbols that are also ordinary words need the name or market context.
        if any(
            ambiguous_symbols.mention_counts(symbol, query, m.start(), m.end())
            for m in re.finditer(r"\b" + re.escape(symbol) + r"\b", q_upper)
        ):
            detected_symbol = symbol
            break

    # Sector detection — check aliases, longest first
    detected_sector = None
    for pattern, canonical in _SECTOR_PATTERNS:
        if pattern.search(q_lower):
            detected_sector = canonical
            break

    # Metric detection — what financial metric is being asked about.
    # An explicit 52-week / high-and-low question wins over other keywords.
    metric = price_range_metric(query)
    if metric is None:
        metric = next((name for pattern, name in _METRIC_PATTERNS if pattern.search(q_lower)), None)

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
        raw = llm.call(prompt, temperature=0.0, max_timeout_sec=ROUTER_TIMEOUT_SEC)
        route = raw.strip().upper().split()[0]  # take first word, uppercase
        if route not in _VALID_ROUTES:
            route = "SQL"  # safe fallback — SQL is the most common case
        confidence = "high"
    except Exception:
        # LLM call failed or timed out — apply heuristic fallback routing
        route = _heuristic_route(query, language, entities)
        confidence = "low"

    # OOS from LLM with no keyword match: mark as unknown rather than mislabeling.
    if route == "OOS" and not guardrail:
        guardrail = "unknown"

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
