import time
import unittest
from unittest.mock import patch

import requests

from nepse_analyst import deadline, llm, pipeline, sql_generator
from nepse_analyst.deadline import DeadlineExceeded, request_deadline


class DeadlineTests(unittest.TestCase):
    def test_no_deadline_keeps_the_call_cap(self) -> None:
        self.assertIsNone(deadline.remaining())
        self.assertEqual(deadline.budget(120), 120)

    def test_budget_is_cut_to_the_time_left(self) -> None:
        with request_deadline(5):
            self.assertLessEqual(deadline.budget(120), 5)
            self.assertEqual(deadline.budget(2), 2)

    def test_budget_raises_when_too_little_time_is_left(self) -> None:
        with request_deadline(0.5):
            with self.assertRaises(DeadlineExceeded):
                deadline.budget(120)

    def test_nested_deadline_cannot_extend_the_outer_one(self) -> None:
        with request_deadline(5):
            with request_deadline(100):
                self.assertLessEqual(deadline.remaining(), 5)
            with request_deadline(2):
                self.assertLessEqual(deadline.remaining(), 2)
        self.assertIsNone(deadline.remaining())

    def test_retry_sleep_does_not_run_past_the_deadline(self) -> None:
        with request_deadline(2):
            with self.assertRaises(DeadlineExceeded):
                deadline.sleep(5)


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"response": "SQL"}


class LlmTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timeouts: list[float] = []
        patcher = patch.object(llm, "LLM_PROVIDER", "ollama")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, *args, **kwargs):
        self.timeouts.append(kwargs["timeout"])
        return _FakeResponse()

    def test_each_request_gets_at_most_the_time_left(self) -> None:
        with patch("requests.post", side_effect=self._post):
            llm.call("route this")
            with request_deadline(10):
                llm.call("route this")
                llm.call("route this", max_timeout_sec=3)
        self.assertEqual(self.timeouts[0], llm.LLM_TIMEOUT_SEC)
        self.assertLessEqual(self.timeouts[1], 10)
        self.assertLessEqual(self.timeouts[2], 3)

    def test_no_request_is_started_without_time_left(self) -> None:
        with patch("requests.post", side_effect=self._post):
            with request_deadline(0.5):
                with self.assertRaises(DeadlineExceeded):
                    llm.call("route this")
        self.assertEqual(self.timeouts, [])


class SqlGeneratorDeadlineTests(unittest.TestCase):
    def test_retries_stop_when_the_request_runs_out_of_time(self) -> None:
        calls = []

        def fake_call(prompt, **kwargs):
            calls.append(prompt)
            if len(calls) > 1:
                raise DeadlineExceeded("request time limit reached")
            return "SELECT missing FROM nowhere"

        with patch.object(sql_generator.llm, "call", side_effect=fake_call), patch.object(
            sql_generator.database, "execute_query",
            return_value={"success": False, "error": "no such table: nowhere"},
        ):
            result = sql_generator.generate_and_execute("anything")
        self.assertFalse(result["success"])
        self.assertEqual((len(calls), result["attempts"]), (2, 1))
        self.assertIn("no such table", result["error"])
        self.assertIn("time limit", result["error"])


class PipelineDeadlineTests(unittest.TestCase):
    def test_a_hanging_llm_cannot_hold_a_question_past_its_budget(self) -> None:
        timeouts: list[float] = []

        def hanging_post(*args, **kwargs):
            timeouts.append(kwargs["timeout"])
            time.sleep(kwargs["timeout"])
            raise requests.Timeout("read timed out")

        start = time.monotonic()
        with patch.object(llm, "LLM_PROVIDER", "ollama"), patch("requests.post", side_effect=hanging_post):
            result = pipeline.run("Explain what a stock exchange does", timeout_sec=2)
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 3.5)
        self.assertTrue(timeouts)
        self.assertTrue(all(t <= 2 for t in timeouts), timeouts)
        self.assertIn("answer", result)

    def test_deadline_during_a_handler_returns_a_timeout_answer(self) -> None:
        routing = {"route": "DIRECT", "guardrail": None, "language": "en", "entities": {}, "confidence": "high"}
        with patch.object(pipeline, "classify", return_value=routing), patch.object(
            pipeline, "_handle_direct", side_effect=DeadlineExceeded("request time limit reached")
        ):
            result = pipeline.run("What is NEPSE?", timeout_sec=30)
        self.assertFalse(result["success"])
        self.assertEqual(result["answer_source"], "timeout")
        self.assertTrue(result["error"].startswith("deadline_exceeded"))
        self.assertIn("30 s time limit", result["answer"])


if __name__ == "__main__":
    unittest.main()
