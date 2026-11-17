"""Value coercion and HTTP helpers shared by ingestion sources."""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nepse_analyst.ingestion.records import PriceBar

_LIST_KEYS = ("data", "content", "results", "result", "items", "history", "response")


def _to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def first_non_null(obj: Any, keys: list[str], default: Any = None) -> Any:
    """Return the first non-null value among ``keys`` on a dict or object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k) is not None:
                return obj[k]
        return default
    for k in keys:
        value = getattr(obj, k, None)
        if value is not None:
            return value
    obj_dict = _to_dict(obj)
    for k in keys:
        if obj_dict.get(k) is not None:
            return obj_dict[k]
    return default


def normalize_rows(payload: Any) -> list[Any]:
    """Unwrap the list from the many envelope shapes the APIs return."""
    if payload is None:
        return []
    if isinstance(payload, (list, tuple)):
        return list(payload)
    payload_dict = payload if isinstance(payload, dict) else _to_dict(payload)
    for key in _LIST_KEYS:
        if isinstance(payload_dict.get(key), list):
            return payload_dict[key]
    return [payload]


def to_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def to_float(value: Any) -> float | None:
    """Strict numeric parse: '1,234.5' -> 1234.5; anything else -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)


def normalize_ws(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_float(value: Any) -> float | None:
    """Lenient parse for scraped text: '12.5 %' -> 12.5, '-' / 'N/A' -> None."""
    if value is None:
        return None
    raw = normalize_ws(str(value)).replace(",", "")
    if raw.lower() in {"", "-", "--", "n/a", "na", "none"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", raw)
    return float(m.group(0)) if m else None


def extract_int(value: Any) -> int | None:
    parsed = extract_float(value)
    return None if parsed is None else int(parsed)


_PRICE_DATE_KEYS = [
    "business_date", "businessDate", "trade_date", "tradeDate", "date", "published_date",
]
_PRICE_CLOSE_KEYS = [
    "close_price", "closePrice", "last_traded_price", "lastTradedPrice", "close", "ltp",
]
_PRICE_VOLUME_KEYS = [
    "total_traded_quantity", "totalTradeQuantity", "total_trade_quantity",
    "totalTradedQuantity", "volume", "traded_quantity",
]
_PRICE_TURNOVER_KEYS = [
    "total_traded_value", "totalTradeValue", "total_trade_value", "turnover",
    "turn_over", "turnOver", "traded_amount",
]


def price_bars_from_records(symbol: str, items: list[Any]) -> list[PriceBar]:
    """Map heterogeneous provider rows onto PriceBar, skipping undated/unpriced rows."""
    bars: list[PriceBar] = []
    for item in items:
        trade_date = to_iso_date(first_non_null(item, _PRICE_DATE_KEYS))
        close_price = to_float(first_non_null(item, _PRICE_CLOSE_KEYS))
        if trade_date is None or close_price is None:
            continue
        volume = to_int(first_non_null(item, _PRICE_VOLUME_KEYS))
        turnover = to_float(first_non_null(item, _PRICE_TURNOVER_KEYS))
        if turnover is None and volume is not None:
            turnover = close_price * volume
        bars.append(
            PriceBar(
                symbol=symbol,
                trade_date=trade_date,
                close_price=close_price,
                open_price=to_float(first_non_null(item, ["open_price", "openPrice", "open"])),
                high_price=to_float(first_non_null(item, ["high_price", "highPrice", "high"])),
                low_price=to_float(first_non_null(item, ["low_price", "lowPrice", "low"])),
                volume=volume,
                turnover=turnover,
            )
        )
    return bars


def canonical_index_name(raw_name: Any) -> str | None:
    if raw_name is None:
        return None
    text = str(raw_name).strip().lower().replace("%20", " ")
    if "bank" in text:
        return "Banking"
    if "hydro" in text:
        return "Hydropower"
    if "nepse" in text or "all share" in text:
        return "NEPSE"
    return None


def _http_get(url: str, accept: str, timeout: float, retries: int) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": accept})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(1)
    raise RuntimeError(f"HTTP fetch failed for {url}: {last_exc}")


def http_get_json(
    url: str, params: dict[str, Any] | None = None, timeout: float = 8, retries: int = 1
) -> Any:
    full_url = f"{url}?{urlencode(params)}" if params else url
    body = _http_get(full_url, "application/json", timeout, retries)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {full_url}: {exc}") from exc


def http_get_text(url: str, timeout: float = 8, retries: int = 1) -> str:
    return _http_get(url, "text/csv,text/plain,*/*", timeout, retries)
