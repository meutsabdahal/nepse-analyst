"""Unofficial NEPSE API price source.

Reads the community HTTP mirror of NepseUnofficialApi at nepseapi.surajrimal.dev.
It is not an official, stable API. Replace this class with another
``PriceSource`` when an official feed is available.

The ``nepse-api`` package client this source used to try first targeted
newweb.nepalstock.com, which no longer resolves; it was removed along with
the package (its httpx<0.19 pin blocked upgrading chromadb).
"""

from __future__ import annotations

import time
from typing import Any

from nepse_analyst.ingestion.parsing import (
    first_non_null,
    http_get_json,
    normalize_rows,
    price_bars_from_records,
    to_float,
    to_iso_date,
)
from nepse_analyst.ingestion.records import IndexBar, PriceBar

DEFAULT_MIRROR_BASE = "https://nepseapi.surajrimal.dev"
PROBE_SYMBOL = "ADBL"

_INDEX_ENDPOINTS = {
    "NEPSE": "/DailyNepseIndexGraph",
    "Banking": "/DailyBankSubindexGraph",
    "Hydropower": "/DailyHydroPowerSubindexGraph",
}


def index_bars_from_records(records: list[Any], index_name: str) -> list[IndexBar]:
    out: list[IndexBar] = []
    for rec in records:
        trade_date = to_iso_date(
            first_non_null(rec, ["business_date", "businessDate", "trade_date", "tradeDate", "date"])
        )
        close_value = to_float(
            first_non_null(
                rec,
                ["close_value", "closeValue", "close_price", "closePrice", "close", "index", "value", "ltp"],
            )
        )
        if trade_date is None or close_value is None:
            continue
        open_value = to_float(
            first_non_null(rec, ["open_value", "openValue", "open_price", "openPrice", "open"])
        )
        change_points = to_float(
            first_non_null(rec, ["change_points", "changePoints", "point_change", "change"])
        )
        change_percent = to_float(
            first_non_null(rec, ["change_percent", "changePercent", "percentage_change", "percent_change"])
        )
        turnover = to_float(
            first_non_null(
                rec,
                ["turnover", "turnOver", "total_turnover", "totalTurnover", "turn_over", "turnOverValues"],
            )
        )
        if change_points is None and open_value is not None:
            change_points = close_value - open_value
        if change_percent is None and open_value not in (None, 0):
            change_percent = ((close_value - open_value) / open_value) * 100.0
        out.append(
            IndexBar(
                trade_date=trade_date,
                index_name=index_name,
                close_value=close_value,
                open_value=open_value,
                change_points=change_points,
                change_percent=change_percent,
                turnover=turnover,
            )
        )
    return out


class NepseApiSource:
    name = "nepse-api"

    def __init__(
        self,
        mirror_base: str = DEFAULT_MIRROR_BASE,
        min_request_interval_sec: float = 1.0,
        timeout_sec: float = 8,
    ) -> None:
        self.mirror_base = mirror_base.rstrip("/")
        self.min_request_interval_sec = min_request_interval_sec
        self.timeout_sec = timeout_sec
        # None = untested; True/False = result of available().
        self._mirror_ok: bool | None = None
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        wait = self.min_request_interval_sec - (time.monotonic() - self._last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _history_via_mirror(self, symbol: str) -> list[Any]:
        payload = http_get_json(
            f"{self.mirror_base}/PriceVolumeHistory",
            params={"symbol": symbol},
            timeout=self.timeout_sec,
        )
        return normalize_rows(payload)

    # -- PriceSource ------------------------------------------------------
    def available(self) -> bool:
        try:
            self._mirror_ok = len(self._history_via_mirror(PROBE_SYMBOL)) > 0
        except Exception:
            self._mirror_ok = False
        return self._mirror_ok

    def fetch_price_history(self, symbol: str) -> list[PriceBar]:
        if self._mirror_ok is False:
            return []
        try:
            self._throttle()
            rows = self._history_via_mirror(symbol)
        except Exception:
            rows = []
        return price_bars_from_records(symbol, rows)

    def fetch_index_history(self) -> list[IndexBar]:
        bars: list[IndexBar] = []
        for index_name, endpoint in _INDEX_ENDPOINTS.items():
            try:
                payload = http_get_json(f"{self.mirror_base}{endpoint}", timeout=self.timeout_sec)
                bars.extend(index_bars_from_records(normalize_rows(payload), index_name))
            except Exception as exc:
                print(f"[{self.name}] {index_name} index via {endpoint} failed: {exc}")
        return bars
