# NEPSE Analyst

A natural language research assistant for Nepal's retail investors.

## Financial Disclaimer

NEPSE Analyst is a research information tool only. Nothing in this project constitutes financial advice. Past performance does not guarantee future results. Always consult a SEBON-registered broker or financial advisor before making investment decisions.

## Current Status

Implemented:
- Hybrid query flow: SQL, RAG, HYBRID, DIRECT, and OOS guardrail routing.
- Multilingual handling for English and Nepali inputs.
- Guardrails for prediction and advice queries with mandatory disclaimer injection.
- Streamlit UI with:
  - natural language input,
  - example question sidebar,
  - source transparency panel,
  - data freshness indicator,
  - company quick-facts card.
- Benchmark runner CLI for SQL and OOS reporting.
- Hugging Face Spaces-ready app entrypoint and uv-based dependency workflow.

## Architecture

User Query (EN/NE)
-> Router
-> SQL / RAG / HYBRID / DIRECT / OOS
-> Answer synthesis
-> Streamlit response card + transparency panel

Core package lives in nepse_analyst/ and UI lives in app/.

## Repository Layout

- app/main.py: Streamlit UI entrypoint.
- app/components.py: Answer card, source panel, quick-facts rendering.
- app/example_questions.py: Sidebar prompt list.
- app.py: Root HF Spaces-compatible entrypoint.
- nepse_analyst/pipeline.py: End-to-end query orchestration.
- nepse_analyst/router.py: Query routing and entity extraction.
- nepse_analyst/sql_generator.py: Text-to-SQL generation and execution.
- nepse_analyst/retriever.py: ChromaDB retrieval.
- nepse_analyst/guardrails.py: Advice/prediction rejection logic.
- scripts/evaluate_benchmark.py: Benchmark runner.
- scripts/build_db.py: Database schema build command.
- scripts/refresh_news.py: News refresh command wrapper.
- evaluation/benchmark_questions.json: SQL benchmark definitions.
- evaluation/results/: Saved evaluation reports.

## Quick Start

Prerequisites:
- Python 3.12+
- Local data artifacts prepared (SQLite DB and vector store)
- Optional: Groq API key for cloud LLM mode

1) Install dependencies (uv)

- uv sync

2) Configure environment

Copy .env.example to .env and set values:
- LLM_PROVIDER=groq or ollama
- GROQ_API_KEY=... (if using groq)
- OLLAMA_MODEL=llama3.2:3b (if using ollama)

3) Ensure data artifacts exist

- SQLite DB: data/processed/nepse.db
- ChromaDB directory: data/vector_store/

If DB schema is missing:
- python scripts/build_db.py

For full data ingestion/index refresh use notebooks:
- notebooks/ingest_companies.ipynb
- notebooks/ingest_price_history.ipynb
- notebooks/ingest_fundamentals.ipynb
- notebooks/ingest_ipos.ipynb
- notebooks/ingest_news.ipynb

4) Run the app

- streamlit run app.py

## Evaluation

Run benchmark in ground-truth mode (validates benchmark SQL against DB):
- python scripts/evaluate_benchmark.py --mode ground-truth

Run benchmark in pipeline mode (requires configured LLM):
- python scripts/evaluate_benchmark.py --mode pipeline

Reports are written to evaluation/results/ as JSON.

Metrics currently reported by runner:
- SQL accuracy (exact/partial scoring)
- OOS rejection accuracy on 10 test queries

Latest local report:
- evaluation/results/report_ground-truth_20260328_162650.json

Latest measured values on this repository snapshot:
- SQL accuracy (ground-truth mode): 100.00%
- OOS rejection accuracy: 90.00%

## Tests

Run regression tests:
- python -m unittest discover -s tests -p "test_*.py"

## Streamlit Features

- Answer card with route and status.
- Data freshness line for each response.
- Expandable transparency panel showing SQL, SQL row preview, and retrieved passages.
- Quick-facts panel for detected company symbol.
- Clickable example prompts from sidebar.

## Hugging Face Spaces Deployment

This repository includes:
- app.py (root entrypoint)
- pyproject.toml
- uv.lock
- runtime.txt

Suggested Space settings:
- SDK: Streamlit
- Python: 3.12
- Hardware: CPU basic (free tier is acceptable)

Deployment steps:
1. Create a new Streamlit Space on Hugging Face.
2. Push this repository to the Space.
3. In build/startup command, install from lockfile: uv sync --frozen
4. Add secrets/environment variables in Space settings:
   - GROQ_API_KEY (if using Groq)
   - LLM_PROVIDER
5. Ensure data artifacts are present in the Space storage (or downloaded on startup).
6. Launch and verify app loads, then run SQL/RAG/OOS sample queries.

## Known Data Constraints

From current benchmark dataset snapshot:
- Q3 is data_unavailable due to missing market_cap values.
- Q6 is data_unavailable due to missing IPO oversubscription_rate values.
- Q10 is data_unavailable due to missing microfinance fundamentals coverage.

These are expected data coverage limitations and should be documented in evaluation results.

## License

MIT License. See LICENSE.

Data sources are third-party and used for educational, non-commercial portfolio purposes only.
