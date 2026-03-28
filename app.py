from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nepse_analyst.chat_helpers import build_passage_preview, extract_symbol_from_result, fetch_quick_facts
from nepse_analyst.example_questions import EXAMPLE_QUESTIONS
from nepse_analyst.pipeline import run

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(
    title="NEPSE Analyst",
    description="FastAPI chat service for NEPSE analysis queries",
    version="2.0.0",
)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


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


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    query = payload.message.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    result = run(query)
    symbol = extract_symbol_from_result(result, query)
    quick_facts = fetch_quick_facts(symbol) if symbol else None

    return {
        "query": query,
        "answer": result.get("answer", "No response returned."),
        "success": bool(result.get("success", False)),
        "route": result.get("route"),
        "guardrail_type": result.get("guardrail_type"),
        "query_language": result.get("query_language"),
        "data_freshness": result.get("data_freshness"),
        "quick_facts": quick_facts,
        "sources": {
            "sql": result.get("sql"),
            "sql_rows_preview": (result.get("sql_rows") or [])[:20],
            "passages": build_passage_preview(result.get("passages") or []),
        },
        "error": result.get("error"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
