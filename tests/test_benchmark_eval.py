import json
import sqlite3
import unittest
from pathlib import Path

from nepse_analyst.database import FULL_SCHEMA_SQL
from nepse_analyst.evaluation import answer_mentions, lenient_score, strict_match, values_equal

BENCHMARK = json.loads(
    (Path(__file__).resolve().parents[1] / "evaluation" / "benchmark_questions.json").read_text(encoding="utf-8")
)
CASES = {c["id"]: c for c in BENCHMARK["sql_benchmark"]}


class StrictMatchTests(unittest.TestCase):
    def test_column_names_are_ignored(self):
        expected = [{"symbol": "RBB", "eps": 42.2, "fiscal_year": "2083/84"}]
        actual = [{"symbol": "RBB", "name": "Rastriya Banijya Bank", "max_eps": 42.2}]
        self.assertTrue(strict_match(expected, actual, ["symbol", "eps"]))

    def test_wrong_value_fails(self):
        expected = [{"symbol": "RBB", "eps": 42.2}]
        self.assertFalse(strict_match(expected, [{"symbol": "NABIL", "eps": 35.18}], ["symbol", "eps"]))

    def test_rounding_tolerance(self):
        self.assertTrue(values_equal(17.47, 17.4689))
        self.assertTrue(values_equal(61481070.51, 61481070.5123))
        self.assertFalse(values_equal(17.47, 0.1747))

    def test_row_count_must_match(self):
        expected = [{"symbol": "A"}, {"symbol": "B"}]
        self.assertFalse(strict_match(expected, [{"symbol": "A"}], ["symbol"]))
        self.assertFalse(strict_match(expected, [{"symbol": "A"}, {"symbol": "B"}, {"symbol": "C"}], ["symbol"]))
        self.assertTrue(strict_match(expected, [{"s": "B"}, {"s": "A"}], ["symbol"]))

    def test_each_expected_row_needs_its_own_result_row(self):
        expected = [{"symbol": "A"}, {"symbol": "A"}]
        self.assertFalse(strict_match(expected, [{"symbol": "A"}, {"symbol": "B"}], ["symbol"]))

    def test_empty_reference(self):
        self.assertTrue(strict_match([], [], ["symbol"]))
        self.assertFalse(strict_match([], [{"symbol": "A"}], ["symbol"]))


class LenientScoreTests(unittest.TestCase):
    def test_any_non_empty_result_is_half_credit(self):
        # This is why lenient scores are reported separately from strict ones.
        self.assertEqual(lenient_score([{"symbol": "RBB"}], [{"symbol": "WRONG"}]), (0.5, "partial"))

    def test_labels(self):
        self.assertEqual(lenient_score([{"a": 1}], [{"a": 1}]), (1.0, "correct"))
        self.assertEqual(lenient_score([], []), (1.0, "correct"))
        self.assertEqual(lenient_score([{"a": 1}], []), (0.0, "incorrect"))
        self.assertEqual(lenient_score([{"a": 1}], None), (0.0, "incorrect"))


class AnswerMentionsTests(unittest.TestCase):
    def test_numbers_in_common_formats(self):
        rows = [{"low_52w": 485.0, "high_52w": 581.0}]
        cols = ["low_52w", "high_52w"]
        self.assertTrue(answer_mentions("The 52-week high is 581.00 and the low is 485.00.", rows, cols))
        self.assertTrue(answer_mentions("Range: Rs 485 to Rs 581", rows, cols))
        self.assertFalse(answer_mentions("The 52-week high is 562.00 and the low is 471.00.", rows, cols))

    def test_strings_case_insensitive(self):
        self.assertTrue(answer_mentions("manufacturing led with 61,481,070.51", [{"sector": "Manufacturing", "v": 61481070.51}], ["sector", "v"]))

    def test_empty_reference_is_not_checked(self):
        self.assertIsNone(answer_mentions("anything", [], ["symbol"]))


def _db_with(dividends=(), fundamentals=(), companies=()):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(FULL_SCHEMA_SQL)
    conn.executemany("INSERT INTO companies (symbol, name, sector) VALUES (?, ?, ?)", companies)
    conn.executemany("INSERT INTO dividends (symbol, fiscal_year, cash_dividend) VALUES (?, ?, ?)", dividends)
    conn.executemany("INSERT INTO fundamentals (symbol, fiscal_year, eps) VALUES (?, ?, ?)", fundamentals)
    return conn


def _symbols(conn, case_id):
    return [r["symbol"] for r in conn.execute(CASES[case_id]["ground_truth_sql"])]


class ReferenceSqlTests(unittest.TestCase):
    def test_q2_needs_three_consecutive_paying_years(self):
        conn = _db_with(
            companies=[("RUN", "Run Hydro", "Hydropower"), ("GAP", "Gap Hydro", "Hydropower"),
                       ("ZERO", "Zero Hydro", "Hydropower"), ("BANK", "A Bank", "Commercial Banks")],
            dividends=[
                ("RUN", "2079/80", 5), ("RUN", "2080/81", 5), ("RUN", "2081/82", 5),
                ("GAP", "2078/79", 5), ("GAP", "2079/80", 5), ("GAP", "2081/82", 5), ("GAP", "2082/83", 5),
                ("ZERO", "2079/80", 5), ("ZERO", "2080/81", 0), ("ZERO", "2081/82", 5),
                ("BANK", "2079/80", 5), ("BANK", "2080/81", 5), ("BANK", "2081/82", 5),
            ],
        )
        self.assertEqual(_symbols(conn, "Q2"), ["RUN"])

    def test_q5_needs_strictly_increasing_eps_over_three_consecutive_years(self):
        conn = _db_with(fundamentals=[
            ("UP", "2080/81", 10), ("UP", "2081/82", 12), ("UP", "2082/83", 15),
            ("FLAT", "2080/81", 10), ("FLAT", "2081/82", 10), ("FLAT", "2082/83", 15),
            ("GAP", "2079/80", 10), ("GAP", "2081/82", 12), ("GAP", "2082/83", 15),
            ("LATE", "2078/79", 9), ("LATE", "2079/80", 8), ("LATE", "2080/81", 9), ("LATE", "2081/82", 10),
            ("TWO", "2081/82", 1), ("TWO", "2082/83", 2),
        ])
        self.assertEqual(_symbols(conn, "Q5"), ["LATE", "UP"])


class BenchmarkFileTests(unittest.TestCase):
    def test_match_columns_exist_in_reference_results(self):
        conn = _db_with()
        for case in BENCHMARK["sql_benchmark"]:
            with self.subTest(case=case["id"]):
                cur = conn.execute(case["ground_truth_sql"])
                columns = [d[0] for d in cur.description]
                self.assertTrue(case["match_columns"])
                self.assertTrue(set(case["match_columns"]) <= set(columns), columns)

    def test_snapshot_shape(self):
        for case in BENCHMARK["sql_benchmark"]:
            with self.subTest(case=case["id"]):
                gt = case["ground_truth"]
                self.assertEqual(gt["row_count"] == 0, gt.get("status") == "data_unavailable")
                self.assertLessEqual(len(gt["rows"]), gt["row_count"])

    def test_allowed_questions_are_distinct_from_refusal_questions(self):
        allowed = [c["query"] for c in BENCHMARK["allowed_benchmark"]]
        refused = {c["query"] for c in BENCHMARK["oos_benchmark"]}
        self.assertGreaterEqual(len(allowed), 10)
        self.assertEqual(len(allowed), len(set(allowed)))
        self.assertFalse(refused & set(allowed))
        self.assertTrue(any(any("ऀ" <= ch <= "ॿ" for ch in q) for q in allowed))


class PipelineAnswerSourceTests(unittest.TestCase):
    def test_guardrail_answers_are_labelled(self):
        from nepse_analyst.pipeline import run

        out = run("Will NABIL stock go up tomorrow?")
        self.assertEqual(out["route"], "OOS")
        self.assertEqual(out["answer_source"], "guardrail")


if __name__ == "__main__":
    unittest.main()
