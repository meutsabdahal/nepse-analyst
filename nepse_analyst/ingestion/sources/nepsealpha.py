"""News articles scraped from NepseAlpha (both known domains)."""

from __future__ import annotations

import time

import requests
from bs4 import BeautifulSoup

from nepse_analyst.config import SCRAPE_DELAY_SEC
from nepse_analyst.ingestion.records import NewsArticle
from nepse_analyst.ingestion.sources.news_html import (
    HEADERS,
    CachedArticleFetcher,
    extract_news_links,
)

LISTING_PATTERNS = (
    "https://www.nepsealpha.com/news/page/{page}/",
    "https://www.nepsealpha.com/category/news/page/{page}/",
    "https://www.nepse-alpha.com/news/page/{page}/",
)


class NepseAlphaNewsSource:
    name = "nepse_alpha"

    def __init__(
        self,
        max_pages: int = 30,
        delay_sec: float = SCRAPE_DELAY_SEC,
        fetcher: CachedArticleFetcher | None = None,
    ) -> None:
        self.max_pages = max_pages
        self.delay_sec = delay_sec
        self.fetcher = fetcher or CachedArticleFetcher(delay_sec=delay_sec)

    def _listing_page(self, page: int) -> tuple[str, str] | None:
        for pattern in LISTING_PATTERNS:
            url = pattern.format(page=page)
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
            except Exception:
                continue
            if r.status_code == 200 and "<html" in r.text.lower():
                return url, r.text
        return None

    def article_urls(self) -> list[str]:
        urls: set[str] = set()
        empty_streak = 0
        for page in range(1, self.max_pages + 1):
            listing = self._listing_page(page)
            page_links: list[str] = []
            if listing is None:
                print(f"NepseAlpha page {page}: no reachable listing URL")
            else:
                listing_url, html = listing
                page_links = extract_news_links(
                    soup=BeautifulSoup(html, "lxml"),
                    base_url=listing_url,
                    allowed_domains=("nepsealpha.com", "nepse-alpha.com"),
                    selectors=("article a[href]", "h2 a[href]", "h3 a[href]", ".post a[href]", ".news a[href]"),
                    path_keywords=("news", "announcement", "market", "article"),
                )
                if not page_links:
                    print(f"NepseAlpha page {page}: 0 links")

            if page_links:
                empty_streak = 0
                urls.update(page_links)
                print(f"NepseAlpha page {page}: +{len(page_links)} links (total: {len(urls)})")
            else:
                empty_streak += 1
                if empty_streak >= 3:
                    print("Stopping NepseAlpha pagination after 3 empty pages.")
                    break
            if listing is not None:
                time.sleep(self.delay_sec)
        return sorted(urls)

    def fetch_news(self, limit: int | None = None) -> list[NewsArticle]:
        urls = self.article_urls()
        if limit is not None:
            urls = urls[:limit]
        return [a for url in urls if (a := self.fetcher.fetch(url, self.name))]
