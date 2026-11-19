import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from nepse_analyst import pipeline, progress

ROWS = {"success": True, "sql": "SELECT 1", "rows": [{"symbol": "NABIL", "eps": 33.89}],
        "columns": ["symbol", "eps"], "row_count": 1, "attempts": 1, "error": None}
PASSAGES = [{"source": "sharesansar", "published_at": "2026-11-10", "title": "Profit",
             "content": "Nabil Bank reported higher profit.", "url": "https://example.com/1"}]


def _route(route, language="en"):
    return lambda _q: {"route": route, "guardrail": None, "language": language, "entities": {}, "confidence": "high"}


class PipelineStageTests(unittest.TestCase):
    def stages(self, route, query="What is the EPS of NABIL?", language="en"):
        seen = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, "classify", side_effect=_route(route, language)))
            stack.enter_context(patch.object(pipeline, "_build_dividend_sector_coverage_fallback", return_value=None))
            stack.enter_context(patch.object(pipeline, "generate_and_execute", return_value=ROWS))
            stack.enter_context(patch.object(pipeline, "search", return_value=PASSAGES))
            stack.enter_context(patch.object(pipeline.llm, "call", return_value="An answer."))
            for name in ("_get_db_freshness", "_get_news_freshness"):
                stack.enter_context(patch.object(pipeline, name, return_value="test"))
            stack.enter_context(patch.object(pipeline, "_get_news_staleness_warning", return_value=None))
            with progress.reporting(lambda stage, label: seen.append((stage, label))):
                pipeline.run(query)
        return seen

    def test_sql_question(self) -> None:
        self.assertEqual([s for s, _ in self.stages("SQL")],
                         ["understanding", "querying_database", "writing_answer"])

    def test_news_question(self) -> None:
        self.assertEqual([s for s, _ in self.stages("RAG")],
                         ["understanding", "searching_news", "writing_answer"])

    def test_general_question(self) -> None:
        self.assertEqual([s for s, _ in self.stages("DIRECT")], ["understanding", "writing_answer"])

    def test_labels_follow_the_question_language(self) -> None:
        seen = dict(self.stages("SQL", query="NABIL को EPS कति छ?", language="ne"))
        self.assertEqual(seen["querying_database"], "डाटाबेसबाट जानकारी खोज्दै")
        self.assertEqual(dict(self.stages("SQL"))["writing_answer"], "Writing the answer")

    def test_no_listener_and_failing_listener_are_harmless(self) -> None:
        progress.report(progress.UNDERSTANDING)  # no listener installed

        def broken(stage, label):
            raise RuntimeError("listener failed")

        with progress.reporting(broken):
            progress.report(progress.WRITING_ANSWER)

    def test_every_stage_has_a_label(self) -> None:
        for stage in progress.STAGES:
            for language in ("en", "ne"):
                self.assertTrue(progress.stage_label(stage, language))


class StreamEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(app_module, "extract_symbol_from_result", return_value=None))
        stack.enter_context(patch.object(app_module, "fetch_quick_facts", return_value=None))
        stack.enter_context(patch.object(app_module, "data_freshness", return_value={}))
        app_module.app.dependency_overrides[app_module.enforce_chat_rate_limit] = lambda: None
        self.addCleanup(app_module.app.dependency_overrides.clear)
        self.stack = stack
        self.client = TestClient(app_module.app)

    def stream(self, run):
        self.stack.enter_context(patch.object(app_module, "run", side_effect=run))
        response = self.client.post("/api/chat/stream", json={"message": "What is the EPS of NABIL?"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/x-ndjson"))
        return [json.loads(line) for line in response.text.splitlines() if line]

    def test_stages_then_the_answer(self) -> None:
        def run(query, request_id=None):
            progress.report(progress.UNDERSTANDING)
            progress.report(progress.QUERYING_DATABASE)
            progress.report(progress.WRITING_ANSWER)
            return {"success": True, "answer": "NABIL EPS is Rs 33.89.", "route": "SQL"}

        events = self.stream(run)
        self.assertEqual([e["type"] for e in events], ["stage", "stage", "stage", "answer"])
        self.assertEqual(events[1], {"type": "stage", "stage": "querying_database", "label": "Querying the database"})
        answer = events[-1]["data"]
        self.assertEqual(answer["answer"], "NABIL EPS is Rs 33.89.")
        self.assertTrue(answer["success"])
        self.assertTrue(answer["request_id"])

    def test_pipeline_failure_still_ends_with_an_answer(self) -> None:
        def run(query, request_id=None):
            progress.report(progress.UNDERSTANDING)
            raise RuntimeError("database is locked")

        with self.assertLogs("nepse_analyst.app", level="ERROR"):
            events = self.stream(run)
        answer = events[-1]
        self.assertEqual(answer["type"], "answer")
        self.assertFalse(answer["data"]["success"])
        self.assertEqual(answer["data"]["error"], "request_failed")
        self.assertNotIn("locked", json.dumps(events))

    def test_empty_question_is_rejected(self) -> None:
        response = self.client.post("/api/chat/stream", json={"message": "   "})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
