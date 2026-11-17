# NEPSE Analyst

A natural language research assistant for Nepal's retail investors.

## Benchmark Results (Front and Center)

Latest benchmark run date: 2026-11-17.
Pipeline LLM: local Ollama `llama3.2:3b`. Data: fresh scrape on 2026-11-17 (ingestion notebooks 01–05).

| Metric | Pipeline Mode | Ground-Truth Mode |
| --- | --- | --- |
| SQL accuracy (scored) | 4.0/12 (33.3%) | n/a (see note) |
| SQL breakdown | 1 correct, 6 partial, 5 incorrect | 12/12 benchmark queries execute |
| OOS guardrail accuracy | 10/10 (100.0%) | 10/10 (100.0%) |
| RAG top-passage relevance | 8/10 relevant (80.0%) | 8/10 relevant (80.0%) |
| RAG retrieval coverage | 9/10 retrieved (90.0%) | 9/10 retrieved (90.0%) |
| Latency p95 | 37,083.55 ms | 422.13 ms |
| Latency under 8s | 71.9% | 100.0% |

Pipeline PRD target checks: 2/4 met.

- Structured query accuracy target (≥75%): **not met** (33.3%)
- OOS rejection target (≥90%): met
- RAG relevance target (≥80%): met (exactly at threshold)
- Latency p95 under 8s target: **not met** (37.1 s with a local 3B model)

How to read these numbers:
- SQL scoring gives 1.0 for an exact row match, 0.5 for any non-empty result when the ground truth is also non-empty ("partial", regardless of whether the values are right), and 1.0 when both results are empty. The single "correct" case (Q6) is an empty-vs-empty match on a question the data cannot answer, so no generated query reproduced a non-empty ground-truth result exactly.
- Ground-truth mode does not call the model for SQL; it only checks that the benchmark's reference SQL runs against the current database, so its SQL score is not a model accuracy metric.
- Earlier versions of this README reported 12/12 pipeline SQL accuracy. That figure came from a lookup in `sql_generator.py` that returned the benchmark's ground-truth SQL whenever the input matched a benchmark question verbatim. The lookup has been removed; the numbers above are from the model alone.
- Pipeline latency is dominated by local LLM inference (the first query includes model load, ~78 s). OOS and RAG cases do not call the SQL generator and stay well under 1 s.
- Results come from a single run and depend on the scraped data snapshot, so expect variation between runs.

Report files (written locally; `evaluation/results/` is gitignored):
- `evaluation/results/report_pipeline_20261117_131010.json`
- `evaluation/results/report_ground-truth_20261117_130557.json`

## What It Does

NEPSE Analyst lets users ask natural-language questions about NEPSE-listed companies and returns grounded answers using:
- Structured SQL for fundamentals, price history, dividends, and IPO data.
- RAG retrieval over financial/news context.
- Guardrails that reject prediction/advice requests and inject a financial disclaimer.
- Source transparency in UI responses (SQL preview, row preview, retrieved passages).

## Current Status

Implemented:
- Hybrid query flow: SQL, RAG, HYBRID, DIRECT, and OOS guardrail routing.
- Multilingual handling for English and Nepali inputs.
- Guardrails for prediction and advice queries with mandatory disclaimer injection.
- FastAPI chat backend with a Claude-style web interface.
- Source transparency support in the chat UI (SQL preview, row preview, retrieved passages).
- Company quick-facts panel when a symbol can be inferred.
- Benchmark runner CLI for SQL and OOS reporting.

## Financial Disclaimer

NEPSE Analyst is a research information tool only. Nothing in this project constitutes financial advice. Past performance does not guarantee future results. Always consult a SEBON-registered broker or financial advisor before making investment decisions.

## Architecture

Browser Chat UI (HTML/CSS/JS)
-> FastAPI (`app.py`)
-> `nepse_analyst.pipeline.run`
-> SQL / RAG / HYBRID / DIRECT / OOS
-> Answer + metadata + source transparency

Routing logic is intent-aware, not a fixed path:
- `SQL`: selected when the question asks for precise, structured facts (for example EPS, dividend history, index comparisons, ranking/filtering).
- `RAG`: selected when the question is narrative or context-heavy (for example recent announcements, policy/regulatory context, qualitative summaries).
- `HYBRID`: selected when the same query needs both hard numbers and contextual explanation, so the pipeline combines SQL evidence with retrieved passages in one response.
- `OOS`: selected when a query asks for prediction/advice and must be refused via guardrails.

This routing layer is important for ambiguous real-world prompts because users rarely label their intent; the system infers it and chooses the minimum-cost path that still preserves answer quality and transparency.

Core package lives in `nepse_analyst/` and frontend assets live in `web/`.

## Repository Layout

- `app.py`: FastAPI server entrypoint and API routes.
- `web/index.html`: Chat UI shell.
- `web/styles.css`: Claude-style visual theme.
- `web/app.js`: Chat client logic.
- `nepse_analyst/pipeline.py`: End-to-end query orchestration.
- `nepse_analyst/chat_helpers.py`: Symbol detection and quick-facts data helpers.
- `nepse_analyst/example_questions.py`: Example prompts for UI.
- `nepse_analyst/router.py`: Query routing and entity extraction.
- `nepse_analyst/sql_generator.py`: Text-to-SQL generation and execution.
- `nepse_analyst/retriever.py`: ChromaDB retrieval.
- `nepse_analyst/guardrails.py`: Advice/prediction rejection logic.
- `scripts/evaluate_benchmark.py`: Benchmark runner.
- `scripts/build_db.py`: Database schema build command.
- `scripts/refresh_news.py`: News refresh command wrapper.

## Quick Start

Prerequisites:
- Python 3.12+
- Local data artifacts prepared (SQLite DB and vector store)
- Optional: Groq API key for cloud LLM mode

1. Install dependencies

`uv sync`

Environment note (recommended workflow):
- Use `uv run ...` for all project commands.
- You do not need to activate a virtual environment manually.
- If `source .venv/bin/activate` fails in your shell, continue with `uv run` commands.

2. Configure environment

Copy `.env.example` to `.env` and set values:
- `LLM_PROVIDER=groq` or `LLM_PROVIDER=ollama`
- `GROQ_API_KEY=...` (if using Groq)
- `OLLAMA_MODEL=llama3.2:3b` (if using Ollama)

3. Ensure data artifacts exist

- SQLite DB: `data/processed/nepse.db`
- ChromaDB directory: `data/vector_store/`

If DB schema is missing:

`uv run python scripts/build_db.py`

For full ingestion/index refresh use notebooks:
- `notebooks/ingest_companies.ipynb`
- `notebooks/ingest_price_history.ipynb`
- `notebooks/ingest_fundamentals.ipynb`
- `notebooks/ingest_ipos.ipynb`
- `notebooks/ingest_news.ipynb`

4. Run the app

`uv run uvicorn app:app --reload`

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API Endpoints

- `GET /`: Chat web interface.
- `GET /api/health`: Service health probe.
- `GET /api/example-questions`: Example prompt list.
- `POST /api/chat`: Query endpoint.

Sample request:

```json
{
  "message": "Which commercial bank has the highest EPS in the latest fiscal year?"
}
```

## Evaluation

Run benchmark in ground-truth mode:
- Validates that benchmark reference SQL executes against the DB (does not exercise the model)
- Runs OOS guardrail checks
- Runs RAG retrieval relevance checks
- Emits per-query latency summary

`uv run python scripts/evaluate_benchmark.py --mode ground-truth`

Run benchmark in pipeline mode (requires configured LLM):
- Scores model SQL generation against benchmark ground truth
- Runs OOS and RAG relevance checks
- Emits PRD target flags in the report (`criteria`)

`uv run python scripts/evaluate_benchmark.py --mode pipeline`

Reports are written to `evaluation/results/` as JSON.

## Tests

Run regression tests:

`uv run python -m unittest discover -s tests -p "test_*.py"`

Tip: keep using `uv run` for scripts and tests instead of relying on shell activation.

Troubleshooting (TestClient mismatch):
- If you see `TypeError: Client.__init__() got an unexpected keyword argument 'follow_redirects'`, your Starlette and httpx versions are incompatible.
- Short-term: prefer function-level API handler tests (as in `tests/test_app_api.py`) instead of `fastapi.testclient.TestClient`.
- Long-term: align FastAPI/Starlette/httpx dependency versions in one update.

## Known Data Constraints

From current benchmark dataset snapshot:
- Q3 is data_unavailable due to missing market_cap values.
- Q6 is data_unavailable due to missing IPO oversubscription_rate values.
- Q10 is data_unavailable due to missing microfinance fundamentals coverage.
- Q5's reference SQL lists every non-null EPS row rather than filtering for 3 consecutive years of growth, so it does not answer its question; the 2026-11-17 scrape also has mostly one fiscal year of fundamentals per company.

These are expected data coverage limitations and should be documented in evaluation results.

## License

MIT License. See LICENSE.

Data sources are third-party and used for educational, non-commercial portfolio purposes only.
