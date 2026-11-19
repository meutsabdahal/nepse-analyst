import unittest

from nepse_analyst.chat_helpers import quick_fact_rows
from nepse_analyst.number_format import percent, plain, rupee_amount, rupees


class NumberFormatTests(unittest.TestCase):
    def test_amounts_in_lakh_and_crore(self) -> None:
        cases = {
            85_000: "Rs 85,000",
            420_000: "Rs 4.2 lakh",
            4_250_000: "Rs 42.5 lakh",
            9_999_000: "Rs 1 crore",  # not "Rs 100 lakh"
            10_000_000: "Rs 1 crore",
            42_000_000: "Rs 4.2 crore",
            1_234_567_890: "Rs 123 crore",
            148_542_921_216: "Rs 14,854 crore",
            -42_000_000: "-Rs 4.2 crore",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(rupee_amount(value), expected)

    def test_prices_percent_and_plain(self) -> None:
        self.assertEqual(rupees(549.0), "Rs 549")
        self.assertEqual(rupees(33.89), "Rs 33.89")
        self.assertEqual(rupees(233.90), "Rs 233.9")
        self.assertEqual(percent(12.5), "12.5%")
        self.assertEqual(percent(10.0), "10%")
        self.assertEqual(plain(16.2), "16.2")
        self.assertIsNone(rupees(None))
        self.assertIsNone(rupee_amount(None))


FACTS = {
    "symbol": "NABIL", "name": "Nabil Bank Limited", "sector": "Commercial Banks",
    "market_cap": 148_542_921_216, "close_price": 549.0, "trade_date": "2026-11-13",
    "fiscal_year": "2083/84", "pe_ratio": 16.2, "eps": 33.89, "book_value": 233.9, "roe": None,
    "cash_dividend": 12.5, "bonus_shares": None, "dividend_fy": "2082/83",
    "low_52w": 485.0, "high_52w": 581.0,
}


class QuickFactRowsTests(unittest.TestCase):
    def rows(self, facts=FACTS):
        return {r["label"]: (r["value"], r["as_of"]) for r in quick_fact_rows(facts)}

    def test_units_and_as_of_dates(self) -> None:
        rows = self.rows()
        self.assertEqual(rows["Close"], ("Rs 549", "on 2026-11-13"))
        self.assertEqual(rows["Market cap"], ("Rs 14,854 crore", "on 2026-11-13"))
        self.assertEqual(rows["52-week range"], ("Rs 485 – Rs 581", "to 2026-11-13"))
        self.assertEqual(rows["EPS"], ("Rs 33.89", "FY 2083/84"))
        self.assertEqual(rows["P/E"], ("16.2", "FY 2083/84"))
        self.assertEqual(rows["Cash dividend"], ("12.5%", "FY 2082/83"))
        self.assertEqual(rows["Sector"], ("Commercial Banks", None))

    def test_missing_facts_are_left_out(self) -> None:
        rows = self.rows()
        self.assertNotIn("ROE", rows)
        self.assertNotIn("Bonus shares", rows)
        sparse = self.rows({"symbol": "X", "sector": "Microfinance", "eps": 4.6, "fiscal_year": "2083/84"})
        self.assertEqual(list(sparse), ["Sector", "EPS"])

    def test_zero_is_a_value_not_missing(self) -> None:
        self.assertEqual(self.rows({**FACTS, "bonus_shares": 0})["Bonus shares"], ("0%", "FY 2082/83"))


if __name__ == "__main__":
    unittest.main()
