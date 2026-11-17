"""Price source backed by community CSV dumps on GitHub."""

from __future__ import annotations

import csv
import io

from nepse_analyst.ingestion.parsing import (
    canonical_index_name,
    first_non_null,
    http_get_json,
    http_get_text,
    normalize_rows,
    price_bars_from_records,
    to_float,
    to_iso_date,
)
from nepse_analyst.ingestion.records import IndexBar, PriceBar

COMPANY_WISE_URL = (
    "https://api.github.com/repos/Aabishkar2/nepse-data/contents/data/company-wise"
)
INDEX_DAILY_URL = (
    "https://api.github.com/repos/socrateai-official/nepse-open-data/contents/ohlc_index"
)
DEFAULT_INDEX_TARGET_DAYS = {"NEPSE": 300, "Banking": 300, "Hydropower": 50}


class GitHubOpenDataSource:
    name = "github-open-data"

    def __init__(
        self,
        company_wise_url: str = COMPANY_WISE_URL,
        index_daily_url: str = INDEX_DAILY_URL,
        index_target_days: dict[str, int] | None = None,
        max_index_files: int = 120,
    ) -> None:
        self.company_wise_url = company_wise_url
        self.index_daily_url = index_daily_url
        self.index_target_days = index_target_days or dict(DEFAULT_INDEX_TARGET_DAYS)
        self.max_index_files = max_index_files
        self._symbol_files: dict[str, str] | None = None
        self._index_files: list[str] | None = None

    def _symbol_file_map(self) -> dict[str, str]:
        if self._symbol_files is None:
            mapping: dict[str, str] = {}
            for item in normalize_rows(http_get_json(self.company_wise_url)):
                name = str(first_non_null(item, ["name"], "")).strip()
                url = first_non_null(item, ["download_url", "downloadUrl"])
                if name.lower().endswith(".csv") and url:
                    mapping[name[:-4].upper()] = str(url)
            self._symbol_files = mapping
        return self._symbol_files

    def _index_file_urls(self) -> list[str]:
        if self._index_files is None:
            urls: list[str] = []
            for item in normalize_rows(http_get_json(self.index_daily_url)):
                name = str(first_non_null(item, ["name"], "")).strip()
                url = first_non_null(item, ["download_url", "downloadUrl"])
                if name.startswith("adj_") and name.endswith(".csv") and url:
                    urls.append(str(url))
            urls.sort(reverse=True)  # newest first, so we can stop early
            self._index_files = urls
        return self._index_files

    def available(self) -> bool:
        try:
            return len(self._symbol_file_map()) > 0
        except Exception:
            return False

    def fetch_price_history(self, symbol: str) -> list[PriceBar]:
        csv_url = self._symbol_file_map().get(symbol.upper())
        if not csv_url:
            return []
        rows = [
            {
                "date": row.get("published_date"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("traded_quantity"),
                "turnover": row.get("traded_amount"),
            }
            for row in csv.DictReader(io.StringIO(http_get_text(csv_url)))
        ]
        return price_bars_from_records(symbol, rows)

    def fetch_index_history(self) -> list[IndexBar]:
        seen: dict[str, set[str]] = {name: set() for name in self.index_target_days}
        bars: list[IndexBar] = []
        for csv_url in self._index_file_urls()[: self.max_index_files]:
            for item in csv.DictReader(io.StringIO(http_get_text(csv_url))):
                index_name = canonical_index_name(item.get("symbol"))
                if index_name not in seen:
                    continue
                trade_date = to_iso_date(item.get("date"))
                close_value = to_float(item.get("close"))
                if trade_date is None or close_value is None or trade_date in seen[index_name]:
                    continue
                open_value = to_float(item.get("open"))
                bars.append(
                    IndexBar(
                        trade_date=trade_date,
                        index_name=index_name,
                        close_value=close_value,
                        open_value=open_value,
                        change_points=None if open_value is None else close_value - open_value,
                        change_percent=(
                            None
                            if open_value in (None, 0)
                            else (close_value - open_value) / open_value * 100.0
                        ),
                        turnover=to_float(item.get("volume")),
                    )
                )
                seen[index_name].add(trade_date)
            if all(len(seen[n]) >= self.index_target_days[n] for n in seen):
                break
        return bars
