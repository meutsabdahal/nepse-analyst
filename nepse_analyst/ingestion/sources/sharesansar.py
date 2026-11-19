"""IPO issues and news articles scraped from sharesansar.com."""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from nepse_analyst.config import SCRAPE_DELAY_SEC
from nepse_analyst.ingestion.parsing import extract_float, extract_int
from nepse_analyst.ingestion.records import IPOIssue, NewsArticle
from nepse_analyst.ingestion.sources.news_html import HEADERS, CachedArticleFetcher

EXISTING_ISSUES_URL = "https://www.sharesansar.com/existing-issues"
IPO_RESULT_URL = "https://www.sharesansar.com/ipo-result"
LATEST_NEWS_URL = "https://www.sharesansar.com/category/latest"
LISTING_ITEM_SELECTOR = "div.featured-news-list a[href]"
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
                    # ratio_value is the rights-share ratio, not oversubscription; this
                    # feed has no applicant counts, so oversubscription stays unknown.
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
    """Walks the "Latest" category newest-first by following its cursor links.

    The listing paginates with an opaque ``cursor`` query parameter exposed on
    the ``rel="next"`` link; ``?page=N`` alone is ignored and always returns
    the first page. Links are taken only from the main list
    (``div.featured-news-list``) so the site menu's old evergreen articles are
    not picked up.
    """

    name = "sharesansar"

    def __init__(
        self,
        max_pages: int = 100,
        delay_sec: float = SCRAPE_DELAY_SEC,
        fetcher: CachedArticleFetcher | None = None,
        get_html: Callable[[str], str] | None = None,
    ) -> None:
        self.max_pages = max_pages
        self.delay_sec = delay_sec
        self.fetcher = fetcher or CachedArticleFetcher(delay_sec=delay_sec)
        self._get_html = get_html or _http_get_html

    def article_urls(self, limit: int | None = None) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        listing_url: str | None = LATEST_NEWS_URL
        page = 0
        while listing_url and page < self.max_pages:
            page += 1
            try:
                html = self._get_html(listing_url)
            except Exception as exc:
                print(f"WARNING: Sharesansar listing page {page} failed ({exc}); stopping pagination.")
                break

            soup = BeautifulSoup(html, "lxml")
            page_links = parse_listing_links(soup, listing_url)
            if not page_links:
                if page == 1:
                    raise RuntimeError(
                        f"Sharesansar listing {listing_url} has no items under "
                        f"'{LISTING_ITEM_SELECTOR}'; the page layout may have changed."
                    )
                print(f"WARNING: Sharesansar page {page} has no list items; stopping pagination.")
                break

            new_links = [u for u in page_links if u not in seen]
            if not new_links:
                print(f"WARNING: Sharesansar page {page} repeated earlier links; stopping pagination.")
                break
            seen.update(new_links)
            urls.extend(new_links)
            print(f"Sharesansar page {page}: +{len(new_links)} links (total: {len(urls)})")
            if limit is not None and len(urls) >= limit:
                break

            listing_url = next_listing_url(soup, listing_url)
            if listing_url:
                time.sleep(self.delay_sec)
        return urls[:limit] if limit is not None else urls

    def fetch_news(self, limit: int | None = None) -> list[NewsArticle]:
        urls = self.article_urls(limit=limit)
        return [a for url in urls if (a := self.fetcher.fetch(url, self.name))]


def parse_listing_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Article URLs from the main list, in page order (newest first)."""
    links: list[str] = []
    for a in soup.select(LISTING_ITEM_SELECTOR):
        url = urljoin(base_url, (a.get("href") or "").strip())
        if "/newsdetail/" in urlparse(url).path and url not in links:
            links.append(url)
    return links


def next_listing_url(soup: BeautifulSoup, base_url: str) -> str | None:
    nxt = soup.select_one("ul.pagination a[rel=next][href]") or soup.select_one("a[rel=next][href]")
    return urljoin(base_url, nxt["href"]) if nxt else None


def _http_get_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text
