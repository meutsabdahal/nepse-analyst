"""IPO issues and news articles scraped from sharesansar.com."""

from __future__ import annotations

import time

import requests
from bs4 import BeautifulSoup

from nepse_analyst.config import SCRAPE_DELAY_SEC
from nepse_analyst.ingestion.parsing import extract_float, extract_int
from nepse_analyst.ingestion.records import IPOIssue, NewsArticle
from nepse_analyst.ingestion.sources.news_html import (
    HEADERS,
    CachedArticleFetcher,
    extract_news_links,
)

EXISTING_ISSUES_URL = "https://www.sharesansar.com/existing-issues"
IPO_RESULT_URL = "https://www.sharesansar.com/ipo-result"
LATEST_NEWS_URL = "https://www.sharesansar.com/category/latest?page={page}"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

# DataTables column spec the existing-issues endpoint expects.
_ISSUE_COLUMNS = [
    "DT_Row_Index", "company.symbol", "company.companyname", "ratio_value", "total_units",
    "issue_price", "price_range", "cutoff_price", "opening_date", "closing_date",
    "final_date", "listing_date", "issue_manager", "status", "view", "right_eligibility_link",
]


class SharesansarIPOSource:
    name = "sharesansar-ipo"

    def __init__(self, timeout_sec: float = 30) -> None:
        self.timeout_sec = timeout_sec
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _existing_issues(self) -> list[IPOIssue]:
        # First request sets cookies the XHR endpoint needs.
        self._session.get(EXISTING_ISSUES_URL, timeout=self.timeout_sec).raise_for_status()

        params: dict[str, str] = {
            "type": "1", "draw": "1", "start": "0", "length": "500",
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "0", "order[0][dir]": "asc",
        }
        for idx, key in enumerate(_ISSUE_COLUMNS):
            params[f"columns[{idx}][data]"] = key
            params[f"columns[{idx}][name]"] = ""
            params[f"columns[{idx}][searchable]"] = "true"
            params[f"columns[{idx}][orderable]"] = "false"
            params[f"columns[{idx}][search][value]"] = ""
            params[f"columns[{idx}][search][regex]"] = "false"

        resp = self._session.get(
            EXISTING_ISSUES_URL,
            params=params,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=self.timeout_sec,
        )
        try:
            rows = resp.json().get("data") or []
        except Exception:
            rows = []

        issues: list[IPOIssue] = []
        for row in rows:
            company = row.get("company") or {}
            issues.append(
                IPOIssue(
                    company_name=str(company.get("companyname") or "").strip(),
                    symbol=str(company.get("symbol") or "").strip().upper() or None,
                    issue_date=str(row.get("opening_date") or "").strip() or None,
                    listing_date=str(row.get("listing_date") or "").strip() or None,
                    issue_price=extract_float(row.get("issue_price")),
                    shares_issued=extract_int(row.get("total_units")),
                    oversubscription_rate=extract_float(row.get("ratio_value")),
                )
            )
        return issues

    def _ipo_result_names(self) -> list[IPOIssue]:
        page = self._session.get(IPO_RESULT_URL, timeout=self.timeout_sec)
        page.raise_for_status()
        select_tag = BeautifulSoup(page.text, "lxml").select_one("select#companyid")
        if not select_tag:
            return []
        return [
            IPOIssue(company_name=name, issue_price=100.0)
            for option in select_tag.select("option")
            if (name := option.get_text(strip=True))
        ]

    def fetch_ipos(self) -> list[IPOIssue]:
        return self._existing_issues() or self._ipo_result_names()

    def close(self) -> None:
        self._session.close()


class SharesansarNewsSource:
    name = "sharesansar"

    def __init__(
        self,
        max_pages: int = 100,
        delay_sec: float = SCRAPE_DELAY_SEC,
        fetcher: CachedArticleFetcher | None = None,
    ) -> None:
        self.max_pages = max_pages
        self.delay_sec = delay_sec
        self.fetcher = fetcher or CachedArticleFetcher(delay_sec=delay_sec)

    def article_urls(self) -> list[str]:
        urls: set[str] = set()
        empty_streak = 0
        for page in range(1, self.max_pages + 1):
            listing_url = LATEST_NEWS_URL.format(page=page)
            try:
                resp = requests.get(listing_url, headers=HEADERS, timeout=20)
                resp.raise_for_status()
            except Exception as exc:
                print(f"Sharesansar error on page {page}: {exc}")
                time.sleep(self.delay_sec * 2)
                continue

            page_links = extract_news_links(
                soup=BeautifulSoup(resp.text, "lxml"),
                base_url=listing_url,
                allowed_domains=("sharesansar.com",),
                selectors=("a.news-title[href]", "h4 a[href]", "h3 a[href]", "article a[href]", ".media a[href]"),
                path_keywords=("news", "detail", "article", "announcement"),
            )
            if page_links:
                empty_streak = 0
                urls.update(page_links)
                print(f"Sharesansar page {page}: +{len(page_links)} links (total: {len(urls)})")
            else:
                empty_streak += 1
                print(f"Sharesansar page {page}: 0 links")
                if empty_streak >= 3:
                    print("Stopping Sharesansar pagination after 3 empty pages.")
                    break
            time.sleep(self.delay_sec)
        return sorted(urls)

    def fetch_news(self, limit: int | None = None) -> list[NewsArticle]:
        urls = self.article_urls()
        if limit is not None:
            urls = urls[:limit]
        return [a for url in urls if (a := self.fetcher.fetch(url, self.name))]
