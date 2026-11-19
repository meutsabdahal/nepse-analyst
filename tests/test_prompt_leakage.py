"""Guard against benchmark questions leaking into the SQL prompt.

If a worked example in the SQL prompt reuses a benchmark question (or a close
paraphrase of one), or its SQL matches a benchmark ground-truth query, pipeline
mode measures how well the model copies the prompt rather than how well it
writes SQL.
"""

import json
import re
import unittest
from pathlib import Path

from nepse_analyst.prompts import SQL_EXAMPLES, build_sql_prompt

BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "benchmark_questions.json"
)

# Token-set Jaccard similarity at or above this value counts as a paraphrase.
# Verbatim copies score 1.0. The leaked "top 3 commercial banks by market
# capitalisation" example scored 0.80 against Q3. The current examples score
# at most ~0.40 against any benchmark question.
PARAPHRASE_THRESHOLD = 0.6


def _normalize(text: str) -> str:
    text = re.sub(r"[^\w\s/]", " ", text.lower())
    return " ".join(text.split())


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.lower().replace(";", " ").split())


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_normalize(a).split()), set(_normalize(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _load_sql_benchmark() -> list[dict]:
    data = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    # Deferred cases are checked too, so they cannot leak back in before they are restored.
    return data["sql_benchmark"] + data.get("deferred_sql_benchmark", [])


class PromptLeakageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.benchmark = _load_sql_benchmark()

    def test_benchmark_is_loaded(self) -> None:
        self.assertGreater(len(self.benchmark), 0)
        self.assertGreater(len(SQL_EXAMPLES), 0)

    def test_no_example_question_matches_a_benchmark_question(self) -> None:
        for ex in SQL_EXAMPLES:
            for case in self.benchmark:
                with self.subTest(example=ex.question, benchmark=case["id"]):
                    self.assertNotEqual(
                        _normalize(ex.question), _normalize(case["question"])
                    )
                    self.assertLess(
                        _jaccard(ex.question, case["question"]),
                        PARAPHRASE_THRESHOLD,
                        f"Example looks like a paraphrase of {case['id']}",
                    )

    def test_no_example_sql_matches_benchmark_ground_truth(self) -> None:
        for ex in SQL_EXAMPLES:
            for case in self.benchmark:
                with self.subTest(example=ex.question, benchmark=case["id"]):
                    self.assertNotEqual(
                        _normalize_sql(ex.sql),
                        _normalize_sql(case["ground_truth_sql"]),
                    )

    def test_rendered_prompt_contains_no_benchmark_question(self) -> None:
        # Catches leaks added anywhere in the prompt, not only in SQL_EXAMPLES.
        # Uses a placeholder question so the benchmark question being asked is
        # not itself counted.
        prompt = _normalize(build_sql_prompt("placeholder"))
        for case in self.benchmark:
            with self.subTest(benchmark=case["id"]):
                self.assertNotIn(_normalize(case["question"]), prompt)

    def test_detector_flags_previously_leaked_examples(self) -> None:
        # Examples that used to be in the prompt. If these stop being flagged,
        # the checks above have become too weak.
        by_id = {c["id"]: c["question"] for c in self.benchmark}
        leaked = {
            "Q1": "Which commercial bank has the highest EPS in the latest fiscal year?",
            "Q3": "What is the P/E ratio of the top 3 commercial banks by market capitalisation?",
            "Q9": "What is the 52-week high and low for NABIL Bank?",
        }
        for case_id, question in leaked.items():
            with self.subTest(benchmark=case_id):
                self.assertGreaterEqual(
                    _jaccard(question, by_id[case_id]), PARAPHRASE_THRESHOLD
                )


if __name__ == "__main__":
    unittest.main()
