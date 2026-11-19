import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import app as app_module
from nepse_analyst import pipeline

DB_ERROR = "no such column: f.eps2"
SECRET = "database is locked: /srv/app/data/processed/nepse.db"


def _sql_route(_query):
    return {"route": "SQL", "guardrail": None, "language": "en", "entities": {}, "confidence": "high"}


def _no_rule_answers(stack: ExitStack) -> None:
    for name in (
        "_build_dividend_consistency_fallback",
        "_build_dividend_sector_coverage_fallback",
        "_build_symbol_price_range_fallback",
        "_build_symbol_metric_fallback",
    ):
        stack.enter_context(patch.object(pipeline, name, return_value=None))
    stack.enter_context(patch.object(pipeline, "_get_db_freshness", return_value="test"))


class PipelineErrorMessageTests(unittest.TestCase):
    def test_failed_sql_answer_hides_the_database_error_and_logs_it(self) -> None:
        failed = {"success": False, "sql": "SELECT f.eps2 FROM fundamentals f", "rows": [], "columns": [],
                  "row_count": 0, "attempts": 3, "error": DB_ERROR}
        with ExitStack() as stack:
            _no_rule_answers(stack)
            stack.enter_context(patch.object(pipeline, "classify", side_effect=_sql_route))
            stack.enter_context(patch.object(pipeline, "generate_and_execute", return_value=failed))
            with self.assertLogs("nepse_analyst.pipeline", level="WARNING") as logs:
                out = pipeline.run("Which bank has the highest EPS?", request_id="req-123")

        self.assertFalse(out["success"])
        self.assertNotIn("no such column", out["answer"])
        self.assertNotIn("SELECT", out["answer"])
        self.assertEqual(out["error"], DB_ERROR)  # kept for logs and evaluation, not for users
        logged = "\n".join(logs.output)
        self.assertIn("request_id=req-123", logged)
        self.assertIn(DB_ERROR, logged)
        self.assertIn("SELECT f.eps2", logged)

    def test_unexpected_exception_is_not_shown_to_the_user(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, "classify", side_effect=_sql_route))
            stack.enter_context(patch.object(pipeline, "_handle_sql", side_effect=RuntimeError(SECRET)))
            with self.assertLogs("nepse_analyst.pipeline", level="ERROR") as logs:
                out = pipeline.run("Which bank has the highest EPS?", request_id="req-456")

        self.assertFalse(out["success"])
        self.assertNotIn("locked", out["answer"])
        self.assertIn("Something went wrong", out["answer"])
        self.assertEqual(out["answer_source"], "error")
        logged = "\n".join(logs.output)
        self.assertIn("request_id=req-456", logged)
        self.assertIn(SECRET, logged)


class ApiErrorMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(app_module, "extract_symbol_from_result", return_value=None))
        stack.enter_context(patch.object(app_module, "fetch_quick_facts", return_value=None))
        self.stack = stack

    def _chat(self, run):
        self.stack.enter_context(patch.object(app_module, "run", side_effect=run))
        return app_module.chat(app_module.ChatRequest(message="Which bank has the highest EPS?"))

    def test_response_carries_a_code_not_the_detail(self) -> None:
        payload = self._chat(lambda q, request_id=None: {
            "success": False, "answer": "I could not get the data for this question.",
            "route": "SQL", "answer_source": "generated_sql_failed", "error": DB_ERROR,
        })
        self.assertEqual(payload["error"], "request_failed")
        self.assertNotIn("no such column", json.dumps(payload))
        self.assertTrue(payload["request_id"])

    def test_timeout_is_reported_as_timeout(self) -> None:
        payload = self._chat(lambda q, request_id=None: {
            "success": False, "answer": "timed out", "route": "SQL",
            "answer_source": "timeout", "error": "deadline_exceeded: request time limit reached",
        })
        self.assertEqual(payload["error"], "timeout")

    def test_success_has_no_error(self) -> None:
        payload = self._chat(lambda q, request_id=None: {"success": True, "answer": "EBL", "route": "SQL", "error": None})
        self.assertIsNone(payload["error"])

    def test_exception_outside_the_pipeline_is_logged_with_the_request_id(self) -> None:
        def boom(q, request_id=None):
            raise RuntimeError(SECRET)

        with self.assertLogs("nepse_analyst.app", level="ERROR") as logs:
            payload = self._chat(boom)
        self.assertFalse(payload["success"])
        self.assertNotIn("locked", json.dumps(payload))
        self.assertEqual(payload["error"], "request_failed")
        self.assertIn(f"request_id={payload['request_id']}", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
