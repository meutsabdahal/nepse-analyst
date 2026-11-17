"""Price source backed by community CSV dumps on GitHub."""

from __future__ import annotations

import csv
import io

from nepse_analyst.ingestion.parsing import (
    canonical_index_name,
    http_get_json,
    http_get_text,
    price_bars_from_records,
    to_float,
    to_iso_date,
)
from nepse_analyst.ingestion.records import IndexBar, PriceBar

COMPANY_WISE_DIR = ("Aabishkar2/nepse-data", "data/company-wise")
INDEX_DAILY_DIR = ("socrateai-official/nepse-open-data", "ohlc_index")
DEFAULT_INDEX_TARGET_DAYS = {"NEPSE": 300, "Banking": 300, "Hydropower": 50}


def list_github_dir(repo: str, path: str, ref: str = "HEAD") -> dict[str, str]:
    """Return {file name: raw download URL} for every file directly under ``path``.

    Uses the git trees API, not the contents API: the contents API silently
    stops at 1,000 entries, which cut the daily index files off at 2007.
    """
    payload = http_get_json(
        f"https://api.github.com/repos/{repo}/git/trees/{ref}:{path}", timeout=30
    )
    if payload.get("truncated"):
        print(f"WARNING: GitHub tree listing for {repo}/{path} was truncated")
    return {
        entry["path"]: f"https://raw.githubusercontent.com/{repo}/{ref}/{path}/{entry['path']}"
        for entry in payload.get("tree", [])
        if entry.get("type") == "blob"
    }


class GitHubOpenDataSource:
    name = "github-open-data"

    def __init__(
        self,
        company_wise_dir: tuple[str, str] = COMPANY_WISE_DIR,
        index_daily_dir: tuple[str, str] = INDEX_DAILY_DIR,
        index_target_days: dict[str, int] | None = None,
        max_index_files: int = 400,
    ) -> None:
        self.company_wise_dir = company_wise_dir
        self.index_daily_dir = index_daily_dir
        self.index_target_days = index_target_days or dict(DEFAULT_INDEX_TARGET_DAYS)
        # One file per trading day; must exceed the largest target or it is unreachable.
        self.max_index_files = max_index_files
        self._symbol_files: dict[str, str] | None = None
        self._index_files: list[str] | None = None

    def _symbol_file_map(self) -> dict[str, str]:
        if self._symbol_files is None:
            self._symbol_files = {
                name[:-4].upper(): url
                for name, url in list_github_dir(*self.company_wise_dir).items()
                if name.lower().endswith(".csv")
            }
        return self._symbol_files

    def _index_file_urls(self) -> list[str]:
        if self._index_files is None:
            files = list_github_dir(*self.index_daily_dir)
            # adj_YYYY-MM-DD.csv: reverse name order is newest first, so we can stop early.
            self._index_files = [
                files[name]
                for name in sorted(files, reverse=True)
                if name.startswith("adj_") and name.endswith(".csv")
            ]
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
