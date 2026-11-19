from dataclasses import dataclass

from nepse_analyst.schema_context import get_schema_context


# The schema section is generated from the database: see schema_context.py.


@dataclass(frozen=True)
class SQLExample:
    title: str
    question: str
    sql: str


# Worked examples for the SQL prompt. These must not reuse questions (or
# ground-truth SQL) from evaluation/benchmark_questions.json, otherwise the
# benchmark measures recall of the prompt instead of SQL generation.
# tests/test_prompt_leakage.py enforces this.
SQL_EXAMPLES: tuple[SQLExample, ...] = (
    SQLExample(
        title="Fundamental ranking with sector filter (latest fiscal year)",
        question="Which five hydropower companies have the lowest positive P/E ratio in the latest fiscal year?",
        sql="SELECT c.symbol, c.name, f.pe_ratio, f.fiscal_year FROM fundamentals f JOIN companies c ON f.symbol = c.symbol WHERE c.sector = 'Hydropower' AND f.fiscal_year = (SELECT MAX(fiscal_year) FROM fundamentals) AND f.pe_ratio > 0 ORDER BY f.pe_ratio ASC LIMIT 5",
    ),
    SQLExample(
        title="Dividend history for one company",
        question="What cash dividends and bonus shares has NICA declared in each fiscal year?",
        sql="SELECT fiscal_year, cash_dividend, bonus_shares FROM dividends WHERE symbol = 'NICA' ORDER BY fiscal_year DESC",
    ),
    SQLExample(
        title="Price window anchored to the symbol's latest trade date",
        question="What was the average closing price of UPPER over the last 90 days?",
        sql="WITH ref AS (SELECT MAX(trade_date) AS max_date FROM price_history WHERE symbol = 'UPPER') SELECT ROUND(AVG(close_price), 2) AS avg_close_90d FROM price_history, ref WHERE symbol = 'UPPER' AND trade_date > date(max_date, '-90 day')",
    ),
    SQLExample(
        title="Per-symbol aggregation over the last N trading days",
        question="Which five stocks had the highest total traded volume over the last 10 trading days?",
        sql="SELECT symbol, SUM(volume) AS total_volume FROM price_history WHERE trade_date IN (SELECT DISTINCT trade_date FROM price_history ORDER BY trade_date DESC LIMIT 10) GROUP BY symbol ORDER BY total_volume DESC LIMIT 5",
    ),
    SQLExample(
        title="IPO lookup by sector",
        question="List the hydropower IPOs that have listed, with their issue and listing prices.",
        sql="SELECT symbol, company_name, issue_price, listing_price, listing_date FROM ipos WHERE status = 'listed' AND sector = 'Hydropower' ORDER BY listing_date DESC",
    ),
    SQLExample(
        title="Latest index value",
        question="What was the NEPSE index close on the most recent trading day?",
        sql="SELECT trade_date, close_value, change_points, change_percent FROM indices WHERE index_name = 'NEPSE' ORDER BY trade_date DESC LIMIT 1",
    ),
)


FEW_SHOT_EXAMPLES = "\n" + "\n\n".join(
    f"EXAMPLE {i} — {ex.title}:\nQuestion: {ex.question}\nSQL: {ex.sql}"
    for i, ex in enumerate(SQL_EXAMPLES, 1)
) + "\n"


def build_sql_prompt(question: str) -> str:
    return f"""{get_schema_context()}

WORKED EXAMPLES:
{FEW_SHOT_EXAMPLES}

Now write the SQL query for this question. Return ONLY the SQL. No explanation, no markdown, no backticks.

Question: {question}
SQL:"""


def build_rag_synthesis_prompt(
    query: str, passages: list[dict], query_language: str = "en"
) -> str:
    # Format the retrieved passages for the prompt
    passage_text = ""
    for i, p in enumerate(passages, 1):
        passage_text += (
            f"[{i}] Source: {p['source'].upper()} | "
            f"Date: {p['published_at']} | "
            f"Title: {p['title']}\n"
            f"{p['content'][:600]}\n\n"
        )

    language_instruction = (
        "Respond in Nepali (Devanagari script)."
        if query_language == "ne"
        else "Respond in English."
    )

    return f"""You are a NEPSE (Nepal Stock Exchange) research assistant. 
Answer the user's question based ONLY on the news passages provided below.
Do not use any information not present in these passages.
If the passages do not contain enough information to answer the question, say so clearly.
{language_instruction}
Cite your sources by referring to passage numbers [1], [2], etc.
Do NOT make any investment recommendations or price predictions.

USER QUESTION: {query}

RETRIEVED NEWS PASSAGES:
{passage_text}

ANSWER (based only on the passages above):"""


def build_router_prompt(
    query: str, query_language: str, detected_entities: dict
) -> str:
    """
    Prompt for the LLM-based query router.
    Returns one of five route labels as a single word.
    detected_entities: dict with keys 'symbol', 'sector', 'metric', 'time_period'
    """
    entity_context = ""
    if detected_entities.get("symbol"):
        entity_context += f"Detected company symbol: {detected_entities['symbol']}\n"
    if detected_entities.get("sector"):
        entity_context += f"Detected sector: {detected_entities['sector']}\n"

    return f"""You are a query router for NEPSE Analyst, a Nepal Stock Exchange research tool.
Classify the user's question into exactly ONE of these five categories:

SQL     — Questions about structured data: prices, EPS, P/E ratios, dividends, book value,
          market cap, turnover, IPO data, index values, sector comparisons.
          Examples: "highest EPS bank", "52-week high for NABIL", "dividend history of NHPC"

RAG     — Questions about news, announcements, events, and qualitative information.
          Examples: "recent news about NABIL", "AGM announcements", "regulatory changes"

HYBRID  — Questions that need BOTH structured data AND news context to answer fully.
          Examples: "How has NABIL performed recently?", "Compare banking sector fundamentals and news"

DIRECT  — Questions answerable from general knowledge about NEPSE structure, how the market
          works, or definitions — no data retrieval needed.
          Examples: "What is NEPSE?", "How does the NEPSE trading session work?", "What is P/E ratio?"

OOS     — Out of scope: price predictions, market forecasts, investment advice, buy/sell recommendations.
          Examples: "Will NABIL go up?", "Should I buy HDCL?", "Best stock for quick returns"

Query language: {query_language}
{entity_context}
User question: {query}

Respond with ONLY one word — the category label: SQL, RAG, HYBRID, DIRECT, or OOS.
No explanation. No punctuation. Just the label."""


def build_sql_synthesis_prompt(
    query: str,
    sql: str,
    rows: list[dict],
    columns: list[str],
    query_language: str,
    truncated: bool = False,
) -> str:
    """
    Prompt for converting a raw SQL result into a natural language answer.
    This is separate from the SQL generation prompt — it runs after execution.
    """
    # Format the result rows compactly
    if not rows:
        result_text = "The query returned no results."
    elif len(rows) == 1:
        result_text = str(dict(rows[0]))
    else:
        if truncated:
            count = f"At least {len(rows)} rows (the result was cut off; do not state a total)"
        else:
            count = f"{len(rows)} rows"
        result_text = f"{count}:\n"
        for i, row in enumerate(rows[:10], 1):  # cap at 10 rows for prompt length
            result_text += f"  {i}. {dict(row)}\n"
        if len(rows) > 10:
            result_text += f"  ... and {len(rows) - 10} more rows."

    language_instruction = (
        "Respond in Nepali (Devanagari script)."
        if query_language == "ne"
        else "Respond in English."
    )

    return f"""You are a NEPSE research assistant. Convert this SQL query result into a clear,
natural language answer for a non-technical investor.
{language_instruction}
Do NOT show the raw SQL or technical database terms.
Do NOT make investment recommendations.
Be concise — answer the question directly, then add one sentence of context if helpful.
If the result is empty, say the data is not available and suggest the user check the data freshness.

User question: {query}

SQL used: {sql}

Query result: {result_text}

Natural language answer:"""


def build_direct_prompt(query: str, query_language: str) -> str:
    language_instruction = (
        "Respond in Nepali (Devanagari script)."
        if query_language == "ne"
        else "Respond in English."
    )
    return f"""You are a NEPSE (Nepal Stock Exchange) research assistant with expert knowledge
of how the Nepali stock market works. Answer the following factual question about NEPSE
using your knowledge. Be accurate and concise.
{language_instruction}
Do not make investment recommendations or price predictions.

Question: {query}

Answer:"""
