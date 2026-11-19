import unittest

from nepse_analyst import router


class RouterEntityTests(unittest.TestCase):
    def test_sort_symbols_prefers_longer_then_alpha(self) -> None:
        symbols = {"NIC", "NIMB", "NABIL", "NICA", "AHPC"}
        ordered = router._sort_symbols(symbols)
        self.assertEqual(ordered, ("NABIL", "AHPC", "NICA", "NIMB", "NIC"))

    def test_extract_entities_uses_deterministic_order_for_multiple_symbols(
        self,
    ) -> None:
        original_cache = router._SYMBOLS
        try:
            router._SYMBOLS = ("NABIL", "NIMB")
            entities = router.extract_entities("Compare NIMB and NABIL for EPS")
            self.assertEqual(entities["symbol"], "NABIL")
            self.assertEqual(entities["metric"], "eps")
        finally:
            router._SYMBOLS = original_cache

    def test_ambiguous_symbols_need_name_or_market_context(self) -> None:
        cases = {
            "What does SEBON say about IPO allotment?": None,
            "Is the NEPSE API down today?": None,
            "What is the EPS of Api Power?": "API",
            "API share price over the last month": "API",
            "What is NABIL's EPS?": "NABIL",
        }
        original_cache = router._SYMBOLS
        try:
            router._SYMBOLS = router._sort_symbols({"SEBON", "API", "NABIL"})
            for query, expected in cases.items():
                with self.subTest(query=query):
                    self.assertEqual(router.extract_entities(query)["symbol"], expected)
        finally:
            router._SYMBOLS = original_cache

    def test_metric_keywords_match_whole_words(self) -> None:
        cases = {
            "Which commercial bank has the highest EPS?": "eps",
            "Stocks trading below book value": "book_value",
            "Which company has the highest net profit?": "net_profit",
            "Show the steps to read a balance sheet": None,  # "eps" inside "steps"
            "How did the NEPSE index perform this year?": None,  # "eps" inside "NEPSE"
            "Hydropower companies that paid cash dividends": "dividend",
            "Total bonus shares issued by banks": "bonus_shares",
            "Lowest P/E ratio among hydropower companies": "pe_ratio",
            "Highest dividend paid last year": "dividend",
            "What is the 52-week high and low for NABIL?": "price_range",
            "What is the 52 week range of NABIL?": "price_range",
            "What is NABIL's 52-week high?": "price_high",
            "NABIL 52-week low": "price_low",
            "What were NABIL's high and low prices last year?": "price_range",
            "Show the high/low for NABIL": "price_range",
            "Is NABIL near a high?": None,
        }
        original_cache = router._SYMBOLS
        try:
            router._SYMBOLS = ("NABIL",)
            for query, expected in cases.items():
                with self.subTest(query=query):
                    self.assertEqual(router.extract_entities(query)["metric"], expected)
        finally:
            router._SYMBOLS = original_cache

    def test_sector_aliases_prefer_the_most_specific_match(self) -> None:
        cases = {
            "Which development bank has the highest EPS?": "Development Banks",
            "List dev bank dividends": "Development Banks",
            "Top commercial banks by P/E": "Commercial Banks",
            "Which bank has the highest book value?": "Commercial Banks",
            "Best non-life insurance company by ROE": "Non-Life Insurance",
            "Best non life insurance company by ROE": "Non-Life Insurance",
            "Which life insurance company pays the most dividend?": "Life Insurance",
            "Microfinance companies with rising EPS": "Microfinance",
            "Finance companies with the lowest P/E": "Finance Companies",
            "Hydropower stocks with bonus shares": "Hydropower",
            "What is the P/E ratio of NABIL?": None,
        }
        original_cache = router._SYMBOLS
        try:
            router._SYMBOLS = ("NABIL",)
            for query, expected in cases.items():
                with self.subTest(query=query):
                    self.assertEqual(router.extract_entities(query)["sector"], expected)
        finally:
            router._SYMBOLS = original_cache


if __name__ == "__main__":
    unittest.main()
