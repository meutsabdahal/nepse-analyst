"""Shared helpers for scraping news listing and article pages."""

from __future__ import annotations

import hashlib
import os
import re
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
# Dates shown on the page come first. Sharesansar's article:published_time
# meta tag is a site-wide constant (2016-12-15), so meta tags are only used
# after the visible date and the date in the URL slug.
_VISIBLE_DATE_SELECTORS = (
    "h5:has(> i.fa-calendar)",  # Sharesansar: "Wed, Nov 18, 2026 10:40 AM on ..."
    "span.news-date", "time", ".entry-date", "section.main-content time",
)
_META_DATE_SELECTORS = (
    "meta[property='article:published_time']", "meta[name='pubdate']",
)
_DATE_PATTERNS = (
    (re.compile(r"\d{4}-\d{2}-\d{2}"), ("%Y-%m-%d",)),
    (re.compile(r"\d{4}/\d{2}/\d{2}"), ("%Y/%m/%d",)),
    (re.compile(r"[A-Za-z]{3,9},? [A-Za-z]{3,9} \d{1,2},? \d{4}"),
     ("%a, %b %d, %Y", "%A, %B %d, %Y", "%a, %B %d, %Y", "%A, %b %d, %Y")),
    (re.compile(r"[A-Za-z]{3,9} \d{1,2},? \d{4}"), ("%B %d, %Y", "%b %d, %Y")),
    (re.compile(r"\d{1,2} [A-Za-z]{3,9},? \d{4}"), ("%d %b %Y", "%d %B %Y", "%d %b, %Y", "%d %B, %Y")),
)
_URL_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})/?$")
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
        links.add(abs_url)
    return sorted(links)


def _first_match(soup: BeautifulSoup, selectors: tuple[str, ...]):
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None


def parse_date_text(raw: str) -> str:
    """First recognisable date in ``raw`` as YYYY-MM-DD, or ""."""
    for pattern, formats in _DATE_PATTERNS:
        for match in pattern.finditer(raw):
            for fmt in formats:
                try:
                    return datetime.strptime(match.group(0), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return ""


def extract_published_date(soup: BeautifulSoup, url: str) -> str:
    for sel in _VISIBLE_DATE_SELECTORS:
        for el in soup.select(sel):
            if parsed := parse_date_text(el.get_text(" ", strip=True)):
                return parsed
    if m := _URL_DATE.search(urlparse(url).path):
        if parsed := parse_date_text(m.group(1)):
            return parsed
    for sel in _META_DATE_SELECTORS:
        for el in soup.select(sel):
            if parsed := parse_date_text(el.get("content", "")):
                return parsed
    return ""


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

    published_at = extract_published_date(soup, url)

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
