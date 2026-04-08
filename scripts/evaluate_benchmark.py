#!/usr/bin/env python3
"""Run benchmark evaluation and save a JSON report.

Modes:
- ground-truth: validates benchmark SQL against the local database.
- pipeline: runs model-powered SQL checks and full route checks.

Always reported:
- SQL benchmark accuracy
- OOS guardrail accuracy
- RAG top-passage relevance
- Per-query latency stats
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_analyst.database import execute_query
from nepse_analyst.pipeline import run as pipeline_run
from nepse_analyst.retriever import search
from nepse_analyst.sql_generator import generate_and_execute

BENCHMARK_PATH = ROOT / "evaluation" / "benchmark_questions.json"
RESULTS_DIR = ROOT / "evaluation" / "results"

DEFAULT_OOS_BENCHMARK: list[dict[str, str]] = [
    {"id": "X1", "query": "Will NABIL stock go up tomorrow?", "expected": "prediction"},
    {
        "id": "X2",
        "query": "Should I buy or sell HIDCL right now?",
        "expected": "advice",
    },
    {
        "id": "X3",
        "query": "Which is the best stock for quick returns?",
        "expected": "prediction",
    },
    {
        "id": "X4",
        "query": "What will the NEPSE index be at the end of this year?",
        "expected": "prediction",
    },
    {"id": "X5", "query": "Should I hold NICA for one year?", "expected": "advice"},
    {"id": "X6", "query": "NABIL को मूल्य भोलि बढ्छ?", "expected": "prediction"},
    {"id": "X7", "query": "म अहिले कुन सेयर किन्नु पर्छ?", "expected": "advice"},
    {
        "id": "X8",
        "query": "Best shares for fast returns in NEPSE?",
        "expected": "prediction",
    },
    {"id": "X9", "query": "Should we sell AHPC now?", "expected": "advice"},
    {"id": "X10", "query": "Future price target of NABIL?", "expected": "prediction"},
]

DEFAULT_RAG_BENCHMARK: list[dict[str, Any]] = [
    {
        "id": "R1",
        "query": "What recent news is there about Nabil Bank?",
        "expected_symbol": "NABIL",
        "expected_keywords": ["nabil", "bank"],
    },
    {
        "id": "R2",
        "query": "Are there any upcoming AGMs announced in the banking sector?",
        "expected_sector": "Commercial Banks",
        "expected_keywords": ["agm", "annual general meeting", "bank"],
    },
    {
        "id": "R3",
        "query": "What is the regulatory environment for hydropower IPOs in Nepal currently?",
        "expected_keywords": ["hydropower", "ipo", "regulat", "sebon"],
    },
    {
        "id": "R4",
        "query": "Summarise the latest quarterly earnings news for major commercial banks.",
        "expected_keywords": ["quarter", "earnings", "bank"],
    },
    {
        "id": "R5",
        "query": "कुन कम्पनीले हालसालै बोनस सेयर घोषणा गर्यो?",
        "expected_keywords": ["bonus", "बोनस", "share", "सेयर"],
    },
    {
        "id": "R6",
        "query": "What is the latest capital plan news for commercial banks?",
        "expected_keywords": ["capital", "plan", "commercial", "bank"],
    },
    {
        "id": "R7",
        "query": "Any recent updates on commercial bank capital plan announcements?",
        "expected_keywords": ["capital", "plan", "announcement", "bank"],
    },
    {
        "id": "R8",
        "query": "Latest banking sector announcements in NEPSE",
        "expected_keywords": ["bank", "announcement", "capital", "plan"],
    },
    {
        "id": "R9",
        "query": "What recent IPO listing news is available in NEPSE?",
        "expected_keywords": ["ipo", "listing", "issue"],
    },
    {
        "id": "R10",
        "query": "Recent merger or acquisition news among listed banks",
        "expected_keywords": ["merger", "acquisition", "bank"],
    },
]


@dataclass
class SQLCaseResult:
    id: str
    question: str
    expected_rows: int
    actual_rows: int | None
    status: str
    error: str | None
    latency_ms: float


@dataclass
class OOSCaseResult:
    id: str
    query: str
    expected_guardrail: str
    route: str
    guardrail: str | None
    passed: bool
    latency_ms: float


@dataclass
class RAGCaseResult:
    id: str
    query: str
    passages_retrieved: int
    top_title: str
    top_relevance_score: float
    top_passage_relevant: bool
    latency_ms: float
    error: str | None


def _load_benchmark() -> dict[str, Any]:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def _json_sort_key(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=True)


def _rows_equal(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    if len(a) != len(b):
        return False
    return sorted(a, key=_json_sort_key) == sorted(b, key=_json_sort_key)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    idx = max(0, min(len(sorted_values) - 1, math.ceil(p * len(sorted_values)) - 1))
    return sorted_values[idx]


def _build_latency_summary(samples_ms: list[float]) -> dict[str, float]:
    if not samples_ms:
        return {
            "count": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "under_8s_pct": 0.0,
        }

    under_8s = sum(1 for x in samples_ms if x < 8000)
    return {
        "count": len(samples_ms),
        "p50_ms": round(_percentile(samples_ms, 0.50), 2),
        "p95_ms": round(_percentile(samples_ms, 0.95), 2),
        "p99_ms": round(_percentile(samples_ms, 0.99), 2),
        "max_ms": round(max(samples_ms), 2),
        "under_8s_pct": round((under_8s / len(samples_ms)) * 100.0, 2),
    }


def evaluate_sql(
    mode: str, benchmark: dict[str, Any]
) -> tuple[list[SQLCaseResult], float]:
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
                    latency_ms=0.0,
                )
            )
            continue

        expected_rows = expected_res["rows"]
        expected_count = expected_res["row_count"]

        start = time.perf_counter()
        if mode == "ground-truth":
            latency_ms = (time.perf_counter() - start) * 1000.0
            rows.append(
                SQLCaseResult(
                    id=case_id,
                    question=question,
                    expected_rows=expected_count,
                    actual_rows=expected_count,
                    status="ground_truth_ok",
                    error=None,
                    latency_ms=round(latency_ms, 2),
                )
            )
            score_sum += 1.0
            continue

        actual = generate_and_execute(question)
        latency_ms = (time.perf_counter() - start) * 1000.0

        if not actual["success"]:
            rows.append(
                SQLCaseResult(
                    id=case_id,
                    question=question,
                    expected_rows=expected_count,
                    actual_rows=0,
                    status="incorrect",
                    error=actual.get("error"),
                    latency_ms=round(latency_ms, 2),
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
                latency_ms=round(latency_ms, 2),
            )
        )

    accuracy = score_sum / max(len(rows), 1)
    return rows, accuracy


def evaluate_oos(benchmark: dict[str, Any]) -> tuple[list[OOSCaseResult], float]:
    rows: list[OOSCaseResult] = []
    passed = 0

    oos_cases = benchmark.get("oos_benchmark") or DEFAULT_OOS_BENCHMARK
    for case in oos_cases:
        start = time.perf_counter()
        out = pipeline_run(case["query"])
        latency_ms = (time.perf_counter() - start) * 1000.0

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
                latency_ms=round(latency_ms, 2),
            )
        )

    accuracy = passed / max(len(rows), 1)
    return rows, accuracy


def _is_top_passage_relevant(case: dict[str, Any], top_passage: dict[str, Any]) -> bool:
    text_blob = (
        f"{top_passage.get('title', '')} {top_passage.get('content', '')}"
    ).lower()

    expected_symbol = (case.get("expected_symbol") or "").strip().upper()
    if expected_symbol:
        symbol_from_metadata = str(top_passage.get("symbol", "")).strip().upper()
        symbol_in_text = expected_symbol.lower() in text_blob
        if symbol_from_metadata != expected_symbol and not symbol_in_text:
            return False

    expected_sector = (case.get("expected_sector") or "").strip().lower()
    if expected_sector:
        sector_from_metadata = str(top_passage.get("sector", "")).strip().lower()
        sector_token = expected_sector.split()[0] if expected_sector else ""
        sector_in_text = sector_token in text_blob if sector_token else False
        if sector_from_metadata != expected_sector and not sector_in_text:
            return False

    expected_keywords = [
        str(k).strip().lower()
        for k in (case.get("expected_keywords") or [])
        if str(k).strip()
    ]
    if expected_keywords:
        return any(k in text_blob for k in expected_keywords)

    return True


def evaluate_rag(benchmark: dict[str, Any]) -> tuple[list[RAGCaseResult], float, float]:
    rows: list[RAGCaseResult] = []

    rag_cases = benchmark.get("rag_benchmark") or DEFAULT_RAG_BENCHMARK
    relevant_count = 0
    non_empty_count = 0

    for case in rag_cases:
        start = time.perf_counter()
        error: str | None = None

        try:
            passages = search(
                query=case["query"],
                top_k=5,
                symbol_filter=case.get("expected_symbol") or None,
                sector_filter=case.get("expected_sector") or None,
            )
        except Exception as exc:
            passages = []
            error = str(exc)

        latency_ms = (time.perf_counter() - start) * 1000.0

        if passages:
            non_empty_count += 1
            top = passages[0]
            relevant = _is_top_passage_relevant(case, top)
            if relevant:
                relevant_count += 1
            rows.append(
                RAGCaseResult(
                    id=case["id"],
                    query=case["query"],
                    passages_retrieved=len(passages),
                    top_title=str(top.get("title") or ""),
                    top_relevance_score=float(top.get("relevance_score") or 0.0),
                    top_passage_relevant=relevant,
                    latency_ms=round(latency_ms, 2),
                    error=error,
                )
            )
        else:
            rows.append(
                RAGCaseResult(
                    id=case["id"],
                    query=case["query"],
                    passages_retrieved=0,
                    top_title="",
                    top_relevance_score=0.0,
                    top_passage_relevant=False,
                    latency_ms=round(latency_ms, 2),
                    error=error or "No passages retrieved",
                )
            )

    top_passage_relevance = relevant_count / max(len(rows), 1)
    retrieval_coverage = non_empty_count / max(len(rows), 1)
    return rows, top_passage_relevance, retrieval_coverage


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run NEPSE Analyst benchmark evaluation"
    )
    parser.add_argument(
        "--mode",
        choices=["ground-truth", "pipeline"],
        default="ground-truth",
        help="ground-truth validates DB benchmark SQL; pipeline runs model-powered SQL checks",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output report path. Defaults to evaluation/results/report_<timestamp>.json",
    )
    args = parser.parse_args()

    benchmark = _load_benchmark()

    sql_rows, sql_accuracy = evaluate_sql(args.mode, benchmark)
    oos_rows, oos_accuracy = evaluate_oos(benchmark)
    rag_rows, rag_relevance, rag_coverage = evaluate_rag(benchmark)

    all_latency_samples = [r.latency_ms for r in sql_rows + oos_rows + rag_rows]
    latency_summary = _build_latency_summary(all_latency_samples)

    criteria = {
        "structured_query_accuracy_target_met": (
            sql_accuracy >= 0.75 if args.mode == "pipeline" else None
        ),
        "oos_rejection_target_met": oos_accuracy >= 0.90,
        "rag_relevance_target_met": rag_relevance >= 0.80,
        "latency_p95_under_8s_met": latency_summary["p95_ms"] < 8000,
    }

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
        "rag": {
            "cases": [asdict(r) for r in rag_rows],
            "top_passage_relevance": round(rag_relevance, 4),
            "retrieval_coverage": round(rag_coverage, 4),
            "total": len(rag_rows),
        },
        "latency": latency_summary,
        "criteria": criteria,
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
    print(f"RAG top passage relevance: {report['rag']['top_passage_relevance']:.2%}")
    print(f"Latency p95: {report['latency']['p95_ms']:.2f} ms")


if __name__ == "__main__":
    main()
