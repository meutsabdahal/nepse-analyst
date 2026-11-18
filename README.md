# NEPSE Analyst

A natural language research assistant for Nepal's retail investors.

## Benchmark Results (Front and Center)

Latest benchmark run date: 2026-11-18.
Pipeline LLM: local Ollama `llama3.2:3b`. Data: scrape of 2026-11-17 (ingestion notebooks 01–05).

| Metric | Pipeline Mode | Ground-Truth Mode |
| --- | --- | --- |
| SQL accuracy (scored) | 4.5/12 (37.5%) | n/a (see note) |
| SQL breakdown | 1 correct, 7 partial, 4 incorrect | 12/12 benchmark queries execute |
| OOS guardrail accuracy | 10/10 (100.0%) | 10/10 (100.0%) |
| RAG top-passage relevance | 8/10 relevant (80.0%)* | 8/10 relevant (80.0%)* |
| RAG retrieval coverage | 9/10 retrieved (90.0%)* | 9/10 retrieved (90.0%)* |
| Latency p95 | 24,732.95 ms | 412.20 ms |
| Latency under 8s | 84.4% | 100.0% |

Pipeline PRD target checks: 2/4 met.

- Structured query accuracy target (≥75%): **not met** (37.5%)
- OOS rejection target (≥90%): met
- RAG relevance target (≥80%): nominally met (exactly at threshold), but see the RAG caveat below
- Latency p95 under 8s target: **not met** (24.7 s with a local 3B model)

How to read these numbers:
- SQL scoring gives 1.0 for an exact row match, 0.5 for any non-empty result when the ground truth is also non-empty ("partial", regardless of whether the values are right), and 1.0 when both results are empty. The single "correct" case (Q6) is an empty-vs-empty match on a question the data cannot answer, so no generated query reproduced a non-empty ground-truth result exactly.
- \*RAG numbers are not meaningful yet. They were measured on a 16-article corpus: the Sharesansar scraper re-read the first listing page on every request and collected site-menu links. Every article was also stamped 2016-12-15 from a site-wide meta tag, and NepseAlpha was unreachable. A passage also counts as "relevant" if it contains any one expected keyword (for example "bank"). The scraper and date parsing are fixed, and the news step now refuses a corpus this small or stale, but the vector store has not been rebuilt or re-measured since.
- Ground-truth mode does not call the model for SQL; it only checks that the benchmark's reference SQL runs against the current database, so its SQL score is not a model accuracy metric.
- Pipeline latency is dominated by local LLM inference (the first query includes model load, ~78 s). OOS and RAG cases do not call the SQL generator and stay well under 1 s.
- Results come from a single run and depend on the scraped data snapshot, so expect variation between runs.

Report files (written locally; `evaluation/results/` is gitignored):
- `evaluation/results/report_pipeline_20261118_134002.json`
- `evaluation/results/report_ground-truth_20261118_133654.json`

### Evaluation integrity

Two leaks affected pipeline SQL scoring. Both are removed.

- **Override lookup:** commit `99c9391` (2026-04-06) added `_SQL_OVERRIDES` to `nepse_analyst/sql_generator.py`. It loaded `evaluation/benchmark_questions.json` and, when a question matched a benchmark question verbatim, executed that case's `ground_truth_sql` instead of calling the LLM. Pipeline mode was therefore scoring the reference answers against themselves. Code review found the generator reading the benchmark file at runtime, and `e5dee48` removed the lookup.
- **Few-shot examples:** the SQL prompt's worked examples (`nepse_analyst/prompts.py`) copied Q1, Q4, Q6 and Q9 word for word, and paraphrased Q3 (with "top 3" for "top 5"). The Q9 example's SQL was identical to its ground truth. `d39face` replaced all six examples with questions that are not in the benchmark. `tests/test_prompt_leakage.py` now fails if an example matches or closely paraphrases a benchmark question, if an example's SQL equals a ground-truth query, or if any benchmark question appears in the rendered prompt.
- **Before vs. after:**
  - 2026-04-11, with both leaks: 12/12 (100.0%). This figure did not measure the model at all. That run also used a different model (likely Groq `llama-3.1-8b-instant`) and data snapshot.
  - 2026-11-17, override removed but leaked examples still in the prompt: 4.0/12 (33.3%).
  - 2026-11-18, both removed: 4.5/12 (37.5%).

  The last two runs use the same model and data. The leaked examples did not inflate the score: even Q9, whose exact reference SQL was in the prompt, scored only "partial" in the 33.3% run. With coarse scoring and one run each, the 0.5-point difference should not be read as an improvement.
- **Remaining prompt guidance:** rule 4 in `SCHEMA_CONTEXT` (anchor 52-week windows to the symbol's latest trade date) is general guidance, but it encodes the convention Q9's ground truth uses.
- OOS and RAG checks never used either leak.

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
- `nepse_analyst/ingestion/`: Data ingestion. `loader.py` is the single entry point; `sources/` holds one swappable class per upstream.
- `scripts/build_db.py`: Builds the database and vector store via the ingestion loader.
- `scripts/refresh_news.py`: Re-runs only the news step (scrape + re-index).

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

Build both from scratch (scrapes several sites with polite delays; expect roughly 45 minutes on a cold cache):

`uv run python scripts/build_db.py`

Run a subset of steps, or create the schema only:

`uv run python scripts/build_db.py --steps prices,indices`

`uv run python scripts/build_db.py --schema-only`

Steps run in this order: `companies`, `prices`, `indices`, `fundamentals`, `ipos`, `news`. Later steps read tables written by earlier ones (IPO listing prices come from `price_history`; news is tagged with symbols from `companies`). An article gets every company it names, matched as a whole-word symbol or by company name, plus those companies' sectors. Search ranks articles tagged with the question's company (`RAG_SYMBOL_BOOST`, default 0.1) or sector (`RAG_SECTOR_BOOST`, default 0.05) higher, but does not filter out untagged ones. Articles indexed before this change have no tag keys and get no boost until the news step re-runs.

4. Run the app

`uv run uvicorn app:app --reload`

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Data Sources

All ingestion goes through `nepse_analyst.ingestion.Loader`. Sources only return normalized records (`ingestion/records.py`); the loader owns every database and vector-store write.

| Data | Interface | Default source |
| --- | --- | --- |
| Companies | `CompanySource` | `KaggleCsvCompanySource` (`data/raw/nepse_companies_kaggle.csv`) |
| Prices, indices | `PriceSource` | `FallbackPriceSource([NepseApiSource(), GitHubOpenDataSource()])` |
| Fundamentals, dividends | `FundamentalsSource` | `MerolaganiSource` (HTML cached in `data/raw/news_cache/`) |
| IPOs | `IPOSource` | `SharesansarIPOSource` |
| News | `NewsSource` (list) | `SharesansarNewsSource`, `NepseAlphaNewsSource` |

The news step checks the scraped corpus before replacing the vector store. It fails, leaving the existing store in place, when there are fewer than `NEWS_MIN_ARTICLES` (default 50) articles after dedupe, when the newest article is older than `NEWS_MAX_NEWEST_AGE_DAYS` (default 14), or when more than half the articles have no parseable date. A source that returns nothing (NepseAlpha is often unreachable) prints a warning. Set `NEWS_ALLOW_THIN_CORPUS=1` to index anyway; the problems are still printed and returned in the step result.

`NepseApiSource` wraps the unofficial NEPSE API (the `nepse-api` client, then the nepseapi.surajrimal.dev mirror). Neither is an official feed. To replace it, implement `PriceSource` (`available`, `fetch_price_history`, `fetch_index_history`) and pass it in:

```python
from nepse_analyst.ingestion import Loader, default_sources

sources = default_sources()
sources.prices = MyOfficialFeed()
Loader(sources).run(["prices", "indices"])
```

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
