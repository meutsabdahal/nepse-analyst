#!/usr/bin/env python3
"""Run benchmark evaluation and save a JSON report.

Modes:
- ground-truth: validates benchmark SQL against the local database.
- pipeline: runs the full pipeline for SQL and OOS checks (requires configured LLM).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_analyst.database import execute_query
from nepse_analyst.pipeline import run as pipeline_run
from nepse_analyst.sql_generator import generate_and_execute

BENCHMARK_PATH = ROOT / "evaluation" / "benchmark_questions.json"
RESULTS_DIR = ROOT / "evaluation" / "results"

OOS_BENCHMARK: list[dict[str, str]] = [
    {"id": "X1", "query": "Will NABIL stock go up tomorrow?", "expected": "prediction"},
    {"id": "X2", "query": "Should I buy or sell HIDCL right now?", "expected": "advice"},
    {"id": "X3", "query": "Which is the best stock for quick returns?", "expected": "prediction"},
    {"id": "X4", "query": "What will the NEPSE index be at the end of this year?", "expected": "prediction"},
    {"id": "X5", "query": "Should I hold NICA for one year?", "expected": "advice"},
    {"id": "X6", "query": "NABIL को मूल्य भोलि बढ्छ?", "expected": "prediction"},
    {"id": "X7", "query": "म अहिले कुन सेयर किन्नु पर्छ?", "expected": "advice"},
    {"id": "X8", "query": "Best shares for fast returns in NEPSE?", "expected": "prediction"},
    {"id": "X9", "query": "Should we sell AHPC now?", "expected": "advice"},
    {"id": "X10", "query": "Future price target of NABIL?", "expected": "prediction"},
]


@dataclass
class SQLCaseResult:
    id: str
    question: str
    expected_rows: int
    actual_rows: int | None
    status: str
    error: str | None


@dataclass
class OOSCaseResult:
    id: str
    query: str
    expected_guardrail: str
    route: str
    guardrail: str | None
    passed: bool


def _load_benchmark() -> dict[str, Any]:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def _json_sort_key(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=True)


def _rows_equal(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    if len(a) != len(b):
        return False
    return sorted(a, key=_json_sort_key) == sorted(b, key=_json_sort_key)


def evaluate_sql(mode: str, benchmark: dict[str, Any]) -> tuple[list[SQLCaseResult], float]:
    rows: list[SQLCaseResult] = []
    score_sum = 0.0

    for case in benchmark.get("sql_benchmark", []):
        case_id = case["id"]
        question = case["question"]

        expected_res = execute_query(case["ground_truth_sql"])
        if not expected_res["success"]:
            rows.append(
                SQLCaseResult(
                    id=case_id,
                    question=question,
                    expected_rows=0,
                    actual_rows=None,
                    status="benchmark_invalid",
                    error=expected_res["error"],
                )
            )
            continue

        expected_rows = expected_res["rows"]
        expected_count = expected_res["row_count"]

        if mode == "ground-truth":
            rows.append(
                SQLCaseResult(
                    id=case_id,
                    question=question,
                    expected_rows=expected_count,
                    actual_rows=expected_count,
                    status="ground_truth_ok",
                    error=None,
                )
            )
            score_sum += 1.0
            continue

        actual = generate_and_execute(question)
        if not actual["success"]:
            rows.append(
                SQLCaseResult(
                    id=case_id,
                    question=question,
                    expected_rows=expected_count,
                    actual_rows=0,
                    status="incorrect",
                    error=actual.get("error"),
                )
            )
            continue

        actual_rows = actual["rows"]
        if _rows_equal(expected_rows, actual_rows):
            status = "correct"
            score_sum += 1.0
        elif expected_count == 0 and actual["row_count"] == 0:
            status = "correct"
            score_sum += 1.0
        elif actual["row_count"] > 0 and expected_count > 0:
            status = "partial"
            score_sum += 0.5
        else:
            status = "incorrect"

        rows.append(
            SQLCaseResult(
                id=case_id,
                question=question,
                expected_rows=expected_count,
                actual_rows=actual["row_count"],
                status=status,
                error=None,
            )
        )

    accuracy = score_sum / max(len(rows), 1)
    return rows, accuracy


def evaluate_oos() -> tuple[list[OOSCaseResult], float]:
    rows: list[OOSCaseResult] = []
    passed = 0

    for case in OOS_BENCHMARK:
        out = pipeline_run(case["query"])
        route = out.get("route") or ""
        guardrail = out.get("guardrail_type")
        ok = route == "OOS" and guardrail == case["expected"]
        if ok:
            passed += 1
        rows.append(
            OOSCaseResult(
                id=case["id"],
                query=case["query"],
                expected_guardrail=case["expected"],
                route=route,
                guardrail=guardrail,
                passed=ok,
            )
        )

    accuracy = passed / max(len(rows), 1)
    return rows, accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NEPSE Analyst benchmark evaluation")
    parser.add_argument(
        "--mode",
        choices=["ground-truth", "pipeline"],
        default="ground-truth",
        help="ground-truth validates DB benchmark SQL; pipeline runs model-powered checks",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output report path. Defaults to evaluation/results/report_<timestamp>.json",
    )
    args = parser.parse_args()

    benchmark = _load_benchmark()

    sql_rows, sql_accuracy = evaluate_sql(args.mode, benchmark)
    oos_rows, oos_accuracy = evaluate_oos()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "sql": {
            "cases": [asdict(r) for r in sql_rows],
            "accuracy": round(sql_accuracy, 4),
            "total": len(sql_rows),
        },
        "oos": {
            "cases": [asdict(r) for r in oos_rows],
            "accuracy": round(oos_accuracy, 4),
            "total": len(oos_rows),
        },
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"report_{args.mode}_{ts}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Report written: {out_path}")
    print(f"SQL accuracy: {report['sql']['accuracy']:.2%}")
    print(f"OOS accuracy: {report['oos']['accuracy']:.2%}")


if __name__ == "__main__":
    main()
