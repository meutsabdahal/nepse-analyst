from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nepse_analyst import __version__
from nepse_analyst.chat_helpers import (
    answer_basis,
    build_passage_preview,
    data_freshness,
    extract_symbol_from_result,
    fetch_quick_facts,
    quick_fact_rows,
)
from nepse_analyst.column_labels import column_labels
from nepse_analyst.config import CHAT_RATE_LIMIT_PER_DAY, CHAT_RATE_LIMIT_PER_MINUTE
from nepse_analyst.example_questions import EXAMPLE_QUESTIONS
from nepse_analyst.messages import message
from nepse_analyst.pipeline import run
from nepse_analyst.rate_limit import SlidingWindowLimiter, retry_after_header

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(
    title="NEPSE Analyst",
    description="FastAPI chat service for NEPSE analysis queries",
    version=__version__,
)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

logger = logging.getLogger("nepse_analyst.app")


chat_limiter = SlidingWindowLimiter(
    [(CHAT_RATE_LIMIT_PER_MINUTE, 60.0), (CHAT_RATE_LIMIT_PER_DAY, 86_400.0)]
)


def client_key(request: Request) -> str:
    """The client's IP address.

    Behind a reverse proxy this is the proxy's address unless uvicorn is told
    to trust it: run with --proxy-headers --forwarded-allow-ips=<proxy IP>, so
    request.client comes from X-Forwarded-For. Headers are not read here, as
    any client can send them.
    """
    return request.client.host if request.client else "unknown"


def enforce_chat_rate_limit(request: Request) -> None:
    retry_after = chat_limiter.hit(client_key(request))
    if retry_after is not None:
        logger.warning("chat_rate_limited client=%s retry_after_sec=%.0f", client_key(request), retry_after)
        raise HTTPException(
            status_code=429,
            detail="Too many questions from this address. Please wait and try again.",
            headers={"Retry-After": retry_after_header(retry_after)},
        )


def public_error(result: dict[str, Any]) -> str | None:
    """A short code for the response. The detail is in the server log under the request ID."""
    if not result.get("error"):
        return None
    return "timeout" if result.get("answer_source") == "timeout" else "request_failed"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@app.get("/")
def root() -> FileResponse:
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=500, detail="Frontend assets are missing")
    return FileResponse(index_file)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "nepse-analyst",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/example-questions")
def example_questions() -> dict[str, list[str]]:
    return {"examples": EXAMPLE_QUESTIONS}


@app.post("/api/chat", dependencies=[Depends(enforce_chat_rate_limit)])
def chat(payload: ChatRequest) -> dict[str, Any]:
    query = payload.message.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    request_id = str(uuid4())
    started = time.perf_counter()
    try:
        result = run(query, request_id=request_id)
    except Exception:
        logger.exception("chat_unhandled_error request_id=%s", request_id)
        result = {
            "success": False,
            "answer": message("unexpected_error", "en"),
            "answer_source": "error",
            "error": "unhandled exception (see log)",
        }
    latency_ms = (time.perf_counter() - started) * 1000.0

    logger.info(
        "chat_completed request_id=%s route=%s success=%s guardrail=%s latency_ms=%.2f error=%s",
        request_id,
        result.get("route"),
        result.get("success"),
        result.get("guardrail_type"),
        latency_ms,
        result.get("error"),
    )

    try:
        symbol = extract_symbol_from_result(result, query)
        quick_facts = fetch_quick_facts(symbol) if symbol else None
        if quick_facts:
            quick_facts["rows"] = quick_fact_rows(quick_facts)
    except Exception:
        logger.exception("chat_quick_facts_error request_id=%s", request_id)
        quick_facts = None

    rows_preview = (result.get("sql_rows") or [])[:20]
    return {
        "request_id": request_id,
        "query": query,
        "answer": result.get("answer", "No response returned."),
        "success": bool(result.get("success", False)),
        "route": result.get("route"),
        "answer_basis": answer_basis(result),
        "guardrail_type": result.get("guardrail_type"),
        "query_language": result.get("query_language"),
        "data_freshness": result.get("data_freshness"),
        "freshness": data_freshness(),
        "quick_facts": quick_facts,
        "sources": {
            "sql": result.get("sql"),
            "sql_rows_preview": rows_preview,
            "columns": column_labels(list(rows_preview[0])) if rows_preview else [],
            "passages": build_passage_preview(result.get("passages") or []),
        },
        "error": public_error(result),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
