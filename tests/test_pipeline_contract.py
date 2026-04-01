import unittest

from nepse_analyst import pipeline


class PipelineContractTests(unittest.TestCase):
    def test_oos_route_contract(self) -> None:
        out = pipeline.run("Should I buy or sell NABIL right now?")
        self.assertEqual(out.get("route"), "OOS")
        self.assertIn(out.get("guardrail_type"), {"prediction", "advice"})

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
                "sql_rows": [{"symbol": "UPPER", "eps": 11.0, "fiscal_year": "2082/83"}],
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
                "sql_rows": [{"symbol": "UPPER", "eps": 11.0, "fiscal_year": "2082/83"}],
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


if __name__ == "__main__":
    unittest.main()
