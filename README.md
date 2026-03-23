# NEPSE Analyst

> A natural language research assistant for Nepal's retail investors.

[![Status](https://img.shields.io/badge/status-in%20development-yellow)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## Disclaimer

**NEPSE Analyst is a research information tool only. Nothing in this project constitutes financial advice. Past performance does not guarantee future results. Always consult a SEBON-registered broker or financial advisor before making investment decisions.**

---

## Overview

NEPSE Analyst lets you ask natural language questions about Nepal's stock market and receive accurate, data-grounded answers without needing to navigate multiple websites or write a single line of code.

**Example questions you can ask:**

- *"Which commercial bank has the highest EPS in the latest fiscal year?"*
- *"List all hydropower companies that have paid cash dividends for 3 or more consecutive years."*
- *"What is the 52-week high and low for NABIL Bank?"*
- *"Which sector had the highest average turnover over the last 30 trading days?"*
- *"कुन कम्पनीले हालसालै बोनस सेयर घोषणा गर्यो?"*

**What it does not do:** NEPSE Analyst does not predict stock prices, generate buy/sell signals, or provide investment recommendations. This is by design.

---

## Demo

> **Live demo coming soon** — will be hosted on Hugging Face Spaces upon project completion.

---

## Architecture

NEPSE Analyst uses a **hybrid retrieval architecture** with two data pathways controlled by an intelligent query router:

```
User Query (English or Nepali)
        │
        ▼
┌─────────────────────┐
│   Query Router      │  ← classifies intent
└──────────┬──────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
┌─────────┐  ┌─────────────┐
│Text-to  │  │ Multilingual│
│  SQL    │  │    RAG      │
│         │  │             │
│ SQLite  │  │  ChromaDB   │
│  DB     │  │  + News     │
└────┬────┘  └──────┬──────┘
     └──────┬───────┘
            ▼
   ┌─────────────────┐
   │ Answer          │
   │ Synthesiser     │  ← natural language response
   └─────────────────┘
```

| Pathway | Used For |
|---|---|
| **Text-to-SQL** | Price history, EPS, P/E ratios, dividends, IPO data, sector comparisons |
| **Multilingual RAG** | Recent news, company announcements, AGM notices, regulatory updates |
| **Direct LLM** | Stable general facts about NEPSE structure and market mechanics |
| **Out of scope** | Price predictions and investment advice — declined with explanation |

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM (cloud) | Groq API — `llama-3.1-8b-instant` |
| LLM (local fallback) | Ollama — `llama3.2:3b` |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` |
| Vector store | ChromaDB (local persistence) |
| Structured store | SQLite |
| Data ingestion | `nepse-api`, `requests`, `BeautifulSoup4` |
| UI | Streamlit |
| Deployment | Hugging Face Spaces |

---

## Data Sources

| Source | Type | Data |
|---|---|---|
| nepse-api (PyPI) | Structured | Real-time prices, OHLCV history, indices |
| Merolagani | Semi-structured | EPS, P/E, book value, dividend history |
| Sharesansar | Unstructured | News, announcements, AGM notices |
| NepseAlpha | Unstructured | Market analysis articles |
| Kaggle — NEPSE companies | Structured | 520 listed companies, sectors |
| OpenNepal | Structured | Historical index data |

> All data is used for educational and non-commercial portfolio purposes only. An official NEPSE data licence would be required for any commercial deployment.

---

## Project Structure

```
nepse-analyst/
├── notebooks/                  # Google Colab — heavy data processing
│   ├── 01_ingest_companies.ipynb
│   ├── 02_ingest_price_history.ipynb
│   ├── 03_ingest_fundamentals.ipynb
│   ├── 04_ingest_ipos.ipynb
│   ├── 05_ingest_news.ipynb
│   └── 06_evaluation.ipynb
│
├── nepse_analyst/              # Core Python package
│   ├── config.py               # All settings and paths
│   ├── database.py             # SQLite interface
│   ├── llm.py                  # Groq / Ollama switcher
│   ├── embeddings.py           # Multilingual embedding model
│   ├── retriever.py            # ChromaDB search
│   ├── sql_generator.py        # Text-to-SQL pipeline
│   ├── router.py               # Query classifier
│   ├── language_detector.py    # English / Nepali detection
│   ├── guardrails.py           # Anti-prediction guard + disclaimer
│   ├── pipeline.py             # End-to-end query function
│   └── prompts.py              # All LLM prompt templates
│
├── app/
│   ├── main.py                 # Streamlit entry point
│   ├── components.py           # UI components
│   └── example_questions.py   # Sidebar example questions
│
├── data/
│   ├── raw/
│   │   └── nepse_companies_kaggle.csv
│   ├── processed/              # nepse.db — gitignored, regenerable
│   └── vector_store/           # ChromaDB index — gitignored, regenerable
│
├── evaluation/
│   ├── benchmark_questions.json
│   └── results/
│
├── scripts/
│   ├── build_db.py
│   ├── refresh_prices.py
│   └── refresh_news.py
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## Setup

> **Full setup instructions will be added upon project completion.**  
> The steps below outline the intended setup process.

### Prerequisites

- Python 3.10+
- A free [Groq API key](https://console.groq.com)
- Google Colab access (free) for data processing

### 1. Clone the repository

```bash
git clone https://github.com/meutsabdahal/nepse-analyst.git
cd nepse-analyst
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

### 4. Build the database

Run the Colab notebooks in order (`01` through `05`) to populate the SQLite database and ChromaDB vector store. Download the outputs and place them in `data/processed/` and `data/vector_store/` respectively.

### 5. Run the app

```bash
streamlit run app/main.py
```

---

## Evaluation

NEPSE Analyst is evaluated against a defined benchmark of 12 structured SQL queries and 5 news retrieval queries, with ground truth answers computed from raw data before the system was built.

> **Benchmark results will be published here upon project completion.**

| Category | Questions | Target Accuracy |
|---|---|---|
| Structured SQL queries | 12 | ≥ 75% |
| News retrieval (RAG) | 5 | ≥ 80% relevance |
| Out-of-scope rejection | 4 | ≥ 90% |

Evaluation notebook: [`notebooks/06_evaluation.ipynb`](notebooks/06_evaluation.ipynb)

---

## Limitations

> **This section will be updated with honest findings after the benchmark evaluation is complete.**

Known limitations at project start:

- Price history and news data are refreshed periodically, not in real time. All responses include a data last-updated timestamp.
- Fundamental data (EPS, P/E, book value) coverage varies by company. The system communicates clearly when data is unavailable for a specific company or fiscal year.
- Nepali language support covers query understanding and response synthesis. Full Nepali UI is not available in v1.
- Statistical outputs may differ slightly from official NEPSE or Merolagani figures due to data source coverage differences.

---

## Roadmap

### v1 — Current
- [x] Project setup and PRD
- [ ] SQLite database with all six tables
- [ ] Text-to-SQL pipeline with retry logic
- [ ] Multilingual news corpus and ChromaDB index
- [ ] Query router with anti-prediction guardrail
- [ ] Streamlit web app
- [ ] Hugging Face Spaces deployment
- [ ] Benchmark evaluation and results

### v2 — Planned
- [ ] Price charts (6-month and 1-year)
- [ ] Portfolio screener with custom filters
- [ ] Real-time price refresh during market hours
- [ ] Government bonds and debentures data
- [ ] Full Nepali UI localisation

---

## Contributing

This is a solo portfolio project currently under active development. Contributions, issues, and suggestions are welcome once v1 is released.

---

## Author

**Utsab Dahal**  
[GitHub](https://github.com/meutsabdahal) · [X / Twitter](https://x.com/meutsabdahal)

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Data used in this project is sourced from third-party providers for educational and non-commercial purposes only. Refer to each data source's terms of use before any commercial application.

---

*Started: March 2026 · Target completion: September 2026*
