import unittest
from datetime import date
from unittest.mock import patch

import app as app_module
from nepse_analyst import chat_helpers
from nepse_analyst.chat_helpers import data_freshness

TODAY = date(2026, 11, 19)


def _freshness(prices_to, news_to):
    with patch.object(chat_helpers, "_latest_price_date", return_value=prices_to), patch.object(
        chat_helpers, "_latest_news_date", return_value=news_to
    ):
        return data_freshness(today=TODAY)


class DataFreshnessTests(unittest.TestCase):
    def test_label_shows_both_dates(self) -> None:
        f = _freshness("2026-11-13", "2026-11-18")
        self.assertEqual(f["label"], "Prices to 2026-11-13 · News to 2026-11-18")
        self.assertFalse(f["prices_stale"] or f["news_stale"])
        self.assertIsNone(f["warning"])

    def test_old_news_is_flagged(self) -> None:
        f = _freshness("2026-11-13", "2016-12-15")
        self.assertEqual(f["label"], "Prices to 2026-11-13 · News to 2016-12-15")
        self.assertFalse(f["prices_stale"])
        self.assertTrue(f["news_stale"])
        self.assertEqual(f["news_age_days"], 3626)
        self.assertEqual(f["warning"], "News is 3626 days old.")

    def test_old_prices_are_flagged(self) -> None:
        f = _freshness("2026-10-01", "2026-11-18")
        self.assertTrue(f["prices_stale"])
        self.assertEqual(f["warning"], "Prices are 49 days old.")

    def test_thresholds_are_inclusive_of_the_limit(self) -> None:
        f = _freshness("2026-11-12", "2026-10-20")  # exactly 7 and 30 days
        self.assertFalse(f["prices_stale"] or f["news_stale"])
        f = _freshness("2026-11-11", "2026-10-19")  # 8 and 31 days
        self.assertTrue(f["prices_stale"] and f["news_stale"])

    def test_missing_data_counts_as_stale(self) -> None:
        f = _freshness(None, None)
        self.assertEqual(f["label"], "No price data · No news data")
        self.assertTrue(f["prices_stale"] and f["news_stale"])
        self.assertEqual(f["warning"], "No price data is loaded. No news is indexed.")


class ChatResponseFreshnessTests(unittest.TestCase):
    def test_every_chat_response_carries_freshness(self) -> None:
        def fake_run(query, request_id=None):
            return {"success": True, "answer": "Declined.", "route": "OOS", "answer_source": "guardrail", "error": None}

        with patch.object(app_module, "run", side_effect=fake_run), patch.object(
            app_module, "extract_symbol_from_result", return_value=None
        ), patch.object(chat_helpers, "_latest_price_date", return_value="2026-11-13"), patch.object(
            chat_helpers, "_latest_news_date", return_value="2016-12-15"
        ):
            payload = app_module.chat(app_module.ChatRequest(message="Should I buy NABIL?"))
        self.assertEqual(payload["freshness"]["news_to"], "2016-12-15")
        self.assertTrue(payload["freshness"]["news_stale"])


if __name__ == "__main__":
    unittest.main()
