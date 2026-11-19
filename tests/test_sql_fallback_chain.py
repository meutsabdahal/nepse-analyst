"""The keyword rule answers behind generated SQL: order, triggers and response shape."""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from nepse_analyst import pipeline

RESPONSE_KEYS = {
    "success", "answer", "route", "sql", "sql_rows", "answer_source",
    "passages", "query_language", "data_freshness", "error",
}

FAILED = {"success": False, "sql": "SELECT bad", "rows": [], "columns": [], "row_count": 0, "attempts": 3, "error": "boom"}
EMPTY = {"success": True, "sql": "SELECT none", "rows": [], "columns": [], "row_count": 0, "attempts": 1, "error": None}


def _rule(name):
    return {"answer": f"{name} answer", "sql": f"SELECT {name}", "sql_rows": [{"rule": name}]}


class SqlFallbackChainTests(unittest.TestCase):
    def _run(self, generated, available):
        """Run _handle_sql with only the rules in ``available`` answering; return (result, calls)."""
        calls = []

        def builder(name):
            def build(*args):
                calls.append(name)
                return _rule(name) if name in available else None
            return build

        with ExitStack() as stack:
            for name in ("dividend", "price_range", "metric"):
                attr = {
                    "dividend": "_build_dividend_consistency_fallback",
                    "price_range": "_build_symbol_price_range_fallback",
                    "metric": "_build_symbol_metric_fallback",
                }[name]
                stack.enter_context(patch.object(pipeline, attr, side_effect=builder(name)))
            stack.enter_context(patch.object(pipeline, "_build_dividend_sector_coverage_fallback", return_value=None))
            stack.enter_context(patch.object(pipeline, "generate_and_execute", return_value=generated))
            stack.enter_context(patch.object(pipeline, "_get_db_freshness", return_value="fresh"))
            stack.enter_context(patch.object(pipeline.llm, "call", side_effect=AssertionError("no synthesis")))
            result = pipeline._handle_sql("q", "en", {})
        return result, calls

    def test_rules_run_in_order_and_the_first_answer_wins(self) -> None:
        for generated in (FAILED, EMPTY):
            with self.subTest(generated=generated["sql"]):
                result, calls = self._run(generated, {"price_range", "metric"})
                self.assertEqual(calls, ["dividend", "price_range"])
                self.assertEqual(result["answer_source"], "rule:price_range_52w")
                self.assertEqual(result["sql"], "SELECT price_range")
                self.assertEqual(result["sql_rows"], [{"rule": "price_range"}])
                self.assertTrue(result["success"])
                self.assertEqual(set(result), RESPONSE_KEYS)

    def test_each_rule_reports_its_own_source(self) -> None:
        expected = {"dividend": "rule:dividend_streak", "price_range": "rule:price_range_52w", "metric": "rule:latest_metric"}
        for name, source in expected.items():
            with self.subTest(rule=name):
                result, _ = self._run(EMPTY, {name})
                self.assertEqual(result["answer_source"], source)

    def test_failed_sql_with_no_rule_answer_is_a_plain_failure(self) -> None:
        result, calls = self._run(FAILED, set())
        self.assertEqual(calls, ["dividend", "price_range", "metric"])
        self.assertFalse(result["success"])
        self.assertEqual((result["answer_source"], result["sql"], result["error"]), ("generated_sql_failed", "SELECT bad", "boom"))
        self.assertEqual(set(result), RESPONSE_KEYS)


class ResponseShapeTests(unittest.TestCase):
    def test_every_route_returns_the_same_keys(self) -> None:
        with patch.object(pipeline, "search", return_value=[]), patch.object(
            pipeline, "_get_news_freshness", return_value="news"
        ), patch.object(pipeline.llm, "call", return_value="An answer"):
            results = {
                "rag": pipeline._handle_rag("q", "en", {}),
                "direct": pipeline._handle_direct("q", "en"),
                "timeout": pipeline._timeout_result("SQL", "en", 60, "late"),
            }
        for route, result in results.items():
            with self.subTest(route=route):
                self.assertEqual(set(result), RESPONSE_KEYS)


if __name__ == "__main__":
    unittest.main()
