import unittest
from unittest.mock import patch

import app as app_module
from nepse_analyst.chat_helpers import build_passage_preview
from nepse_analyst.column_labels import column_label, column_labels


def _passage(i, url="https://www.sharesansar.com/newsdetail/x", source="sharesansar"):
    return {"title": f"Article {i}", "url": url, "source": source, "published_at": "2026-11-18",
            "content": "Body " * 200, "relevance_score": 0.73}


class PassagePreviewTests(unittest.TestCase):
    def test_cards_are_numbered_like_the_citations_and_linked(self) -> None:
        cards = build_passage_preview([_passage(i) for i in range(3)])
        self.assertEqual([c["number"] for c in cards], [1, 2, 3])
        self.assertEqual(cards[0]["url"], "https://www.sharesansar.com/newsdetail/x")
        self.assertEqual(cards[0]["source_name"], "ShareSansar")
        self.assertNotIn("relevance_score", cards[0])
        self.assertTrue(cards[0]["content_preview"].endswith("..."))

    def test_only_http_links_are_kept(self) -> None:
        for bad in ("javascript:alert(1)", "data:text/html,x", "", None, "/relative/path", "https://"):
            with self.subTest(url=bad):
                self.assertIsNone(build_passage_preview([_passage(1, url=bad)])[0]["url"])

    def test_unknown_source_names_are_readable(self) -> None:
        self.assertEqual(build_passage_preview([_passage(1, source="nepse_alpha")])[0]["source_name"], "NepseAlpha")
        self.assertEqual(build_passage_preview([_passage(1, source="kathmandu_post")])[0]["source_name"], "Kathmandu Post")


class ColumnLabelTests(unittest.TestCase):
    def label(self, key):
        c = column_label(key)
        return c["label"], c["unit"]

    def test_database_columns(self) -> None:
        self.assertEqual(self.label("cash_dividend"), ("Cash dividend", "%"))
        self.assertEqual(self.label("fy_start"), ("Fiscal year (start)", None))
        self.assertEqual(self.label("eps"), ("EPS", "NPR"))
        self.assertEqual(self.label("close_price"), ("Close", "NPR"))
        self.assertEqual(self.label("market_cap"), ("Market cap", "NPR"))

    def test_model_aliases(self) -> None:
        self.assertEqual(self.label("max_eps"), ("Highest EPS", "NPR"))
        self.assertEqual(self.label("min_pe_ratio"), ("Lowest P/E ratio", None))
        self.assertEqual(self.label("total_volume"), ("Total volume", "shares"))
        self.assertEqual(self.label("avg_close_90d"), ("Average close (90 days)", "NPR"))
        self.assertEqual(self.label("count_symbol"), ("Number of companies", None))

    def test_year_columns_are_marked(self) -> None:
        formats = {c["key"]: c["format"] for c in column_labels(["fy_start", "eps", "fiscal_year"])}
        self.assertEqual(formats, {"fy_start": "year", "eps": "number", "fiscal_year": "number"})

    def test_unknown_columns_are_humanized(self) -> None:
        self.assertEqual(self.label("nepse_change_today"), ("NEPSE change today", None))
        self.assertEqual(column_labels(["symbol", "eps"])[1]["key"], "eps")


class ChatSourcesTests(unittest.TestCase):
    def test_response_carries_column_labels_and_numbered_links(self) -> None:
        def fake_run(query, request_id=None):
            return {"success": True, "answer": "EBL [1].", "route": "HYBRID", "answer_source": "generated_sql",
                    "sql": "SELECT symbol, cash_dividend FROM dividends", "error": None,
                    "sql_rows": [{"symbol": "EBL", "cash_dividend": 15.0}], "passages": [_passage(1)]}

        with patch.object(app_module, "run", side_effect=fake_run), patch.object(
            app_module, "extract_symbol_from_result", return_value=None
        ):
            payload = app_module.chat(app_module.ChatRequest(message="EBL dividends and news?"))
        sources = payload["sources"]
        self.assertEqual([c["label"] for c in sources["columns"]], ["Symbol", "Cash dividend"])
        self.assertEqual(sources["passages"][0]["number"], 1)
        self.assertTrue(sources["passages"][0]["url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
