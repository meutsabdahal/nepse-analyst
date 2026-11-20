import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

import app as app_module
from nepse_analyst import coverage, database, retriever

TODAY = date(2026, 11, 20)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for statement in (
        database.CREATE_TABLE_COMPANIES,
        database.CREATE_TABLE_PRICE_HISTORY,
        database.CREATE_TABLE_FUNDAMENTALS,
        database.CREATE_TABLE_DIVIDENDS,
        database.CREATE_TABLE_IPOS,
        database.CREATE_TABLE_INDICES,
    ):
        conn.execute(statement)
    conn.executemany(
        "INSERT INTO fundamentals (symbol, fiscal_year, eps) VALUES (?, ?, ?)",
        [("NABIL", "2082/83", 30), ("NABIL", "2083/84", 32), ("NICA", "2083/84", 12), ("HIDCL", "2083/84", None)],
    )
    conn.executemany(
        "INSERT INTO dividends (symbol, fiscal_year, cash_dividend) VALUES (?, ?, ?)",
        [("NABIL", "2060/61", 10), ("NABIL", "2082/83", 12), ("NICA", "2071/72", 5)],
    )
    conn.executemany(
        "INSERT INTO price_history (symbol, trade_date, close_price) VALUES (?, ?, ?)",
        [("NABIL", "2026-11-12", 549), ("NICA", "2026-11-13", 400)],
    )
    conn.executemany(
        "INSERT INTO indices (trade_date, index_name, close_value) VALUES (?, ?, ?)",
        [("2025-07-09", "Hydropower", 1), ("2026-11-06", "NEPSE", 2), ("2025-07-09", "NEPSE", 2)],
    )
    conn.execute("INSERT INTO ipos (company_name, listing_date) VALUES ('X', '2021-04-25')")
    return conn


NEWS_2016 = {"total_documents": 16, "dated_documents": 16, "earliest_date": "2016-12-15",
             "latest_date": "2016-12-15", "built_at": "unknown"}


def _coverage(conn, news=NEWS_2016):
    with patch.object(coverage, "get_connection", return_value=conn), patch.object(
        retriever, "get_corpus_stats", return_value=news
    ):
        return {item["label"]: item for item in coverage.data_coverage(today=TODAY)}


class DataCoverageTests(unittest.TestCase):
    def test_each_dataset_shows_its_dates(self) -> None:
        items = _coverage(_db())
        self.assertEqual(items["Fundamentals"]["detail"], "EPS, P/E and book value for FY 2083/84 (2 companies)")
        self.assertEqual(items["Dividends"]["detail"], "Cash and bonus dividends, FY 2060/61 to FY 2082/83")
        self.assertEqual(items["Prices"]["detail"], "Daily prices for 2 companies, up to 2026-11-13")
        self.assertEqual(items["Indices"]["detail"], "NEPSE and Hydropower, 2025-07-09 to 2026-11-06")
        self.assertEqual(items["IPOs"]["detail"], "1 listing, 2021-04-25 to 2021-04-25")
        self.assertEqual(items["News"]["detail"], "16 articles, all from 2016-12-15")

    def test_old_news_is_flagged_not_promised(self) -> None:
        items = _coverage(_db())
        self.assertTrue(items["News"]["stale"])
        self.assertNotIn("recent", items["News"]["detail"].lower())

    def test_staleness_uses_the_freshness_thresholds(self) -> None:
        items = _coverage(_db())
        self.assertFalse(items["Prices"]["stale"])  # 7 days: at the limit
        self.assertTrue(items["Indices"]["stale"])  # 14 days
        self.assertFalse(items["Fundamentals"]["stale"])

    def test_news_range_spans_dates(self) -> None:
        news = dict(NEWS_2016, total_documents=1, earliest_date="2026-11-01", latest_date="2026-11-18")
        items = _coverage(_db(), news=news)
        self.assertEqual(items["News"]["detail"], "1 article, 2026-11-01 to 2026-11-18")
        self.assertFalse(items["News"]["stale"])

    def test_missing_data_is_left_out(self) -> None:
        conn = sqlite3.connect(":memory:")
        for statement in (database.CREATE_TABLE_FUNDAMENTALS, database.CREATE_TABLE_DIVIDENDS,
                          database.CREATE_TABLE_PRICE_HISTORY, database.CREATE_TABLE_INDICES,
                          database.CREATE_TABLE_IPOS):
            conn.execute(statement)
        empty_news = dict(NEWS_2016, total_documents=0, earliest_date="unknown", latest_date="unknown")
        self.assertEqual(_coverage(conn, news=empty_news), {})

    def test_no_database_still_lists_news(self) -> None:
        with patch.object(coverage, "get_connection", side_effect=FileNotFoundError), patch.object(
            retriever, "get_corpus_stats", return_value=NEWS_2016
        ):
            items = coverage.data_coverage(today=TODAY)
        self.assertEqual([item["label"] for item in items], ["News"])

    def test_endpoint_returns_items(self) -> None:
        with patch.object(app_module, "data_coverage", return_value=[{"label": "Prices"}]), patch.object(
            app_module, "data_freshness", return_value={"label": "Prices to 2026-11-13"}
        ):
            self.assertEqual(
                app_module.coverage(),
                {"items": [{"label": "Prices"}], "freshness": {"label": "Prices to 2026-11-13"}},
            )


if __name__ == "__main__":
    unittest.main()
