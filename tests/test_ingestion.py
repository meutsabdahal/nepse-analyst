import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from bs4 import BeautifulSoup

from nepse_analyst.ingestion import Loader, Sources
from nepse_analyst.ingestion.records import (
    Company,
    Dividend,
    Fundamental,
    IndexBar,
    IPOIssue,
    NewsArticle,
    PriceBar,
)
from nepse_analyst.ingestion.parsing import canonical_index_name
from nepse_analyst.ingestion.sources.base import PriceSource
from nepse_analyst.ingestion.sources.fallback import FallbackPriceSource
from nepse_analyst.ingestion.sources.github_open_data import GitHubOpenDataSource
from nepse_analyst.ingestion.sources.kaggle_csv import KaggleCsvCompanySource
from nepse_analyst.ingestion.sources.merolagani import (
    normalize_fiscal_year,
    parse_dividends,
    parse_fundamentals,
)


class FakeCompanies:
    name = "fake-companies"

    def fetch_companies(self):
        return [
            Company("NABIL", "Nabil Bank Limited", "Commercial Banks", 100),
            Company("NABILP", "Nabil Bank Limited Promoter Share", "Others", 10),
            Company("AHPC", "Arun Valley Hydropower Development Co. Ltd.", "Hydropower", 50),
            Company("NBF2", "Nabil Balanced Fund 2", "Mutual Fund", 5),
        ]


class FakePrices:
    def __init__(self, name="fake-prices", ok=True, data=None):
        self.name = name
        self.ok = ok
        self.data = data if data is not None else {
            "NABIL": [
                PriceBar("NABIL", "2026-01-02", 510.0, open_price=500.0),
                PriceBar("NABIL", "2026-01-01", 495.0, open_price=490.0),
            ],
            "AHPC": [PriceBar("AHPC", "2026-01-01", 300.0)],
        }
        self.calls = []
        self.closed = False

    def available(self):
        return self.ok

    def fetch_price_history(self, symbol):
        self.calls.append(symbol)
        return self.data.get(symbol, [])

    def fetch_index_history(self):
        return [
            IndexBar("2026-01-01", "NEPSE", 2700.0),
            IndexBar("2026-01-01", "NEPSE", 2700.0),  # duplicate, dropped
            IndexBar("2026-01-01", "Banking", 1400.0),
            IndexBar("2026-01-01", "Hydropower", 3000.0),
        ]

    def close(self):
        self.closed = True


class FakeFundamentals:
    name = "fake-fundamentals"

    def __init__(self):
        self.calls = []

    def fetch_fundamentals(self, symbol):
        self.calls.append(symbol)
        return (
            [Fundamental(symbol, "2081/82", eps=25.0)],
            [Dividend(symbol, "2081/82", cash_dividend=10.0)],
        )


class FakeIPOs:
    name = "fake-ipos"

    def fetch_ipos(self):
        return [
            IPOIssue("Arun Valley Hydropower Development Co. Ltd.", issue_price=100.0),  # matched by name
            IPOIssue("Unknown Co", symbol="ZZZ", issue_price=100.0),  # no price history -> dropped
        ]


class FakeNews:
    name = "fake-news"

    def fetch_news(self, limit=None):
        body = "Nabil Bank announced a cash dividend for shareholders. " * 3
        return [
            NewsArticle("https://x/1", self.name, "NABIL dividend announced", body, "2026-01-05", "en"),
            NewsArticle("https://x/2", self.name, "nabil dividend announced ", body, "2026-01-05", "en"),
        ][: limit or None]


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "nepse.db")
        self.prices = FakePrices()
        self.fundamentals = FakeFundamentals()
        self.indexed = []
        self.loader = Loader(
            sources=Sources(
                companies=FakeCompanies(),
                prices=self.prices,
                fundamentals=self.fundamentals,
                ipos=FakeIPOs(),
                news=[FakeNews()],
            ),
            db_path=self.db_path,
            vector_store_dir=os.path.join(self.tmp.name, "vs"),
            news_indexer=lambda docs, path, coll: self.indexed.extend(docs) or len(docs),
            min_news_articles=1,
            today=lambda: date(2026, 1, 10),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def query(self, sql):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def test_full_run_populates_every_table(self):
        results = self.loader.run()

        self.assertEqual(self.query("SELECT COUNT(*) FROM companies")[0][0], 4)
        # Promoter (P suffix) and digit symbols are skipped for prices.
        self.assertEqual(self.prices.calls, ["AHPC", "NABIL"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM price_history")[0][0], 3)
        self.assertEqual(results["indices"]["rows"], 3)
        # Mutual funds are excluded from fundamentals.
        self.assertNotIn("NBF2", self.fundamentals.calls)
        self.assertEqual(
            self.query("SELECT eps FROM fundamentals WHERE symbol='NABIL'"), [(25.0,)]
        )
        self.assertEqual(
            self.query("SELECT symbol, sector, listing_date, listing_price, status FROM ipos"),
            [("AHPC", "Hydropower", "2026-01-01", 300.0, "listed")],
        )
        # Title dedupe, symbol tagging, article typing.
        self.assertEqual(len(self.indexed), 1)
        self.assertEqual(self.indexed[0]["symbol"], "NABIL")
        self.assertEqual(self.indexed[0]["article_type"], "dividend")
        self.assertTrue(self.indexed[0]["id"].startswith("fake-news_20260105_"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "all_docs.json")))
        self.assertTrue(self.prices.closed)

    def test_rerun_is_idempotent(self):
        self.loader.run(["companies", "prices", "fundamentals"])
        self.loader.run(["companies", "prices", "fundamentals"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM price_history")[0][0], 3)
        self.assertEqual(self.query("SELECT COUNT(*) FROM fundamentals")[0][0], 3)

    def test_market_cap_is_listed_shares_times_latest_close(self):
        self.loader.run(["companies", "prices"])
        self.assertEqual(
            self.query("SELECT symbol, market_cap FROM companies ORDER BY symbol"),
            # NABIL: 100 x 510 (2026-01-02 close, not 2026-01-01). No prices -> NULL.
            [("AHPC", 15000.0), ("NABIL", 51000.0), ("NABILP", None), ("NBF2", None)],
        )

    def test_reloading_companies_keeps_market_cap(self):
        self.loader.run(["companies", "prices"])
        self.loader.run(["companies"])
        self.assertEqual(self.query("SELECT market_cap FROM companies WHERE symbol='NABIL'"), [(51000.0,)])

    def test_unavailable_price_source_fails_before_deleting_prices(self):
        self.loader.run(["companies", "prices"])
        self.prices.ok = False
        with self.assertRaises(RuntimeError):
            self.loader.run(["prices"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM price_history")[0][0], 3)

    def test_unknown_step_is_rejected(self):
        with self.assertRaises(ValueError):
            self.loader.run(["nope"])


class KaggleCsvTests(unittest.TestCase):
    def test_parses_thousands_separators_and_zero_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "companies.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "Name,company_nmae,symbol,Listed_Shares,Paidup_Value,Total_Paidup\n"
                    'Commercial Banks,Agriculture Development Bank Limited,ADBL,"134,516,741",100.00,"13,187,915,800.00"\n'
                    "Capital,Global IME Capital Limited,GICL,0,0.00,0.00\n"
                )
            adbl, gicl = KaggleCsvCompanySource(path).fetch_companies()
        self.assertEqual((adbl.listed_shares, adbl.paid_up_value, adbl.total_paid_up), (134516741, 100.0, 13187915800.0))
        self.assertEqual((gicl.listed_shares, gicl.paid_up_value, gicl.total_paid_up), (None, None, None))

    def test_bundled_csv_has_share_counts(self):
        companies = KaggleCsvCompanySource().fetch_companies()
        with_shares = [c for c in companies if c.listed_shares]
        self.assertGreater(len(with_shares), len(companies) // 2)


class FallbackPriceSourceTests(unittest.TestCase):
    def test_satisfies_price_source_interface(self):
        self.assertIsInstance(FallbackPriceSource([FakePrices()]), PriceSource)

    def test_skips_unavailable_and_empty_sources_in_order(self):
        dead = FakePrices("dead", ok=False)
        empty = FakePrices("empty", data={})
        good = FakePrices("good")
        chain = FallbackPriceSource([dead, empty, good])

        self.assertTrue(chain.available())
        bars = chain.fetch_price_history("NABIL")

        self.assertEqual(len(bars), 2)
        self.assertEqual(dead.calls, [])
        self.assertEqual(empty.calls, ["NABIL"])
        self.assertEqual(dict(chain.served_by), {"good": 1})

    def test_raises_when_no_source_has_rows(self):
        chain = FallbackPriceSource([FakePrices("empty", data={})])
        chain.available()
        with self.assertRaises(RuntimeError):
            chain.fetch_price_history("NABIL")


class IndexNameTests(unittest.TestCase):
    def test_exact_canonical_names(self):
        self.assertEqual(canonical_index_name("NEPSE_index"), "NEPSE")
        self.assertEqual(canonical_index_name("Banking_index"), "Banking")
        self.assertEqual(canonical_index_name("HydroPower_index"), "Hydropower")
        self.assertEqual(canonical_index_name("Hydro Power"), "Hydropower")

    def test_other_sub_indices_are_not_aliased(self):
        for name in ("Development%20Bank_index", "Microfinance_index", "Sensitive_index", "Float_index"):
            self.assertIsNone(canonical_index_name(name), name)


class GitHubListingTests(unittest.TestCase):
    def test_index_files_newest_first_from_tree_listing(self):
        tree = {
            "truncated": False,
            "tree": [
                {"path": ".gitkeep", "type": "blob"},
                {"path": "adj_2007-10-16.csv", "type": "blob"},
                {"path": "adj_2026-11-06.csv", "type": "blob"},
                {"path": "raw", "type": "tree"},
            ],
        }
        with patch("nepse_analyst.ingestion.sources.github_open_data.http_get_json", return_value=tree) as get:
            urls = GitHubOpenDataSource()._index_file_urls()

        self.assertIn("/git/trees/HEAD:ohlc_index", get.call_args.args[0])
        self.assertEqual(
            urls,
            [
                "https://raw.githubusercontent.com/socrateai-official/nepse-open-data/HEAD/ohlc_index/adj_2026-11-06.csv",
                "https://raw.githubusercontent.com/socrateai-official/nepse-open-data/HEAD/ohlc_index/adj_2007-10-16.csv",
            ],
        )

    def test_default_scan_can_reach_index_targets(self):
        source = GitHubOpenDataSource()
        self.assertGreaterEqual(source.max_index_files, max(source.index_target_days.values()))


class MerolaganiParserTests(unittest.TestCase):
    HTML = """
    <table id="accordion">
      <tr><th>EPS</th><td>25.50 (FY:082-083, Q:1)</td></tr>
      <tr><th>P/E Ratio</th><td>20.1</td></tr>
      <tr><th>Book Value</th><td>210.3</td></tr>
      <tr><th>% Dividend</th><td>12.5 (FY:081-082)</td></tr>
      <tr><th>% Bonus</th><td>5 (FY:081-082)</td></tr>
    </table>
    """

    def test_fiscal_year_normalization(self):
        self.assertEqual(normalize_fiscal_year("FY:082-083"), "2082/83")
        self.assertEqual(normalize_fiscal_year("2079/2080"), "2079/80")
        self.assertIsNone(normalize_fiscal_year("2026/03"))

    def test_parses_summary_table(self):
        soup = BeautifulSoup(self.HTML, "html.parser")
        [f] = parse_fundamentals(soup, "NABIL")
        self.assertEqual((f.fiscal_year, f.eps, f.pe_ratio, f.book_value), ("2082/83", 25.5, 20.1, 210.3))
        [d] = parse_dividends(soup, "NABIL")
        self.assertEqual((d.fiscal_year, d.cash_dividend, d.bonus_shares), ("2081/82", 12.5, 5.0))


if __name__ == "__main__":
    unittest.main()
