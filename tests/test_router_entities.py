import unittest

from nepse_analyst import router


class RouterEntityTests(unittest.TestCase):
    def test_sort_symbols_prefers_longer_then_alpha(self) -> None:
        symbols = {"NIC", "NIMB", "NABIL", "NICA", "AHPC"}
        ordered = router._sort_symbols(symbols)
        self.assertEqual(ordered, ("NABIL", "AHPC", "NICA", "NIMB", "NIC"))

    def test_extract_entities_uses_deterministic_order_for_multiple_symbols(self) -> None:
        original_cache = router._SYMBOLS
        try:
            router._SYMBOLS = ("NABIL", "NIMB")
            entities = router.extract_entities("Compare NIMB and NABIL for EPS")
            self.assertEqual(entities["symbol"], "NABIL")
            self.assertEqual(entities["metric"], "eps")
        finally:
            router._SYMBOLS = original_cache


if __name__ == "__main__":
    unittest.main()
