import os
import tempfile
import unittest
from datetime import date

from bs4 import BeautifulSoup

from nepse_analyst.ingestion import Loader, Sources
from nepse_analyst.ingestion.loader import news_corpus_problems
from nepse_analyst.ingestion.records import NewsArticle
from nepse_analyst.ingestion.sources.news_html import parse_article_html
from nepse_analyst.ingestion.sources.sharesansar import (
    LATEST_NEWS_URL,
    SharesansarNewsSource,
    next_listing_url,
    parse_listing_links,
)

BASE = "https://www.sharesansar.com"


def listing_page(slugs: list[str], next_cursor: str | None) -> str:
    """Minimal copy of the Sharesansar "Latest" listing layout."""
    # Site menu links to old evergreen articles; these must not be collected.
    menu = (
        '<div id="cssmenu"><ul><li><ul>'
        f'<li><a href="/newsdetail/capital-plan-of-commercial-bank">Commercial Banks</a></li>'
        f'<li><a href="{BASE}/newsdetail/watch-live-video-of-nepal-investment-summit-2019-2nd-day">Summit</a></li>'
        "</ul></li></ul></div>"
    )
    items = "".join(
        '<div class="featured-news-list margin-bottom-15">'
        f'<div class="col-md-2"><a href="{BASE}/newsdetail/{slug}"><img/></a></div>'
        f'<div class="col-md-10"><a href="{BASE}/newsdetail/{slug}"><h4 class="featured-news-title">{slug}</h4></a>'
        '<p><span class="text-org">Wednesday, November 18, 2026</span></p></div></div>'
        for slug in slugs
    )
    nxt = (
        f'<li class="page-item"><a class="page-link" href="?page=1&amp;cursor={next_cursor}" rel="next">Next</a></li>'
        if next_cursor
        else ""
    )
    return (
        f"<html><body>{menu}<div class='news-list'><div class='newslist'>{items}</div></div>"
        f'<ul class="pagination"><li class="page-item disabled"><span>Previous</span></li>{nxt}</ul>'
        "</body></html>"
    )


class FakeFetcher:
    def fetch(self, url, source):
        return NewsArticle(url, source, url.rsplit("/", 1)[-1], "x" * 100, "2026-11-18", "en")


class SharesansarListingTests(unittest.TestCase):
    def test_only_main_list_links_in_page_order(self):
        soup = BeautifulSoup(listing_page(["b-2026-11-18", "a-2026-11-18"], "c1"), "lxml")
        links = parse_listing_links(soup, LATEST_NEWS_URL)
        self.assertEqual(
            links,
            [f"{BASE}/newsdetail/b-2026-11-18", f"{BASE}/newsdetail/a-2026-11-18"],
        )

    def test_next_link_carries_cursor(self):
        soup = BeautifulSoup(listing_page(["a"], "abc"), "lxml")
        self.assertEqual(next_listing_url(soup, LATEST_NEWS_URL), f"{LATEST_NEWS_URL}?page=1&cursor=abc")
        self.assertIsNone(next_listing_url(BeautifulSoup(listing_page(["a"], None), "lxml"), LATEST_NEWS_URL))

    def test_pagination_follows_cursor_until_last_page(self):
        pages = {
            LATEST_NEWS_URL: listing_page(["n1", "n2"], "c1"),
            f"{LATEST_NEWS_URL}?page=1&cursor=c1": listing_page(["n3", "n4"], "c2"),
            f"{LATEST_NEWS_URL}?page=1&cursor=c2": listing_page(["n5"], None),
        }
        requested = []

        def get_html(url):
            requested.append(url)
            return pages[url]

        src = SharesansarNewsSource(delay_sec=0, fetcher=FakeFetcher(), get_html=get_html)
        urls = src.article_urls()
        self.assertEqual([u.rsplit("/", 1)[-1] for u in urls], ["n1", "n2", "n3", "n4", "n5"])
        self.assertEqual(requested, list(pages))

    def test_stops_when_a_page_repeats(self):
        # The old bug: the site ignored ?page=N and served page 1 every time.
        page = listing_page(["n1", "n2"], "same")
        calls = []

        def get_html(url):
            calls.append(url)
            return page

        src = SharesansarNewsSource(max_pages=50, delay_sec=0, fetcher=FakeFetcher(), get_html=get_html)
        self.assertEqual(len(src.article_urls()), 2)
        self.assertEqual(len(calls), 2)

    def test_limit_keeps_newest(self):
        pages = {
            LATEST_NEWS_URL: listing_page(["z-new", "a-old"], "c1"),
            f"{LATEST_NEWS_URL}?page=1&cursor=c1": listing_page(["m-older"], None),
        }
        src = SharesansarNewsSource(delay_sec=0, fetcher=FakeFetcher(), get_html=pages.__getitem__)
        self.assertEqual([a.title for a in src.fetch_news(limit=1)], ["z-new"])

    def test_layout_change_fails_loudly(self):
        src = SharesansarNewsSource(delay_sec=0, fetcher=FakeFetcher(), get_html=lambda url: "<html><a href='/newsdetail/x'>x</a></html>")
        with self.assertRaises(RuntimeError):
            src.article_urls()


class ArticleDateTests(unittest.TestCase):
    ARTICLE = (
        "<html><head><meta property='article:published_time' content='2016-12-15T05:55:55-05:00'/></head>"
        "<body><section class='main-content'><h1>Gold Price Falls</h1>"
        "<div class='margin-bottom-10'><h5><i class='fa fa-calendar'></i> Wed, Nov 18, 2026 10:40 AM</i> on "
        "<a class='tags'>Economy</a></h5></div>"
        "<div id='newsdetail-content'><p>" + "Gold prices fell sharply in the domestic market today. " * 3 + "</p></div></section>"
        "<h3>Recent News</h3><span class='date'>6 Jul, 2026</span>"
        "</body></html>"
    )

    def test_visible_date_beats_sitewide_meta(self):
        a = parse_article_html(self.ARTICLE, f"{BASE}/newsdetail/gold-price-falls", "sharesansar")
        self.assertEqual(a.published_at, "2026-11-18")

    def test_url_slug_date_beats_meta(self):
        html = self.ARTICLE.replace("Wed, Nov 18, 2026 10:40 AM", "")
        a = parse_article_html(html, f"{BASE}/newsdetail/gold-price-falls-2026-11-17", "sharesansar")
        self.assertEqual(a.published_at, "2026-11-17")


def doc(published_at="2026-11-18"):
    return {"published_at": published_at}


class NewsCorpusHealthTests(unittest.TestCase):
    today = date(2026, 11, 18)

    def check(self, docs, per_source=None, min_articles=3, max_age=14):
        return news_corpus_problems(docs, per_source or {"s": len(docs)}, min_articles, max_age, self.today)

    def test_healthy_corpus(self):
        self.assertEqual(self.check([doc(), doc("2026-11-10"), doc("2026-10-01")]), ([], []))

    def test_too_few_articles(self):
        problems, _ = self.check([doc()] * 2)
        self.assertTrue(any("only 2 articles" in p for p in problems))

    def test_only_old_articles(self):
        # The corpus the README's RAG numbers were measured on.
        problems, _ = self.check([doc("2016-12-15")] * 16, min_articles=3)
        self.assertTrue(any("newest article is from 2016-12-15" in p for p in problems))

    def test_mostly_undated(self):
        problems, _ = self.check([doc(""), doc(""), doc()])
        self.assertTrue(any("no parseable publish date" in p for p in problems))

    def test_empty_source_is_a_warning(self):
        problems, warnings = self.check([doc()] * 3, per_source={"sharesansar": 3, "nepse_alpha": 0})
        self.assertEqual(problems, [])
        self.assertEqual(warnings, ["news source 'nepse_alpha' returned 0 articles"])


class FakeNewsSource:
    name = "fake-news"

    def __init__(self, articles):
        self.articles = articles

    def fetch_news(self, limit=None):
        return self.articles


class LoaderNewsHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.indexed = []

    def tearDown(self):
        self.tmp.cleanup()

    def loader(self, articles, **kwargs):
        return Loader(
            sources=Sources(companies=None, prices=None, fundamentals=None, ipos=None,
                            news=[FakeNewsSource(articles)]),
            db_path=os.path.join(self.tmp.name, "nepse.db"),
            vector_store_dir=os.path.join(self.tmp.name, "vs"),
            news_indexer=lambda docs, path, coll: self.indexed.extend(docs) or len(docs),
            min_news_articles=5,
            today=lambda: date(2026, 11, 18),
            **kwargs,
        )

    @staticmethod
    def stale_articles():
        body = "Nabil Bank announced a cash dividend for shareholders. " * 3
        return [NewsArticle(f"https://x/{i}", "fake-news", f"Old story {i}", body, "2016-12-15", "en") for i in range(3)]

    def test_thin_stale_corpus_is_rejected_before_indexing(self):
        loader = self.loader(self.stale_articles())
        loader.create_schema()
        with self.assertRaises(RuntimeError) as ctx:
            loader.load_news()
        self.assertIn("only 3 articles", str(ctx.exception))
        self.assertIn("2016-12-15", str(ctx.exception))
        self.assertEqual(self.indexed, [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "all_docs.json")))

    def test_override_indexes_and_reports_problems(self):
        loader = self.loader(self.stale_articles(), allow_thin_news=True)
        loader.create_schema()
        result = loader.load_news()
        self.assertEqual(len(self.indexed), 3)
        self.assertEqual(len(result["health_problems"]), 2)


if __name__ == "__main__":
    unittest.main()
