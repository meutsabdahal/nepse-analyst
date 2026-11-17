"""Shared helpers for scraping news listing and article pages."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from nepse_analyst.config import NEWS_CACHE_DIR, SCRAPE_DELAY_SEC
from nepse_analyst.ingestion.records import NewsArticle

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

_TITLE_SELECTORS = (
    "h1.news-heading", "h1.entry-title", "h1.post-title",
    "article h1", "section.main-content h1", "h1",
)
_CONTENT_SELECTORS = (
    "div.news-content", "div.entry-content", "div.post-content", "div.text-justify",
    "section.main-content", "article .content", "article",
)
_DATE_SELECTORS = (
    "span.news-date", "time", ".entry-date", "section.main-content time",
    "meta[property='article:published_time']", "meta[name='pubdate']",
)
_DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%a, %b %d, %Y")
_NOISE = ("Login", "Register", "Contact Us", "Write For Us", "Home News", "Latest Share Price")


def extract_news_links(
    soup: BeautifulSoup,
    base_url: str,
    allowed_domains: tuple[str, ...],
    selectors: tuple[str, ...],
    path_keywords: tuple[str, ...],
) -> list[str]:
    anchors = [a for sel in selectors for a in soup.select(sel)] or soup.select("a[href]")
    links: set[str] = set()
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        path = parsed.path.lower()
        if not any(d in parsed.netloc for d in allowed_domains):
            continue
        if not any(k in path for k in path_keywords):
            continue
        # Keep detail pages; drop listing/category pages.
        if "category" in path or "page/" in path:
            continue
        if path.rstrip("/") in ("", "/news", "/latest", "/announcement", "/news-page"):
            continue
        if "sharesansar.com" in parsed.netloc and "/newsdetail/" not in path:
            continue
        links.add(abs_url)
    return sorted(links)


def _first_match(soup: BeautifulSoup, selectors: tuple[str, ...]):
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None


def parse_article_html(html: str, url: str, source: str) -> NewsArticle | None:
    soup = BeautifulSoup(html, "lxml")
    title_el = _first_match(soup, _TITLE_SELECTORS)
    content_el = _first_match(soup, _CONTENT_SELECTORS)
    if not title_el or not content_el:
        return None

    title = title_el.get_text(strip=True)
    paragraphs = [p.get_text(" ", strip=True) for p in content_el.select("p") if p.get_text(strip=True)]
    content = " ".join(paragraphs) if paragraphs else content_el.get_text(" ", strip=True)
    for noise in _NOISE:
        content = content.replace(noise, " ")
    content = " ".join(content.split())
    if len(content) < 80:
        return None

    published_at = ""
    date_el = _first_match(soup, _DATE_SELECTORS)
    if date_el:
        raw = date_el.get("content", "").strip() if date_el.name == "meta" else date_el.get_text(strip=True)
        raw = raw.split("T")[0] if "T" in raw else raw
        for fmt in _DATE_FORMATS:
            try:
                published_at = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    try:
        from nepse_analyst.language_detector import detect_language

        language = detect_language(title + " " + content[:200])
    except Exception:
        language = "unknown"

    return NewsArticle(
        url=url, source=source, title=title, content=content,
        published_at=published_at, language=language,
    )


class CachedArticleFetcher:
    """Fetch article HTML through an on-disk cache keyed by URL hash."""

    def __init__(self, cache_dir: str = NEWS_CACHE_DIR, delay_sec: float = SCRAPE_DELAY_SEC) -> None:
        self.cache_dir = cache_dir
        self.delay_sec = delay_sec

    def fetch(self, url: str, source: str) -> NewsArticle | None:
        cache_path = os.path.join(self.cache_dir, f"{hashlib.md5(url.encode()).hexdigest()}.html")
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                html = f.read()
        else:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=20)
                resp.raise_for_status()
            except Exception as exc:
                print(f"Fetch failed: {url} - {exc}")
                return None
            html = resp.text
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(html)
            time.sleep(self.delay_sec)
        return parse_article_html(html, url, source)
