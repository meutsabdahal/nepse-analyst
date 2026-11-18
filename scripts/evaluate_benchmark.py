#!/usr/bin/env python3
"""Run benchmark evaluation and save a JSON report.

Modes:
- ground-truth: checks that every reference query runs on the local database;
  guardrail checks use the keyword guardrail only. No model calls.
- pipeline: everything a user goes through, plus the SQL generator alone.
  * sql:      generate_and_execute() on each SQL question (SQL generator only)
  * e2e:      pipeline.run() on each SQL question: routing, keyword-triggered
              rule answers, generated SQL, and the written answer
  * oos:      questions that must be refused
  * allowed:  questions that must NOT be refused (router incl. LLM)
  * rag:      top-passage relevance and retrieval coverage

SQL scores are reported two ways (see nepse_analyst/evaluation.py):
strict exact matches, and the legacy lenient score that gives half credit
for any non-empty result.

--refresh-snapshot rewrites each SQL case's ``ground_truth`` block from its
reference SQL on the current database (scoring always re-runs the reference
SQL; the snapshot is for readers of the JSON).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_analyst.database import execute_query
from nepse_analyst.evaluation import answer_mentions, key_columns, lenient_score, strict_match
from nepse_analyst.guardrails import get_guardrail_type

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
    strict_match: bool
    lenient_score: float
    status: str  # lenient label: correct / partial / incorrect / benchmark_invalid / ground_truth_ok
    error: str | None
    latency_ms: float
    sql: str | None = None


@dataclass
class E2ECaseResult:
    id: str
    request_id: str
    question: str
    route: str
    answer_source: str
    expected_rows: int
    actual_rows: int
    strict_match: bool
    lenient_score: float
    status: str
    answer_mentions_reference: bool | None
    answer: str
    sql: str | None
    error: str | None
    latency_ms: float


@dataclass
class AllowedCaseResult:
    id: str
    query: str
    route: str
    guardrail: str | None
    passed: bool
    checked_with: str  # "router" (keyword guardrail + LLM route) or "keyword-guardrail"
    latency_ms: float


@dataclass
class OOSCaseResult:
    id: str
    request_id: str
    query: str
    expected_guardrail: str
    route: str
    guardrail: str | None
    passed: bool
    latency_ms: float


@dataclass
class RAGCaseResult:
    id: str
    request_id: str
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


def _reference_rows(case: dict[str, Any]) -> tuple[list[dict] | None, str | None]:
    res = execute_query(case["ground_truth_sql"])
    if not res["success"]:
        return None, res["error"]
    return res["rows"], None


def evaluate_sql(mode: str, benchmark: dict[str, Any]) -> tuple[list[SQLCaseResult], dict[str, Any]]:
    """SQL generator only (no routing, no rule answers, no answer writing)."""
    from nepse_analyst.sql_generator import generate_and_execute

    rows: list[SQLCaseResult] = []
    for case in benchmark.get("sql_benchmark", []):
        expected, ref_error = _reference_rows(case)
        if expected is None:
            rows.append(SQLCaseResult(case["id"], case["question"], 0, None, False, 0.0,
                                      "benchmark_invalid", ref_error, 0.0))
            continue
        if mode == "ground-truth":
            rows.append(SQLCaseResult(case["id"], case["question"], len(expected), len(expected),
                                      True, 1.0, "ground_truth_ok", None, 0.0, case["ground_truth_sql"]))
            continue

        start = time.perf_counter()
        actual = generate_and_execute(case["question"])
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        actual_rows = actual["rows"] if actual["success"] else None
        score, label = lenient_score(expected, actual_rows)
        strict = actual_rows is not None and strict_match(expected, actual_rows, key_columns(case, expected))
        rows.append(SQLCaseResult(
            case["id"], case["question"], len(expected),
            len(actual_rows) if actual_rows is not None else 0,
            strict, score, label, actual.get("error"), latency_ms, actual.get("sql"),
        ))
    return rows, _sql_summary(rows)


def _sql_summary(rows: list) -> dict[str, Any]:
    scored = [r for r in rows if r.status != "benchmark_invalid"]
    total = len(rows)
    strict = [r for r in scored if r.strict_match]
    strict_nonempty = [r for r in strict if r.expected_rows > 0]
    lenient = sum(r.lenient_score for r in scored)
    labels: dict[str, int] = {}
    for r in rows:
        labels[r.status] = labels.get(r.status, 0) + 1
    return {
        "total": total,
        "strict_exact": len(strict),
        "strict_exact_nonempty_reference": len(strict_nonempty),
        "strict_exact_empty_reference": len(strict) - len(strict_nonempty),
        "strict_accuracy": round(len(strict) / max(total, 1), 4),
        "lenient_score": round(lenient, 2),
        "lenient_accuracy": round(lenient / max(total, 1), 4),
        "lenient_labels": labels,
    }


def company_aliases() -> dict[str, list[str]]:
    """Symbol -> company name forms an answer may use instead of the symbol."""
    res = execute_query("SELECT symbol, name FROM companies")
    aliases: dict[str, list[str]] = {}
    for row in res["rows"] if res["success"] else []:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        short = re.sub(r"\s+(limited|ltd\.?|company limited|co\.? ltd\.?)$", "", name, flags=re.IGNORECASE)
        aliases[str(row["symbol"]).upper()] = sorted({name, short})
    return aliases


def evaluate_e2e(benchmark: dict[str, Any]) -> tuple[list[E2ECaseResult], dict[str, Any]]:
    """pipeline.run() on each SQL question, scored on the rows behind the answer."""
    from nepse_analyst.pipeline import run as pipeline_run

    aliases = company_aliases()
    rows: list[E2ECaseResult] = []
    for case in benchmark.get("sql_benchmark", []):
        expected, ref_error = _reference_rows(case)
        request_id = f"eval:e2e:{case['id']}"
        start = time.perf_counter()
        out = pipeline_run(case["question"], request_id=request_id)
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)

        route = out.get("route") or ""
        actual_rows = out.get("sql_rows") or []
        answer = out.get("answer") or ""
        if expected is None:
            rows.append(E2ECaseResult(case["id"], request_id, case["question"], route,
                                      out.get("answer_source") or "", 0, len(actual_rows), False, 0.0,
                                      "benchmark_invalid", None, answer, out.get("sql"),
                                      ref_error, latency_ms))
            continue

        cols = key_columns(case, expected)
        if route == "OOS":
            strict, score, label = False, 0.0, "refused"
        elif route not in ("SQL", "HYBRID") or not out.get("success"):
            strict, score, label = False, 0.0, "incorrect"
        else:
            strict = strict_match(expected, actual_rows, cols)
            score, label = lenient_score(expected, actual_rows)
        rows.append(E2ECaseResult(
            case["id"], request_id, case["question"], route, out.get("answer_source") or "",
            len(expected), len(actual_rows), strict, score, label,
            answer_mentions(answer, expected, cols, aliases=aliases) if route != "OOS" else False,
            answer, out.get("sql"), out.get("error"), latency_ms,
        ))

    summary = _sql_summary(rows)
    checked = [r for r in rows if r.answer_mentions_reference is not None]
    summary["answer_mentions_reference"] = sum(1 for r in checked if r.answer_mentions_reference)
    summary["answer_mentions_checked"] = len(checked)
    sources: dict[str, int] = {}
    for r in rows:
        sources[r.answer_source] = sources.get(r.answer_source, 0) + 1
    summary["answer_sources"] = sources
    summary["routes"] = {route: sum(1 for r in rows if r.route == route) for route in sorted({r.route for r in rows})}
    return rows, summary


def evaluate_allowed(mode: str, benchmark: dict[str, Any]) -> tuple[list[AllowedCaseResult], float]:
    """Questions a user may legitimately ask; any refusal is a failure."""
    rows: list[AllowedCaseResult] = []
    for case in benchmark.get("allowed_benchmark", []):
        start = time.perf_counter()
        if mode == "ground-truth":
            guardrail = get_guardrail_type(case["query"])
            route, checked_with = ("OOS" if guardrail else "-"), "keyword-guardrail"
        else:
            from nepse_analyst.router import classify

            routing = classify(case["query"])
            route, guardrail, checked_with = routing["route"], routing.get("guardrail"), "router"
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        passed = route != "OOS" and not guardrail
        rows.append(AllowedCaseResult(case["id"], case["query"], route, guardrail, passed, checked_with, latency_ms))
    accuracy = sum(r.passed for r in rows) / max(len(rows), 1)
    return rows, accuracy


def refresh_snapshot(benchmark: dict[str, Any]) -> None:
    """Rewrite each SQL case's ground_truth block from its reference SQL."""
    snapshot_at = datetime.now(timezone.utc).date().isoformat()
    for case in benchmark.get("sql_benchmark", []):
        rows, error = _reference_rows(case)
        if rows is None:
            raise RuntimeError(f"{case['id']} reference SQL failed: {error}")
        old = case.get("ground_truth") or {}
        block: dict[str, Any] = {"snapshot_at": snapshot_at, "row_count": len(rows), "rows": rows[:25]}
        if not rows:
            block["status"] = "data_unavailable"
            if old.get("reason"):
                block["reason"] = old["reason"]
        case["ground_truth"] = block
    benchmark["generated_at"] = snapshot_at
    BENCHMARK_PATH.write_text(json.dumps(benchmark, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Refreshed ground_truth snapshots in {BENCHMARK_PATH}")


def evaluate_oos(benchmark: dict[str, Any]) -> tuple[list[OOSCaseResult], float]:
    rows: list[OOSCaseResult] = []
    passed = 0

    from nepse_analyst.pipeline import run as pipeline_run

    oos_cases = benchmark.get("oos_benchmark") or DEFAULT_OOS_BENCHMARK
    for case in oos_cases:
        request_id = f"eval:oos:{case['id']}"
        start = time.perf_counter()
        out = pipeline_run(case["query"], request_id=request_id)
        latency_ms = (time.perf_counter() - start) * 1000.0

        route = out.get("route") or ""
        guardrail = out.get("guardrail_type")
        ok = route == "OOS" and guardrail == case["expected"]
        if ok:
            passed += 1
        rows.append(
            OOSCaseResult(
                id=case["id"],
                request_id=request_id,
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
        tagged_symbols = {
            str(s).strip().upper()
            for s in (top_passage.get("symbols") or [top_passage.get("symbol", "")])
        }
        symbol_in_text = expected_symbol.lower() in text_blob
        if expected_symbol not in tagged_symbols and not symbol_in_text:
            return False

    expected_sector = (case.get("expected_sector") or "").strip().lower()
    if expected_sector:
        tagged_sectors = {
            str(s).strip().lower()
            for s in (top_passage.get("sectors") or [top_passage.get("sector", "")])
        }
        sector_token = expected_sector.split()[0] if expected_sector else ""
        sector_in_text = sector_token in text_blob if sector_token else False
        if expected_sector not in tagged_sectors and not sector_in_text:
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
        request_id = f"eval:rag:{case['id']}"
        start = time.perf_counter()
        error: str | None = None

        try:
            from nepse_analyst.retriever import search

            passages = search(
                query=case["query"],
                top_k=5,
                boost_symbol=case.get("expected_symbol") or None,
                boost_sector=case.get("expected_sector") or None,
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
                    request_id=request_id,
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
                    request_id=request_id,
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
    parser = argparse.ArgumentParser(description="Run NEPSE Analyst benchmark evaluation")
    parser.add_argument(
        "--mode",
        choices=["ground-truth", "pipeline"],
        default="ground-truth",
        help="ground-truth validates reference SQL without model calls; pipeline runs the model end to end",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output report path. Defaults to evaluation/results/report_<mode>_<timestamp>.json",
    )
    parser.add_argument(
        "--refresh-snapshot",
        action="store_true",
        help="Rewrite ground_truth blocks in the benchmark file from the current database, then exit",
    )
    args = parser.parse_args()

    benchmark = _load_benchmark()
    if args.refresh_snapshot:
        refresh_snapshot(benchmark)
        return

    sql_rows, sql_summary = evaluate_sql(args.mode, benchmark)
    e2e_rows, e2e_summary = evaluate_e2e(benchmark) if args.mode == "pipeline" else ([], None)
    oos_rows, oos_accuracy = evaluate_oos(benchmark)
    allowed_rows, allowed_accuracy = evaluate_allowed(args.mode, benchmark)
    rag_rows, rag_relevance, rag_coverage = evaluate_rag(benchmark)

    all_latency_samples = [r.latency_ms for r in sql_rows + e2e_rows + oos_rows + rag_rows]
    latency_summary = _build_latency_summary(all_latency_samples)
    e2e_latency = _build_latency_summary([r.latency_ms for r in e2e_rows])

    pipeline = args.mode == "pipeline"
    criteria = {
        "structured_query_accuracy_target_met": (e2e_summary["strict_accuracy"] >= 0.75) if pipeline else None,
        "oos_rejection_target_met": oos_accuracy >= 0.90,
        "allowed_not_refused_target_met": allowed_accuracy >= 0.90,
        "rag_relevance_target_met": rag_relevance >= 0.80,
        "latency_p95_under_8s_met": latency_summary["p95_ms"] < 8000,
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "sql": {"scope": "SQL generator only" if pipeline else "reference SQL executes (no model)", **sql_summary, "cases": [asdict(r) for r in sql_rows]},
        "e2e": (
            {"scope": "pipeline.run(): routing, rule answers, generated SQL, answer",
             **e2e_summary, "latency": e2e_latency, "cases": [asdict(r) for r in e2e_rows]}
            if pipeline else None
        ),
        "oos": {"cases": [asdict(r) for r in oos_rows], "accuracy": round(oos_accuracy, 4), "total": len(oos_rows)},
        "allowed": {
            "cases": [asdict(r) for r in allowed_rows],
            "accuracy": round(allowed_accuracy, 4),
            "total": len(allowed_rows),
            "refused": [r.id for r in allowed_rows if not r.passed],
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
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    def fmt(summary: dict[str, Any]) -> str:
        return (
            f"strict {summary['strict_exact']}/{summary['total']} "
            f"({summary['strict_exact_nonempty_reference']} with a non-empty reference); "
            f"lenient {summary['lenient_score']}/{summary['total']} ({summary['lenient_accuracy']:.1%})"
        )

    print(f"Report written: {out_path}")
    if pipeline:
        print(f"SQL generator only: {fmt(sql_summary)}")
    else:
        print(f"Reference SQL executes: {sql_summary['strict_exact']}/{sql_summary['total']} (not a model score)")
    if e2e_summary:
        print(f"End to end:         {fmt(e2e_summary)}; answer states reference values "
              f"{e2e_summary['answer_mentions_reference']}/{e2e_summary['answer_mentions_checked']}")
        print(f"  answer sources: {e2e_summary['answer_sources']}")
    print(f"OOS refused: {report['oos']['accuracy']:.2%}")
    print(f"Allowed not refused: {report['allowed']['accuracy']:.2%} (refused: {report['allowed']['refused']})")
    print(f"RAG top passage relevance: {report['rag']['top_passage_relevance']:.2%}")
    print(f"Latency p95: {report['latency']['p95_ms']:.2f} ms")


if __name__ == "__main__":
    main()
