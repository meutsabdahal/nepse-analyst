"""The example questions shown in the chat: grouped, answerable, not benchmark copies."""

import json
import unittest
from pathlib import Path

from test_prompt_leakage import PARAPHRASE_THRESHOLD, _jaccard

import app as app_module
from nepse_analyst.example_questions import EXAMPLE_GROUPS, EXAMPLE_QUESTIONS
from nepse_analyst.guardrails import get_guardrail_type
from nepse_analyst.language_detector import detect_language

BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "benchmark_questions.json"

# The news corpus ends in 2016, so news questions cannot be answered yet.
NEWS_WORDS = ("news", "announce", "agm", "समाचार", "घोषणा")


def _benchmark_questions() -> list[str]:
    data = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    return [
        case.get("question") or case.get("query")
        for cases in data.values() if isinstance(cases, list)
        for case in cases
    ]


class ExampleQuestionTests(unittest.TestCase):
    def test_groups_are_small_and_named(self) -> None:
        self.assertGreaterEqual(len(EXAMPLE_GROUPS), 3)
        for group in EXAMPLE_GROUPS:
            with self.subTest(group=group["group"]):
                self.assertTrue(group["group"].strip())
                self.assertTrue(1 <= len(group["questions"]) <= 3)
        # Every example is shown, so the list must stay short.
        self.assertLessEqual(len(EXAMPLE_QUESTIONS), 10)
        self.assertEqual(len(EXAMPLE_QUESTIONS), len(set(EXAMPLE_QUESTIONS)))

    def test_one_nepali_example(self) -> None:
        nepali = [q for q in EXAMPLE_QUESTIONS if detect_language(q) == "ne"]
        self.assertEqual(len(nepali), 1)

    def test_no_example_copies_a_benchmark_question(self) -> None:
        for example in EXAMPLE_QUESTIONS:
            for question in _benchmark_questions():
                with self.subTest(example=example, benchmark=question):
                    self.assertLess(_jaccard(example, question), PARAPHRASE_THRESHOLD)

    def test_no_news_or_declined_examples(self) -> None:
        for example in EXAMPLE_QUESTIONS:
            with self.subTest(example=example):
                self.assertFalse(any(word in example.lower() for word in NEWS_WORDS))
                self.assertIsNone(get_guardrail_type(example))

    def test_api_returns_groups_and_the_flat_list(self) -> None:
        payload = app_module.example_questions()
        self.assertEqual(payload["groups"], EXAMPLE_GROUPS)
        self.assertEqual(payload["examples"], EXAMPLE_QUESTIONS)


if __name__ == "__main__":
    unittest.main()
