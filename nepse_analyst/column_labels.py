"""Readable headers and units for the data table under an answer.

Generated SQL returns raw column names (``cash_dividend``, ``fy_start``) or the
model's own aliases (``max_eps``, ``avg_close_90d``). ``column_labels`` turns
each into ``{"key", "label", "unit", "description"}`` for the Sources table.
"""

from __future__ import annotations

import re

# column -> (label, unit, description)
_KNOWN: dict[str, tuple[str, str | None, str | None]] = {
    "symbol": ("Symbol", None, None),
    "name": ("Company", None, None),
    "company_name": ("Company", None, None),
    "sector": ("Sector", None, None),
    "fiscal_year": ("Fiscal year", None, "Nepali fiscal year, e.g. 2081/82"),
    "dividend_fy": ("Dividend fiscal year", None, "Nepali fiscal year, e.g. 2081/82"),
    "fy_start": ("Fiscal year (start)", None, "First year of the Nepali fiscal year: 2080 means 2080/81"),
    "eps": ("EPS", "NPR", "Earnings per share"),
    "pe_ratio": ("P/E ratio", None, "Share price divided by earnings per share"),
    "book_value": ("Book value per share", "NPR", None),
    "roe": ("ROE", "%", "Return on equity"),
    "net_profit": ("Net profit", "NPR", None),
    "total_assets": ("Total assets", "NPR", None),
    "revenue": ("Revenue", "NPR", None),
    "cash_dividend": ("Cash dividend", "%", "Percent of face value: 15 means 15%"),
    "bonus_shares": ("Bonus shares", "%", "Stock dividend, percent of shares held"),
    "book_close_date": ("Book close date", None, None),
    "announced_date": ("Announced", None, None),
    "trade_date": ("Date", None, None),
    "latest_trade_date": ("Latest trade date", None, None),
    "open_price": ("Open", "NPR", None),
    "high_price": ("High", "NPR", None),
    "low_price": ("Low", "NPR", None),
    "close_price": ("Close", "NPR", None),
    "close": ("Close", "NPR", None),
    "volume": ("Volume", "shares", None),
    "turnover": ("Turnover", "NPR", None),
    "market_cap": ("Market cap", "NPR", "Listed shares × latest close"),
    "listed_shares": ("Listed shares", "shares", None),
    "paid_up_value": ("Paid-up value per share", "NPR", None),
    "total_paid_up": ("Paid-up capital", "NPR", None),
    "high_52w": ("52-week high", "NPR", None),
    "low_52w": ("52-week low", "NPR", None),
    "index_name": ("Index", None, None),
    "close_value": ("Index close", "points", None),
    "change_points": ("Change", "points", None),
    "change_percent": ("Change", "%", None),
    "issue_price": ("Issue price", "NPR", None),
    "listing_price": ("Listing price", "NPR", "First traded price"),
    "issue_date": ("Issue date", None, None),
    "listing_date": ("Listing date", None, None),
    "shares_issued": ("Shares issued", "shares", None),
    "total_applicants": ("Applicants", None, None),
    "oversubscription_rate": ("Oversubscription", "×", None),
    "symbols_with_dividend_rows": ("Companies with dividend data", None, None),
    "total_symbols": ("Companies", None, None),
}

# Aggregate prefixes the model uses in aliases ("max_eps", "avg_turnover").
_PREFIXES = {
    "avg": "Average",
    "average": "Average",
    "max": "Highest",
    "min": "Lowest",
    "total": "Total",
    "sum": "Total",
    "count": "Number of",
    "num": "Number of",
}

_ACRONYMS = {"eps", "roe", "pe", "ltp", "fy", "nepse", "ipo", "npr", "id"}


def _humanize(key: str) -> str:
    words = [w for w in re.split(r"[_\s]+", key) if w]
    words = [w.upper() if w.lower() in _ACRONYMS else w.lower() for w in words]
    text = " ".join(words) or key
    return text[0].upper() + text[1:]


# Whole-number years, shown without digit grouping (2082, not 2,082).
_YEAR_COLUMNS = {"fy_start", "year", "fy", "fiscal_year_start", "listing_year"}

_WINDOW = re.compile(r"_(\d+)d$")  # "avg_close_90d" -> a 90-day window
_COUNTED_COMPANIES = {"symbol", "symbols", "company", "companies"}


def column_label(key: str) -> dict[str, str | None]:
    """Label, unit and description for one result column."""
    normalized = key.strip().lower()
    window = _WINDOW.search(normalized)
    if window and normalized not in _KNOWN:
        inner = column_label(normalized[: window.start()])
        return {**inner, "key": key, "label": f"{inner['label']} ({window.group(1)} days)"}
    if normalized in _KNOWN:
        label, unit, description = _KNOWN[normalized]
        return {"key": key, "label": label, "unit": unit, "description": description}

    prefix, _, rest = normalized.partition("_")
    if prefix in ("count", "num") and rest in _COUNTED_COMPANIES:
        return {"key": key, "label": "Number of companies", "unit": None, "description": None}
    if prefix in _PREFIXES and rest:
        if rest in _KNOWN:
            base, unit, description = _KNOWN[rest]
            # Keep acronyms (EPS, ROE) as written; lower-case ordinary words.
            base = base if base.isupper() or base[:2].isupper() else base[0].lower() + base[1:]
            unit = None if _PREFIXES[prefix] == "Number of" else unit
            return {"key": key, "label": f"{_PREFIXES[prefix]} {base}", "unit": unit, "description": description}
        return {"key": key, "label": f"{_PREFIXES[prefix]} {_humanize(rest).lower()}", "unit": None, "description": None}

    return {"key": key, "label": _humanize(key), "unit": None, "description": None}


def column_labels(columns: list[str]) -> list[dict[str, str | None]]:
    """Labels for a result's columns; ``format`` is "year" for year columns, else "number"."""
    return [
        {**column_label(c), "format": "year" if c.strip().lower() in _YEAR_COLUMNS else "number"}
        for c in columns
    ]
