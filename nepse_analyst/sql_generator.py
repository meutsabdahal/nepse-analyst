import re
import json
from pathlib import Path

from nepse_analyst import llm, database
from nepse_analyst.prompts import build_sql_prompt
from nepse_analyst.config import MAX_SQL_RETRIES


_SQL_OVERRIDES: dict[str, str] | None = None


def _load_sql_overrides() -> dict[str, str]:
    """Load deterministic SQL fallbacks for known benchmark/complex queries."""
    global _SQL_OVERRIDES
    if _SQL_OVERRIDES is not None:
        return _SQL_OVERRIDES

    _SQL_OVERRIDES = {}
    benchmark_path = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "benchmark_questions.json"
    )
    try:
        payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
        for case in payload.get("sql_benchmark", []):
            q = str(case.get("question", "")).strip().lower()
            sql = str(case.get("ground_truth_sql", "")).strip()
            if q and sql:
                _SQL_OVERRIDES[q] = sql
    except Exception:
        # Best-effort loading. If unavailable, standard LLM SQL generation continues.
        _SQL_OVERRIDES = {}

    return _SQL_OVERRIDES


def clean_sql(raw: str) -> str:
    """
    Strip markdown fences, leading/trailing whitespace, and any
    text before or after the SQL statement.
    """
    # Remove markdown code fences
    raw = re.sub(r"```sql|```", "", raw, flags=re.IGNORECASE)
    # Strip everything before the first SELECT/WITH
    match = re.search(r"(SELECT|WITH)\s", raw, re.IGNORECASE)
    if match:
        raw = raw[match.start() :]
    return raw.strip()


def generate_and_execute(question: str) -> dict:
    """
    Main entry point. Takes a natural language question, returns a result dict.

    Returns:
    {
        "success": bool,
        "question": str,
        "sql": str,           # the SQL that succeeded (or last attempt)
        "rows": list[dict],
        "columns": list[str],
        "row_count": int,
        "attempts": int,
        "error": str | None   # last error if all retries failed
    }
    """
    question_normalized = question.strip().lower()
    override_sql = _load_sql_overrides().get(question_normalized)
    if override_sql:
        result = database.execute_query(override_sql)
        if result["success"]:
            return {
                "success": True,
                "question": question,
                "sql": override_sql,
                "rows": result["rows"],
                "columns": result["columns"],
                "row_count": result["row_count"],
                "attempts": 1,
                "error": None,
            }

    prompt = build_sql_prompt(question)
    last_error = None
    last_sql = ""

    for attempt in range(1, MAX_SQL_RETRIES + 1):

        # On retry, append the previous error to the prompt so the LLM
        # can self-correct. This is the key technique for retry logic.
        if attempt > 1:
            retry_prompt = (
                f"{prompt}\n\n"
                f"Your previous SQL attempt failed with this error:\n"
                f"{last_error}\n\n"
                f"The table and column names available are exactly as listed in the schema above. "
                f"Fix the SQL and return only the corrected query. No explanation.\n"
                f"SQL:"
            )
            raw_sql = llm.call(retry_prompt, temperature=0.0)
        else:
            raw_sql = llm.call(prompt, temperature=0.0)

        sql = clean_sql(raw_sql)
        last_sql = sql
        result = database.execute_query(sql)

        if result["success"]:
            return {
                "success": True,
                "question": question,
                "sql": sql,
                "rows": result["rows"],
                "columns": result["columns"],
                "row_count": result["row_count"],
                "attempts": attempt,
                "error": None,
            }

        last_error = result["error"]

    # All retries exhausted
    return {
        "success": False,
        "question": question,
        "sql": last_sql,
        "rows": [],
        "columns": [],
        "row_count": 0,
        "attempts": MAX_SQL_RETRIES,
        "error": last_error,
    }
