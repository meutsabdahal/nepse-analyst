"""Numbers the way Nepali investors read them.

Large amounts in lakh and crore ("Rs 4.2 crore", not "Rs 42,000,000"); per-share
prices in plain rupees ("Rs 549"); percentages with a sign ("12.5%").
"""

from __future__ import annotations

LAKH = 100_000
CRORE = 10_000_000


def _trim(value: float, decimals: int) -> str:
    """Fixed decimals with trailing zeros removed: 4.20 -> "4.2", 549.00 -> "549"."""
    text = f"{value:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _scaled(value: float) -> str:
    # Three significant figures for small multiples, whole numbers past 100.
    decimals = 2 if value < 10 else 1 if value < 100 else 0
    return _trim(value, decimals)


def rupees(value: float | int | None) -> str | None:
    """A per-share price or other small amount: "Rs 549", "Rs 33.89"."""
    if value is None:
        return None
    return f"Rs {_trim(float(value), 2)}"


def rupee_amount(value: float | int | None) -> str | None:
    """A large amount in lakh or crore: "Rs 85,000", "Rs 4.2 lakh", "Rs 14,854 crore"."""
    if value is None:
        return None
    amount = float(value)
    sign, amount = ("-", -amount) if amount < 0 else ("", amount)
    # 99.99 lakh would round to "100 lakh"; that is 1 crore.
    if amount >= CRORE or round(amount / LAKH, 1) >= 100:
        return f"{sign}Rs {_scaled(amount / CRORE)} crore"
    if amount >= LAKH:
        return f"{sign}Rs {_scaled(amount / LAKH)} lakh"
    return f"{sign}Rs {_trim(amount, 0)}"


def percent(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{_trim(float(value), 2)}%"


def plain(value: float | int | None) -> str | None:
    if value is None:
        return None
    return _trim(float(value), 2)
