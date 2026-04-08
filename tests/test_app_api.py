import unittest

from fastapi import HTTPException

import app as app_module


class AppApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_run = app_module.run
        self.original_extract_symbol = app_module.extract_symbol_from_result
        self.original_fetch_quick_facts = app_module.fetch_quick_facts

    def tearDown(self) -> None:
        app_module.run = self.original_run
        app_module.extract_symbol_from_result = self.original_extract_symbol
        app_module.fetch_quick_facts = self.original_fetch_quick_facts

    def test_chat_returns_request_id_and_contract_shape(self) -> None:
        seen: dict[str, str] = {}

        def fake_run(query: str, request_id: str | None = None) -> dict:
            seen["query"] = query
            seen["request_id"] = request_id or ""
            return {
                "success": True,
                "answer": "Stubbed answer",
                "route": "SQL",
                "guardrail_type": None,
                "query_language": "en",
                "data_freshness": "Price data last updated: 2026-04-08",
                "sql": "SELECT 1 AS x",
                "sql_rows": [{"x": 1}],
                "passages": [],
                "error": None,
            }

        app_module.run = fake_run
        app_module.extract_symbol_from_result = lambda result, query: None
        app_module.fetch_quick_facts = lambda symbol: None

        payload = app_module.chat(app_module.ChatRequest(message="  test query  "))
        self.assertEqual(payload["query"], "test query")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["route"], "SQL")
        self.assertIn("request_id", payload)
        self.assertTrue(payload["request_id"])
        self.assertEqual(payload["request_id"], seen["request_id"])
        self.assertEqual(seen["query"], "test query")
        self.assertIn("sources", payload)
        self.assertIn("sql", payload["sources"])
        self.assertIn("sql_rows_preview", payload["sources"])

    def test_chat_rejects_whitespace_message(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            app_module.chat(app_module.ChatRequest(message="   "))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(str(ctx.exception.detail), "Message cannot be empty")


if __name__ == "__main__":
    unittest.main()
