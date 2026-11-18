"""Scoring helpers for scripts/evaluate_benchmark.py (no model or DB access).

Two SQL scores are reported side by side:

- strict: the result answers the question. Row count matches the reference,
  and every reference row's key values (``match_columns``) appear in a
  distinct result row. Column names are ignored, so ``max_eps`` matches
  ``eps``; numbers match within rounding tolerance.
- lenient (legacy): 1.0 for identical rows, 0.5 for *any* non-empty result
  when the reference is non-empty, 1.0 when both are empty. Half credit says
  nothing about whether the values are right; it is kept for comparison with
  older reports.
"""

from __future__ import annotations

import json
import math
from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def values_equal(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if _is_number(expected) and _is_number(actual):
        tol = max(0.01, abs(float(expected)) * 1e-4)
        return math.isclose(float(expected), float(actual), abs_tol=tol)
    if _is_number(expected) or _is_number(actual):
        try:
            return values_equal(float(expected), float(actual))
        except (TypeError, ValueError):
            return False
    return str(expected).strip().lower() == str(actual).strip().lower()


def key_columns(case: dict, expected_rows: list[dict]) -> list[str]:
    cols = list(case.get("match_columns") or [])
    if not cols and expected_rows:
        cols = list(expected_rows[0].keys())
    return cols


def _row_contains(actual_row: dict, wanted: list[Any]) -> bool:
    values = list(actual_row.values())
    used: set[int] = set()
    for w in wanted:
        hit = next((i for i, v in enumerate(values) if i not in used and values_equal(w, v)), None)
        if hit is None:
            return False
        used.add(hit)
    return True


def strict_match(expected_rows: list[dict], actual_rows: list[dict], columns: list[str]) -> bool:
    """True when ``actual_rows`` gives the same answer as ``expected_rows``."""
    if not expected_rows:
        return not actual_rows
    if len(actual_rows) != len(expected_rows):
        return False
    remaining = list(actual_rows)
    for exp in expected_rows:
        wanted = [exp.get(c) for c in columns]
        idx = next((i for i, row in enumerate(remaining) if _row_contains(row, wanted)), None)
        if idx is None:
            return False
        remaining.pop(idx)
    return True


def _sort_key(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=True, default=str)


def lenient_score(expected_rows: list[dict], actual_rows: list[dict] | None) -> tuple[float, str]:
    """Legacy scoring: (score, label) with label correct / partial / incorrect."""
    if actual_rows is None:
        return 0.0, "incorrect"
    if sorted(expected_rows, key=_sort_key) == sorted(actual_rows, key=_sort_key):
        return 1.0, "correct"
    if not expected_rows and not actual_rows:
        return 1.0, "correct"
    if expected_rows and actual_rows:
        return 0.5, "partial"
    return 0.0, "incorrect"


def _number_forms(value: float) -> set[str]:
    forms = {f"{value:.2f}", f"{value:,.2f}", f"{value:.1f}", f"{value:,.1f}"}
    if float(value).is_integer():
        forms |= {f"{int(value)}", f"{int(value):,}"}
    else:
        forms |= {f"{value:g}"}
    return forms


def answer_mentions(answer: str, expected_rows: list[dict], columns: list[str], max_rows: int = 20) -> bool | None:
    """Whether the answer text states every key value of the reference rows.

    None when there is nothing to check (empty reference). Only the first
    ``max_rows`` rows are checked so long lists stay comparable.
    """
    if not expected_rows:
        return None
    text = (answer or "").lower()
    for row in expected_rows[:max_rows]:
        for col in columns:
            value = row.get(col)
            if value is None:
                continue
            if _is_number(value):
                if not any(form.lower() in text for form in _number_forms(float(value))):
                    return False
            elif str(value).strip().lower() not in text:
                return False
    return True
