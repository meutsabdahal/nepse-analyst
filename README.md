# NEPSE Analyst

A natural language research assistant for Nepal's retail investors.

## Benchmark Results (Front and Center)

Latest benchmark run: 2026-11-18. Pipeline LLM: local Ollama `llama3.2:3b`. Data: database built 2026-11-17 16:23 (includes the 2025–26 index history from `b110eb1`).

This run predates two benchmark changes: market cap is now populated (Q3's reference was empty then and now has 5 rows), and Q5 and Q6 are no longer scored, so the benchmark has 10 SQL questions (see Known Data Constraints). The results below are from the 12-question run and have not been re-measured since.

Pipeline mode now evaluates what a user gets: `pipeline.run()` on each SQL question (routing, keyword-triggered rule answers, generated SQL, written answer), plus the SQL generator alone for comparison.

| Metric | Pipeline mode | Ground-truth mode |
| --- | --- | --- |
| SQL end to end, strict exact | **3/12** (2 with a non-empty reference: Q1, Q8; 1 empty: Q5) | n/a |
| SQL end to end, lenient (legacy) | 3.5/12 (29.2%): 1 correct, 5 partial, 6 incorrect | n/a |
| Answer text states the reference values | 1/8 (Q1) | n/a |
| SQL generator alone, strict / lenient | 3/12 / 3.5/12 (same cases as end to end) | 12/12 reference queries execute |
| Answer source | 12/12 generated SQL; rule answers never fired | n/a |
| Must refuse (OOS) | 10/10 | 10/10 |
| Must not refuse | **2/10** (8 refused by keyword guardrail) | 2/10 (keyword guardrail only) |
| RAG top-passage relevance | 8/10* | 8/10* |
| RAG retrieval coverage | 10/10* | 10/10* |
| Latency per end-to-end SQL answer | p50 162 s, p95 266 s | n/a |
| Latency p95, all cases | 235,858 ms | 423 ms |

Pipeline target checks: 2/5 met.

- Structured query accuracy (≥75%, end to end, strict): **not met** (25%)
- OOS rejection (≥90%): met
- Must-not-refuse (≥90%): **not met** (20%)
- RAG relevance (≥80%): nominally met (exactly at threshold), but see the RAG caveat below
- Latency p95 under 8 s: **not met**

How to read these numbers:
- **Strict exact** (`nepse_analyst/evaluation.py`): same row count as the reference, and each reference row's key values (`match_columns` in `evaluation/benchmark_questions.json`) appear in its own result row. Column names are ignored and numbers match within rounding. Q8's strict match is partly luck: its SQL ignores the "latest fiscal year" and the written answer misstates the value (6,445.1 for 6,645.1).
- **Lenient** is the score the README used to report: 0.5 for *any* non-empty result when the reference is non-empty, whether or not the values are right. It is kept only for comparison with older reports.
- **Answer text** checks that the final answer states every reference key value (a company name counts for its symbol). Of the 8 questions with a non-empty reference, only Q1's answer does. Failures include Q4 (queried `indices` instead of sectors), Q9 (all-time range, quoted in dollars) and several "no data found" answers.
- **Rule answers:** `pipeline.py` has keyword-triggered SQL for dividend streaks and 52-week ranges, but these only run when the generated SQL fails or returns nothing, and none did in this run. `answer_source` in each report case shows which path answered.
- **Must not refuse** (`allowed_benchmark`): questions such as "What should I know about P/E?" and Nepali questions containing "भोलि" (tomorrow). The keyword guardrail refuses them before the LLM router sees them. The guardrail has not been changed yet.
- \*RAG numbers are not meaningful yet. They were measured on a 16-article corpus: the Sharesansar scraper re-read the first listing page on every request and collected site-menu links. Every article was also stamped 2016-12-15 from a site-wide meta tag, and NepseAlpha was unreachable. A passage also counts as "relevant" if it contains any one expected keyword (for example "bank"). The scraper and date parsing are fixed, and the news step now refuses a corpus this small or stale, but the vector store has not been rebuilt or re-measured since.
- **Ground-truth mode** makes no model calls: it checks that the reference SQL runs, and checks must-not-refuse questions against the keyword guardrail only.
- **Latency:** an end-to-end answer makes several local LLM calls (routing, SQL, answer writing; HYBRID routes also retrieve and summarise news). The SQL generator alone took 5–38 s per question. Since this run, each question has a time budget (`REQUEST_TIMEOUT_SEC`, default 60 s) shared by all of its LLM calls and SQL queries; each call gets at most the time left (`LLM_TIMEOUT_SEC` 120 s per call, `ROUTER_TIMEOUT_SEC` 15 s for routing, `SQL_TIMEOUT_MS` 5 s per query). A question that runs out returns a timeout answer (`answer_source: "timeout"`). With a slow local model such as the one above, raise `REQUEST_TIMEOUT_SEC` or most questions will time out.
- Results come from a single run and depend on the data snapshot, so expect variation between runs. These numbers are not comparable with the earlier 37.5% figure: that was the lenient score of the SQL generator alone, before the prompt schema was generated from the database and before the Q2 and Q5 reference SQL was fixed.

Report files (written locally; `evaluation/results/` is gitignored):
- `evaluation/results/report_pipeline_20261118_145609.json` (answer-text check rescored after adding company-name aliases)
- `evaluation/results/report_ground-truth_20261118_141507.json`

### Evaluation integrity

Two leaks affected pipeline SQL scoring. Both are removed.

- **Override lookup:** commit `99c9391` (2026-04-06) added `_SQL_OVERRIDES` to `nepse_analyst/sql_generator.py`. It loaded `evaluation/benchmark_questions.json` and, when a question matched a benchmark question verbatim, executed that case's `ground_truth_sql` instead of calling the LLM. Pipeline mode was therefore scoring the reference answers against themselves. Code review found the generator reading the benchmark file at runtime, and `e5dee48` removed the lookup.
- **Few-shot examples:** the SQL prompt's worked examples (`nepse_analyst/prompts.py`) copied Q1, Q4, Q6 and Q9 word for word, and paraphrased Q3 (with "top 3" for "top 5"). The Q9 example's SQL was identical to its ground truth. `d39face` replaced all six examples with questions that are not in the benchmark. `tests/test_prompt_leakage.py` now fails if an example matches or closely paraphrases a benchmark question, if an example's SQL equals a ground-truth query, or if any benchmark question appears in the rendered prompt.
- **Before vs. after** (lenient score of the SQL generator alone, the only score reported at the time):
  - 2026-04-11, with both leaks: 12/12 (100.0%). This figure did not measure the model at all. That run also used a different model (likely Groq `llama-3.1-8b-instant`) and data snapshot.
  - 2026-11-17 13:10, override removed but leaked examples still in the prompt: 4.0/12 (33.3%).
  - 2026-11-18 13:40, both removed: 4.5/12 (37.5%).

  These two runs used the same model but **not** the same data: the database was rebuilt at 16:23 on 2026-11-17, between them, which also replaced the index history (Q11's reference window moved from 2007 to 2025–26). The 0.5-point difference therefore says nothing about the leaked examples. Even Q9, whose exact reference SQL was in the prompt, scored only "partial" in the 33.3% run.
- **Remaining prompt guidance:** the SQL prompt's schema section is generated from the live database (`nepse_analyst/schema_context.py`). Its rule 3 (anchor relative windows such as "52-week" to the latest date in the data) is general guidance, but it encodes the convention Q9's ground truth uses.
- OOS and RAG checks never used either leak.

## What It Does

NEPSE Analyst lets users ask natural-language questions about NEPSE-listed companies and returns grounded answers using:
- Structured SQL for fundamentals, price history, dividends, and IPO data.
- RAG retrieval over financial/news context.
- Guardrails that reject prediction/advice requests.
- Source transparency in UI responses (SQL preview, row preview, retrieved passages).

## Current Status

Implemented:
- Hybrid query flow: SQL, RAG, HYBRID, DIRECT, and OOS guardrail routing.
- Multilingual handling for English and Nepali inputs.
- Guardrails for prediction and advice queries.
- FastAPI chat backend with a Claude-style web interface.
- Source transparency support in the chat UI (SQL preview, row preview, retrieved passages).
- Company quick-facts panel when a symbol can be inferred.
- Benchmark runner CLI for SQL and OOS reporting.

## Financial Disclaimer

NEPSE Analyst is a research information tool only. Answers are not followed by a per-answer disclaimer (removed in `cb105ab`); this notice applies to all of them. Nothing in this project constitutes financial advice. Past performance does not guarantee future results. Always consult a SEBON-registered broker or financial advisor before making investment decisions.

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
- `nepse_analyst/example_questions.py`: Example questions for the UI, grouped by type and limited to what the current data can answer.
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

### Deploying publicly

Every `/api/chat` or `/api/chat/stream` request can make several LLM calls, which cost credits with Groq or Hugging Face. The endpoint is rate limited per client IP: `CHAT_RATE_LIMIT_PER_MINUTE` (default 10) and `CHAT_RATE_LIMIT_PER_DAY` (default 200). Over the limit it returns HTTP 429 with a `Retry-After` header.

- **Behind a reverse proxy or load balancer**, every request arrives from the proxy's address, so all users would share one limit. Tell uvicorn to trust the proxy so the client address comes from `X-Forwarded-For`: `uvicorn app:app --proxy-headers --forwarded-allow-ips=<proxy IP or range>`. The app itself never reads forwarding headers, since any client can send them.
- **Counts are kept in memory per process.** With several uvicorn workers or instances, each counts separately, so the effective limit is multiplied by their number, and counts reset on restart. For that setup, rate limit at the proxy or move the counts to a shared store such as Redis.
- **There is no authentication.** The limit slows abuse from one address; it does not stop many addresses. Set a spending cap with the LLM provider as well.

## Data Sources

All ingestion goes through `nepse_analyst.ingestion.Loader`. Sources only return normalized records (`ingestion/records.py`); the loader owns every database and vector-store write.

| Data | Interface | Default source |
| --- | --- | --- |
| Companies | `CompanySource` | `MerolaganiCompanySource` (live `merolagani.com/CompanyList.aspx`; `KaggleCsvCompanySource` reads the bundled static snapshot for offline builds) |
| Prices, indices | `PriceSource` | `FallbackPriceSource([NepseApiSource(), GitHubOpenDataSource()])` |
| Fundamentals, dividends | `FundamentalsSource` | `MerolaganiSource` (HTML cached in `data/raw/news_cache/`) |
| IPOs | `IPOSource` | `SharesansarIPOSource` |
| News | `NewsSource` (list) | `SharesansarNewsSource`, `NepseAlphaNewsSource` |

The companies step upserts the live list. A company that drops off it (delisted, merged, or a matured bond or fund) is kept with `is_active = 0`, because prices, fundamentals and news still refer to it, and returns to 1 if it is listed again. The step refuses a list shorter than 80% of the currently active companies, so a partial page cannot mark the rest delisted.

The news step checks the scraped corpus before replacing the vector store. It fails, leaving the existing store in place, when there are fewer than `NEWS_MIN_ARTICLES` (default 50) articles after dedupe, when the newest article is older than `NEWS_MAX_NEWEST_AGE_DAYS` (default 14), or when more than half the articles have no parseable date. A source that returns nothing (NepseAlpha is often unreachable) prints a warning. Set `NEWS_ALLOW_THIN_CORPUS=1` to index anyway; the problems are still printed and returned in the step result.

`NepseApiSource` reads the unofficial NEPSE API through the community nepseapi.surajrimal.dev mirror. It is not an official feed. To replace it, implement `PriceSource` (`available`, `fetch_price_history`, `fetch_index_history`) and pass it in:

```python
from nepse_analyst.ingestion import Loader, default_sources

sources = default_sources()
sources.prices = MyOfficialFeed()
Loader(sources).run(["prices", "indices"])
```

## API Endpoints

- `GET /`: Chat web interface.
- `GET /api/health`: Service health probe.
- `GET /api/example-questions`: Example questions, as `groups` (`{"group", "questions"}`) and as a flat `examples` list.
- `POST /api/chat`: Query endpoint.
- `POST /api/chat/stream`: The same answer, preceded by progress stages. The body is newline-delimited JSON: `{"type": "stage", "stage": "querying_database", "label": "Querying the database"}` lines as the question moves on (`understanding`, `querying_database`, `searching_news`, `writing_answer`), then one `{"type": "answer", "data": {...}}` line holding the `/api/chat` response. The web interface uses this endpoint.

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

Run the linter and the regression tests (the same two checks CI runs, `.github/workflows/ci.yml`):

```
uv run ruff check .
uv run python -m unittest discover -s tests -p "test_*.py"
```

`uv sync` installs the `dev` dependency group (ruff) by default. The ruff rules are set in `pyproject.toml` under `[tool.ruff]`; `uv run ruff check . --fix` applies the automatic fixes (import sorting). The tests need no built database, vector store or model download, so they run in a fresh checkout.

Tip: keep using `uv run` for scripts and tests instead of relying on shell activation.

`fastapi.testclient.TestClient` works. It used to fail (`Client.__init__() got an unexpected keyword argument 'follow_redirects'`) because the `nepse-api` package pinned httpx below 0.19; that package was removed, which also let chromadb move from 0.5.0 to 1.5.9.

## Known Data Constraints

From the 2026-11-17 database (reference results are snapshotted in `evaluation/benchmark_questions.json`; refresh with `uv run python scripts/evaluate_benchmark.py --refresh-snapshot`):
- `companies.market_cap` is computed during the build as `listed_shares` × the symbol's latest close (recomputed by both the `companies` and `prices` steps). 249 of the 585 active companies have one; the rest lack a share count on the company list or have no price history (promoter shares are not priced), and inactive companies get NULL. Share counts come from Merolagani's company list, which can lag a company's own page (NABIL: 270.6M on the list, 284.1M on its page), so recent bonus and right issues may be missing. Until 2026-11-19 the CSV's thousands separators were parsed as missing, so `listed_shares` was 0 and `market_cap` NULL for every company, and Q3 had an empty reference.
- Q6 ("top 5 most oversubscribed IPOs") is deferred and not scored (`deferred_sql_benchmark` in the benchmark file). `ipos.total_applicants` and `ipos.oversubscription_rate` are NULL for every row because no source exposes IPO applicant counts. Sharesansar's existing-issues feed, NepaliPaisa and Merolagani list units, dates and issue manager only, and the CDSC and Sharesansar result pages check one BOID at a time. The columns stay in the schema (the prompt marks them "no data"), and Q6 returns to scoring once a source fills them.
- Q10 has an empty reference: `fundamentals.roe` is NULL for every row.
- Q5 ("consistent EPS growth for 3 consecutive fiscal years") is deferred and not scored. Merolagani's company page shows only the latest fiscal year's EPS, P/E and book value; its Quarterly tab and NepaliPaisa's Financial Reports tab list report announcements and PDFs, not figures. So `fundamentals` holds one fiscal year per company. The fundamentals step now upserts instead of clearing a company's rows, so each build adds the current year and history accumulates; Q5 returns to scoring once companies have three consecutive years. Its reference SQL checks EPS rising across three consecutive fiscal years (previously it listed every EPS row) and is still covered by `tests/test_benchmark_eval.py`. Q2's reference SQL had the same problem (raw dividend rows, streak check left to code that did not exist) and now returns the 23 hydropower companies with a 3+ year cash-dividend run.

An empty reference is matched by an empty result, so these questions can be "correct" without the model answering anything. The report counts them separately (`strict_exact_empty_reference`).

These are expected data coverage limitations and should be documented in evaluation results.

## License

MIT License. See LICENSE.

Data sources are third-party and used for educational, non-commercial portfolio purposes only.
