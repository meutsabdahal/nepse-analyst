import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from nepse_analyst.feedback import FeedbackStore, answer_record, latest_ratings
from nepse_analyst.rate_limit import SlidingWindowLimiter

REQUEST_ID = "6f1c2a3b-4d5e-4f60-8a9b-0c1d2e3f4a5b"


def _record(question: str = "What is NABIL's P/E?") -> dict:
    response = {
        "answer": "NABIL's P/E is 18.4.",
        "route": "SQL",
        "answer_basis": {"kind": "database", "label": "From the database"},
        "query_language": "en",
        "success": True,
        "error": None,
        "sources": {"passages": [{"title": "AGM notice", "url": "https://example.com/a", "published_at": "2026-11-01",
                                  "content_preview": "long text"}]},
        "timestamp": "2026-11-20T08:00:00+00:00",
    }
    result = {"answer_source": "sql", "sql": "SELECT pe_ratio FROM fundamentals WHERE symbol = 'NABIL'"}
    return answer_record(question, response, result)


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "feedback" / "ratings.jsonl"
        self.store = FeedbackStore(self.path, max_answers=2)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def test_rating_is_saved_with_the_question_and_answer(self) -> None:
        self.store.remember(REQUEST_ID, _record())
        self.assertTrue(self.store.rate(REQUEST_ID, "down"))
        [line] = self.lines()
        self.assertEqual(line["request_id"], REQUEST_ID)
        self.assertEqual(line["rating"], "down")
        self.assertEqual(line["question"], "What is NABIL's P/E?")
        self.assertEqual(line["answer"], "NABIL's P/E is 18.4.")
        self.assertEqual(line["route"], "SQL")
        self.assertEqual(line["answer_basis"], "database")
        self.assertEqual(line["sql"], "SELECT pe_ratio FROM fundamentals WHERE symbol = 'NABIL'")
        self.assertEqual(line["sources"], [{"title": "AGM notice", "url": "https://example.com/a",
                                            "published_at": "2026-11-01"}])
        self.assertIn("rated_at", line)

    def test_unknown_answer_is_not_saved(self) -> None:
        self.assertFalse(self.store.rate(REQUEST_ID, "up"))
        self.assertFalse(self.path.exists())

    def test_only_recent_answers_are_remembered(self) -> None:
        self.store.remember("a", _record("first"))
        self.store.remember("b", _record("second"))
        self.store.remember("c", _record("third"))
        self.assertFalse(self.store.rate("a", "up"))
        self.assertTrue(self.store.rate("c", "up"))

    def test_rejects_unknown_rating(self) -> None:
        self.store.remember(REQUEST_ID, _record())
        with self.assertRaises(ValueError):
            self.store.rate(REQUEST_ID, "meh")

    def test_latest_rating_wins_and_cleared_ones_drop_out(self) -> None:
        self.store.remember("a", _record("first"))
        self.store.remember("b", _record("second"))
        self.store.rate("a", "up")
        self.store.rate("a", "down")
        self.store.rate("b", "up")
        self.store.rate("b", "none")
        latest = latest_ratings(self.path.read_text(encoding="utf-8").splitlines())
        self.assertEqual({k: v["rating"] for k, v in latest.items()}, {"a": "down"})


class FeedbackEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ratings.jsonl"
        self.store = FeedbackStore(self.path)
        patches = [
            patch.object(app_module, "feedback_store", self.store),
            patch.object(app_module, "feedback_limiter", SlidingWindowLimiter([(2, 60.0)])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_answers_can_be_rated_by_request_id(self) -> None:
        def fake_run(query, request_id=None):
            return {"success": True, "answer": "Stubbed", "route": "SQL", "answer_source": "sql",
                    "sql": "SELECT 1", "error": None}

        with patch.object(app_module, "run", side_effect=fake_run), patch.object(
            app_module, "extract_symbol_from_result", return_value=None
        ), patch.object(app_module, "data_freshness", return_value={}):
            answer = app_module.answer_question("A question")

        response = self.client.post("/api/feedback", json={"request_id": answer["request_id"], "rating": "up"})
        self.assertEqual(response.status_code, 200)
        [line] = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((line["question"], line["answer"], line["rating"]), ("A question", "Stubbed", "up"))

    def test_unknown_answer_is_404(self) -> None:
        response = self.client.post("/api/feedback", json={"request_id": REQUEST_ID, "rating": "up"})
        self.assertEqual(response.status_code, 404)

    def test_invalid_input_is_rejected(self) -> None:
        self.store.remember(REQUEST_ID, _record())
        self.assertEqual(self.client.post("/api/feedback", json={"request_id": REQUEST_ID, "rating": "meh"}).status_code, 422)
        self.assertEqual(self.client.post("/api/feedback", json={"request_id": "not-a-uuid", "rating": "up"}).status_code, 422)

    def test_ratings_are_rate_limited(self) -> None:
        self.store.remember(REQUEST_ID, _record())
        codes = [self.client.post("/api/feedback", json={"request_id": REQUEST_ID, "rating": "up"}).status_code
                 for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


if __name__ == "__main__":
    unittest.main()
