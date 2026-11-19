"""Company list, fundamentals and dividends scraped from merolagani.com.

Respectful scraping: pacing between requests and a local HTML cache, so
re-runs only hit the network for symbols that have not been fetched yet.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from nepse_analyst import sectors
from nepse_analyst.config import NEWS_CACHE_DIR, SCRAPE_DELAY_SEC
from nepse_analyst.ingestion.parsing import extract_float, extract_int, normalize_ws
from nepse_analyst.ingestion.records import Company, Dividend, Fundamental

BASE_URL = "https://merolagani.com/CompanyDetail.aspx"
COMPANY_LIST_URL = "https://merolagani.com/CompanyList.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FUNDAMENTAL_KEYWORDS = {
    "eps": ["eps", "earning per share", "earnings per share"],
    "pe_ratio": ["p/e", "p e ratio", "pe ratio", "price earnings"],
    "book_value": ["book value", "book value per share", "bvps"],
    "roe": ["roe", "return on equity"],
    "net_profit": ["net profit", "profit after tax", "pat"],
    "total_assets": ["total assets", "asset"],
    "revenue": ["revenue", "turnover", "income"],
}
DIVIDEND_TABLE_HINTS = ["dividend", "bonus", "book close", "announced", "distribution"]
_FUNDAMENTAL_FIELDS = list(FUNDAMENTAL_KEYWORDS)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", (text or "").lower()).strip()


def _normalize_year_token(tok: str) -> int | None:
    tok = tok.strip()
    if not tok.isdigit():
        return None
    n = int(tok)
    if len(tok) == 4:
        return n
    if len(tok) == 3:
        return 2000 + n  # merolagani shorthand like 082-083 for 2082/83
    if len(tok) == 2 and n >= 70:
        return 2000 + n  # conservative: avoid Gregorian month false positives
    return None


def normalize_fiscal_year(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = normalize_ws(text)
    m = re.search(r"(?:FY\s*[:\-]?\s*)?(\d{2,4})\s*[/\-]\s*(\d{2,4})", cleaned, flags=re.I)
    if m:
        left = _normalize_year_token(m.group(1))
        right = _normalize_year_token(m.group(2))
        if left is not None and right is not None:
            return f"{left:04d}/{right % 100:02d}"
    m2 = re.search(r"FY\s*[:\-]?\s*(\d{2,4})", cleaned, flags=re.I)
    if m2:
        left = _normalize_year_token(m2.group(1))
        if left is not None:
            return f"{left:04d}/{(left + 1) % 100:02d}"
    return None


def extract_fiscal_year_from_text(text: str | None) -> str | None:
    if not text:
        return None
    fy = normalize_fiscal_year(text)
    if fy:
        return fy
    if "fy" in text.lower():
        m = re.search(r"(\d{2,4}\s*[/\-]\s*\d{2,4})", text)
        if m:
            return normalize_fiscal_year(f"FY:{m.group(1)}")
    return None


def _metric_key(row_label: str) -> str | None:
    s = slug(row_label)
    for key, variants in FUNDAMENTAL_KEYWORDS.items():
        if any(v in s for v in variants):
            return key
    return None


def _table_matrix(table_tag: Any) -> tuple[list[str], list[list[str]]]:
    matrix: list[list[str]] = []
    for r in table_tag.find_all("tr"):
        vals = [normalize_ws(c.get_text(" ", strip=True)) for c in r.find_all(["th", "td"])]
        if any(vals):
            matrix.append(vals)
    if not matrix:
        return [], []
    return matrix[0], matrix[1:]


def parse_fundamentals(soup: BeautifulSoup, symbol: str) -> list[Fundamental]:
    by_fy: dict[str, dict[str, Any]] = {}
    default_fy: str | None = None

    # 1) Key/value rows in the main accordion summary table.
    acc = soup.find("table", id="accordion")
    if acc:
        for tr in acc.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = normalize_ws(cells[0].get_text(" ", strip=True))
            value_text = normalize_ws(cells[1].get_text(" ", strip=True))
            mk = _metric_key(label)
            if not mk:
                continue
            row_fy = extract_fiscal_year_from_text(value_text)
            if mk == "eps" and row_fy:
                default_fy = row_fy
            fy = row_fy or default_fy
            if not fy:
                continue
            by_fy.setdefault(fy, {})[mk] = extract_float(value_text)

    # 2) Wide tables with one column per fiscal year.
    for table in soup.find_all("table"):
        header, body = _table_matrix(table)
        if len(header) < 2:
            continue
        fiscal_cols = [
            (idx, fy)
            for idx, col in enumerate(header[1:], start=1)
            if (fy := extract_fiscal_year_from_text(col))
        ]
        for _, fy in fiscal_cols:
            by_fy.setdefault(fy, {})
        for row in body:
            if len(row) < 2:
                continue
            mk = _metric_key(row[0])
            if not mk:
                continue
            for col_idx, fy in fiscal_cols:
                if col_idx < len(row):
                    val = extract_float(row[col_idx])
                    if val is not None:
                        by_fy[fy][mk] = val

    return [
        Fundamental(symbol=symbol, fiscal_year=fy, **{k: vals.get(k) for k in _FUNDAMENTAL_FIELDS})
        for fy, vals in sorted(by_fy.items(), reverse=True)
    ]


def _col_index(header: list[str], *needles: str) -> int | None:
    """Index of the first header cell containing any of ``needles``."""
    for i, name in enumerate(header):
        if any(n in name for n in needles):
            return i
    return None


_ROW_NUMBER = re.compile(r"^\d+\.?$")


def _panel_row(cells: list[str]) -> tuple[str | None, float | None]:
    """(fiscal year, value) from a dividend/bonus history panel row.

    The cells are [row number, value, "(FY: 082-083)"]; the panel's header labels
    ("#, Fiscal Year, Value") do not match them, so cells are read by content.
    The row number ("1.") must be skipped: reading it as the value stored 1, 2,
    3... as every company's dividend history.
    """
    fy = None
    value = None
    for cell in cells:
        if _ROW_NUMBER.match(cell):
            continue
        cell_fy = extract_fiscal_year_from_text(cell)
        if cell_fy:
            fy = fy or cell_fy
        elif value is None and re.search(r"\d", cell):
            value = extract_float(cell)
    return fy, value


def parse_dividends(soup: BeautifulSoup, symbol: str) -> list[Dividend]:
    by_fy: dict[str, dict[str, Any]] = {}

    def upsert(fy: str, field: str, val: Any) -> None:
        rec = by_fy.setdefault(fy, {})
        if val is not None:
            rec[field] = val

    acc = soup.find("table", id="accordion")
    if acc:
        # 1) Summary rows: "% Dividend", "% Bonus" with inline FY.
        for tr in acc.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = slug(cells[0].get_text(" ", strip=True))
            value_text = normalize_ws(cells[1].get_text(" ", strip=True))
            fy = extract_fiscal_year_from_text(value_text)
            if not fy:
                continue
            if "dividend" in label:
                upsert(fy, "cash_dividend", extract_float(value_text))
            elif "bonus" in label:
                upsert(fy, "bonus_shares", extract_float(value_text))

        # 2) Collapsed history panels.
        for panel_id, field in (("dividend-panel", "cash_dividend"), ("bonus-panel", "bonus_shares")):
            panel = acc.find("tr", id=panel_id)
            if not panel:
                continue
            # Rows are newest first, and a year is often listed twice, the second
            # time as 0.00%. A zero never replaces a value already read for that
            # year; between two values, the first (newest) wins.
            panel_values: dict[str, float] = {}
            for r in panel.find_all("tr"):
                vals = [normalize_ws(c.get_text(" ", strip=True)) for c in r.find_all(["th", "td"])]
                if not vals or any(v.lower() in {"#", "value", "fiscal year"} for v in vals):
                    continue
                fy, num = _panel_row(vals)
                if not fy or num is None:
                    continue
                if fy not in panel_values or (panel_values[fy] == 0 and num != 0):
                    panel_values[fy] = num
            for fy, num in panel_values.items():
                upsert(fy, field, num)

    # 3) Generic dividend-like tables with FY/value columns.
    for table in soup.find_all("table"):
        table_text = slug(table.get_text(" ", strip=True))
        if not any(hint in table_text for hint in DIVIDEND_TABLE_HINTS):
            continue
        header, body = _table_matrix(table)
        if not header or not body:
            continue
        hdr = [slug(h) for h in header]
        fy_idx = _col_index(hdr, "fiscal year", "fy")
        val_idx = _col_index(hdr, "value", "cash", "dividend", "bonus", "stock")
        if fy_idx is None or val_idx is None:
            continue
        field = "bonus_shares" if "bonus" in table_text else "cash_dividend"
        for row in body:
            if fy_idx >= len(row) or val_idx >= len(row):
                continue
            fy = extract_fiscal_year_from_text(row[fy_idx])
            if fy:
                upsert(fy, field, extract_float(row[val_idx]))

    return [
        Dividend(symbol=symbol, fiscal_year=fy, **vals)
        for fy, vals in sorted(by_fy.items(), reverse=True)
    ]


def _positive(value: float | int | None) -> float | int | None:
    return value if value is not None and value > 0 else None


def parse_company_list(soup: BeautifulSoup) -> list[Company]:
    """Every listed security on CompanyList.aspx, one collapsible panel per sector.

    Raises on a sector label that ``sectors.LISTING_SECTOR_LABELS`` does not know,
    so a new label is added deliberately instead of landing under a raw name.
    """
    companies: dict[str, Company] = {}
    unknown: set[str] = set()
    for panel in soup.select("div.panel"):
        title = panel.select_one(".panel-title")
        table = panel.find("table")
        if not title or not table:
            continue  # sectors with no companies render a "Could not find" note instead
        label = normalize_ws(title.get_text(" ", strip=True))
        for tr in table.find_all("tr"):
            cells = [normalize_ws(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if len(cells) < 2 or not cells[0]:
                continue  # header row uses <th>
            symbol, name = cells[0].upper(), cells[1]
            sector = sectors.sector_from_listing(label, name)
            if sector is None:
                unknown.add(label)
                continue
            companies.setdefault(symbol, Company(
                symbol=symbol,
                name=name,
                sector=sector,
                listed_shares=_positive(extract_int(cells[2])) if len(cells) > 2 else None,
                paid_up_value=_positive(extract_float(cells[3])) if len(cells) > 3 else None,
                total_paid_up=_positive(extract_float(cells[4])) if len(cells) > 4 else None,
            ))
    if unknown:
        raise ValueError(f"Unmapped sector labels on {COMPANY_LIST_URL}: {sorted(unknown)}")
    return list(companies.values())


class MerolaganiCompanySource:
    """Live company list: what is listed today, with current share counts."""

    name = "merolagani-company-list"

    def __init__(self, timeout_sec: float = 30) -> None:
        self.timeout_sec = timeout_sec

    def fetch_companies(self) -> list[Company]:
        resp = requests.get(COMPANY_LIST_URL, headers=HEADERS, timeout=self.timeout_sec)
        resp.raise_for_status()
        return parse_company_list(BeautifulSoup(resp.text, "html.parser"))


class MerolaganiSource:
    name = "merolagani"

    def __init__(
        self,
        cache_dir: str | Path = NEWS_CACHE_DIR,
        delay_sec: float = SCRAPE_DELAY_SEC,
        timeout_sec: float = 20,
        force_refresh: bool = False,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.delay_sec = delay_sec
        self.timeout_sec = timeout_sec
        self.force_refresh = force_refresh
        self._session = requests.Session()
        self._last_request_ts: float | None = None

    def fetch_html(self, symbol: str) -> str:
        cache_path = self.cache_dir / f"merolagani_{symbol.upper()}.html"
        if cache_path.exists() and not self.force_refresh:
            return cache_path.read_text(encoding="utf-8", errors="ignore")

        if self._last_request_ts is not None:
            wait = self.delay_sec - (time.time() - self._last_request_ts)
            if wait > 0:
                time.sleep(wait)
        url = f"{BASE_URL}?{urlencode({'symbol': symbol.upper()})}"
        resp = self._session.get(url, headers=HEADERS, timeout=self.timeout_sec)
        self._last_request_ts = time.time()
        resp.raise_for_status()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(resp.text, encoding="utf-8")
        return resp.text

    def fetch_fundamentals(self, symbol: str) -> tuple[list[Fundamental], list[Dividend]]:
        soup = BeautifulSoup(self.fetch_html(symbol), "html.parser")
        return parse_fundamentals(soup, symbol), parse_dividends(soup, symbol)

    def close(self) -> None:
        self._session.close()
