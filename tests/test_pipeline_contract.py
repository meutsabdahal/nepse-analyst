import unittest

from nepse_analyst import pipeline


class PipelineContractTests(unittest.TestCase):
    def test_oos_route_contract(self) -> None:
        out = pipeline.run("Should I buy or sell NABIL right now?")
        self.assertEqual(out.get("route"), "OOS")
        self.assertIn(out.get("guardrail_type"), {"prediction", "advice"})

    def test_oos_unknown_guardrail_contract(self) -> None:
        orig_classify = pipeline.classify
        try:
            pipeline.classify = lambda q: {
                "route": "OOS",
                "guardrail": None,
                "language": "en",
                "entities": {},
                "confidence": "high",
            }
            out = pipeline.run("Tell me what I should do next")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "OOS")
            self.assertEqual(out.get("guardrail_type"), "unknown")
        finally:
            pipeline.classify = orig_classify

    def test_sql_contract_shape_with_stubs(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_llm_call = pipeline.llm.call
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": True,
                "question": q,
                "sql": "SELECT 1 AS x",
                "rows": [{"x": 1}],
                "columns": ["x"],
                "row_count": 1,
                "attempts": 1,
                "error": None,
            }
            pipeline.llm.call = lambda *a, **k: "Stubbed answer"

            out = pipeline.run("test")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertTrue(out.get("sql"))
            self.assertIn("research purposes", out.get("answer", ""))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline.llm.call = orig_llm_call

    def test_sql_empty_rows_uses_symbol_metric_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_llm_call = pipeline.llm.call
        orig_fallback = pipeline._build_symbol_metric_fallback
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"symbol": "UPPER", "metric": "eps"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": True,
                "question": q,
                "sql": "SELECT ...",
                "rows": [],
                "columns": [],
                "row_count": 0,
                "attempts": 1,
                "error": None,
            }
            pipeline._build_symbol_metric_fallback = lambda language, entities: {
                "answer": "The latest EPS for UPPER is 11.00 in FY 2082/83.",
                "sql": "SELECT fallback",
                "sql_rows": [
                    {"symbol": "UPPER", "eps": 11.0, "fiscal_year": "2082/83"}
                ],
            }
            pipeline.llm.call = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("LLM synthesis should not run when fallback is used")
            )

            out = pipeline.run("what is eps of UPPER")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertIn("latest EPS", out.get("answer", ""))
            self.assertTrue(out.get("sql_rows"))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline.llm.call = orig_llm_call
            pipeline._build_symbol_metric_fallback = orig_fallback

    def test_sql_empty_rows_uses_price_range_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_llm_call = pipeline.llm.call
        orig_price_fallback = pipeline._build_symbol_price_range_fallback
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"symbol": "NFS", "metric": "price_range"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": True,
                "question": q,
                "sql": "SELECT ...",
                "rows": [],
                "columns": [],
                "row_count": 0,
                "attempts": 1,
                "error": None,
            }
            pipeline._build_symbol_price_range_fallback = lambda query, language, entities: {
                "answer": "The 52-week high for NFS is 851.00 and the 52-week low is 576.00.",
                "sql": "SELECT range",
                "sql_rows": [
                    {
                        "symbol": "NFS",
                        "latest_trade_date": "2026-04-10",
                        "high_52w": 851.0,
                        "low_52w": 576.0,
                    }
                ],
            }
            pipeline.llm.call = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("LLM synthesis should not run when fallback is used")
            )

            out = pipeline.run("what is 52 week high and low of NFS")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertIn("52-week high", out.get("answer", ""))
            self.assertTrue(out.get("sql_rows"))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline.llm.call = orig_llm_call
            pipeline._build_symbol_price_range_fallback = orig_price_fallback

    def test_sql_null_price_range_row_uses_price_range_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_llm_call = pipeline.llm.call
        orig_price_fallback = pipeline._build_symbol_price_range_fallback
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"symbol": "NFS", "metric": "price_range"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": True,
                "question": q,
                "sql": "SELECT symbol, MAX(high_price) AS week52_high, MIN(low_price) AS week52_low FROM price_history WHERE symbol='BAD'",
                "rows": [{"week52_high": None, "week52_low": None}],
                "columns": ["week52_high", "week52_low"],
                "row_count": 1,
                "attempts": 1,
                "error": None,
            }
            pipeline._build_symbol_price_range_fallback = lambda query, language, entities: {
                "answer": "The 52-week high for NFS is 851.00 and the 52-week low is 576.00.",
                "sql": "SELECT range",
                "sql_rows": [
                    {
                        "symbol": "NFS",
                        "latest_trade_date": "2026-04-10",
                        "high_52w": 851.0,
                        "low_52w": 576.0,
                    }
                ],
            }
            pipeline.llm.call = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("LLM synthesis should not run when fallback is used")
            )

            out = pipeline.run("what is 52 week high and low of NFS")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertIn("52-week high", out.get("answer", ""))
            self.assertTrue(out.get("sql_rows"))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline.llm.call = orig_llm_call
            pipeline._build_symbol_price_range_fallback = orig_price_fallback

    def test_sql_error_uses_symbol_metric_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_fallback = pipeline._build_symbol_metric_fallback
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"symbol": "UPPER", "metric": "eps"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": False,
                "question": q,
                "sql": "SELECT bad",
                "rows": [],
                "columns": [],
                "row_count": 0,
                "attempts": 3,
                "error": "SQL error",
            }
            pipeline._build_symbol_metric_fallback = lambda language, entities: {
                "answer": "The latest EPS for UPPER is 11.00 in FY 2082/83.",
                "sql": "SELECT fallback",
                "sql_rows": [
                    {"symbol": "UPPER", "eps": 11.0, "fiscal_year": "2082/83"}
                ],
            }

            out = pipeline.run("eps of UPPER")
            self.assertTrue(out.get("success"))
            self.assertIsNone(out.get("error"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertIn("UPPER", out.get("answer", ""))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline._build_symbol_metric_fallback = orig_fallback

    def test_sql_empty_rows_uses_dividend_consistency_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_dividend_fallback = pipeline._build_dividend_consistency_fallback
        orig_llm_call = pipeline.llm.call
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"sector": "Hydropower", "metric": "dividend"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": True,
                "question": q,
                "sql": "SELECT ...",
                "rows": [],
                "columns": [],
                "row_count": 0,
                "attempts": 1,
                "error": None,
            }
            pipeline._build_dividend_consistency_fallback = lambda q, language, entities: {
                "answer": "In Hydropower, these stocks have paid dividends consistently for the last 5 years: CHCL.",
                "sql": "SELECT streak",
                "sql_rows": [{"symbol": "CHCL", "years_paid": 5}],
            }
            pipeline.llm.call = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("LLM synthesis should not run when fallback is used")
            )

            out = pipeline.run(
                "which hydropower stock has been consistently providing dividend for last 5 years?"
            )
            self.assertTrue(out.get("success"))
            self.assertIn("consistently", out.get("answer", ""))
            self.assertTrue(out.get("sql_rows"))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline._build_dividend_consistency_fallback = orig_dividend_fallback
            pipeline.llm.call = orig_llm_call

    def test_sql_error_uses_dividend_consistency_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_dividend_fallback = pipeline._build_dividend_consistency_fallback
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"sector": "Hydropower", "metric": "dividend"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": False,
                "question": q,
                "sql": "SELECT broken",
                "rows": [],
                "columns": [],
                "row_count": 0,
                "attempts": 3,
                "error": "SQL error",
            }
            pipeline._build_dividend_consistency_fallback = lambda q, language, entities: {
                "answer": "In Hydropower, these stocks have paid dividends consistently for the last 5 years: CHCL.",
                "sql": "SELECT streak",
                "sql_rows": [{"symbol": "CHCL", "years_paid": 5}],
            }

            out = pipeline.run(
                "which hydropower stock has been consistently providing dividend for last 5 years?"
            )
            self.assertTrue(out.get("success"))
            self.assertIsNone(out.get("error"))
            self.assertIn("Hydropower", out.get("answer", ""))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline._build_dividend_consistency_fallback = orig_dividend_fallback

    def test_dividend_sector_coverage_query_uses_deterministic_fallback(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_coverage_fallback = pipeline._build_dividend_sector_coverage_fallback
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {"metric": "dividend"},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: (_ for _ in ()).throw(
                AssertionError(
                    "SQL generation should not run for sector coverage fallback queries"
                )
            )
            pipeline._build_dividend_sector_coverage_fallback = lambda q, language: {
                "answer": "Dividend data is not available for every sector.",
                "sql": "SELECT coverage",
                "sql_rows": [
                    {
                        "sector": "Hydropower",
                        "total_symbols": 10,
                        "symbols_with_dividend_rows": 5,
                    }
                ],
            }

            out = pipeline.run("dividend data is not available for every sectors")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertIn("every sector", out.get("answer", ""))
            self.assertTrue(out.get("sql_rows"))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline._build_dividend_sector_coverage_fallback = orig_coverage_fallback


if __name__ == "__main__":
    unittest.main()
