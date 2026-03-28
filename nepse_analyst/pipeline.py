from datetime import datetime
from nepse_analyst.router import classify
from nepse_analyst.guardrails import build_decline_response, append_disclaimer
from nepse_analyst.sql_generator import generate_and_execute
from nepse_analyst.retriever import search, get_corpus_stats
from nepse_analyst.database import get_connection
from nepse_analyst import llm
from nepse_analyst.prompts import (
    build_sql_synthesis_prompt,
    build_rag_synthesis_prompt,
    build_direct_prompt,
)


# Data freshness helpers


def _get_db_freshness() -> str:
    """Return the most recent trade_date in price_history as a readable string."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM price_history")
        result = cursor.fetchone()
        conn.close()
        date_str = result[0] if result and result[0] else "unknown"
        return f"Price data last updated: {date_str}"
    except Exception:
        return "Price data freshness unknown"


def _get_news_freshness() -> str:
    """Return the most recent article date from the ChromaDB corpus."""
    try:
        stats = get_corpus_stats()
        return f"News data last updated: {stats['latest_date']} ({stats['total_documents']} articles)"
    except Exception:
        return "News data freshness unknown"


# Route handlers


def _handle_sql(query: str, language: str, entities: dict) -> dict:
    """Execute the Text-to-SQL pathway."""
    result = generate_and_execute(query)

    if not result["success"]:
        answer = (
            "I was unable to retrieve structured data for this question. "
            f"The database returned an error after {result['attempts']} attempts: "
            f"{result['error']}\n\n"
            "This may mean the data is not available in the current dataset. "
            "Please check the data freshness indicator."
        )
        if language == "ne":
            answer = (
                "यो प्रश्नको लागि संरचित डेटा प्राप्त गर्न सकिएन। "
                "डेटाबेसले त्रुटि दियो। डेटा उपलब्ध नहुन सक्छ।"
            )
        return {
            "success": False,
            "answer": append_disclaimer(answer, language),
            "route": "SQL",
            "sql": result.get("sql"),
            "passages": [],
            "query_language": language,
            "data_freshness": _get_db_freshness(),
            "error": result["error"],
        }

    # Synthesise natural language answer from SQL result
    synthesis_prompt = build_sql_synthesis_prompt(
        query=query,
        sql=result["sql"],
        rows=result["rows"],
        columns=result["columns"],
        query_language=language,
    )
    answer = llm.call(synthesis_prompt, temperature=0.1)

    return {
        "success": True,
        "answer": append_disclaimer(answer, language),
        "route": "SQL",
        "sql": result["sql"],
        "sql_rows": result["rows"],
        "passages": [],
        "query_language": language,
        "data_freshness": _get_db_freshness(),
        "error": None,
    }


def _handle_rag(query: str, language: str, entities: dict) -> dict:
    """Execute the multilingual RAG pathway."""
    # Use entity metadata for filtered retrieval when a symbol is detected
    try:
        passages = search(
            query=query,
            top_k=5,
            symbol_filter=entities.get("symbol") or None,
            sector_filter=entities.get("sector") or None,
        )
    except Exception as e:
        answer = (
            "News retrieval is currently unavailable because the embedding/vector stack could not be loaded. "
            "Please verify model availability and retry."
        )
        if language == "ne":
            answer = (
                "समाचार खोज सुविधा हाल उपलब्ध छैन। " "एम्बेडिङ मोडेल वा भेक्टर स्टोर लोड हुन सकेन।"
            )
        return {
            "success": False,
            "answer": append_disclaimer(answer, language),
            "route": "RAG",
            "sql": None,
            "passages": [],
            "query_language": language,
            "data_freshness": "News data freshness unknown",
            "error": str(e),
        }

    if not passages:
        answer = (
            "No relevant news or announcements were found for this query in the current corpus. "
            "The news corpus is updated weekly — try again after the next refresh."
        )
        if language == "ne":
            answer = "यस प्रश्नसँग सम्बन्धित कुनै समाचार भेटिएन।"
        return {
            "success": False,
            "answer": append_disclaimer(answer, language),
            "route": "RAG",
            "sql": None,
            "passages": [],
            "query_language": language,
            "data_freshness": _get_news_freshness(),
            "error": "No passages retrieved",
        }

    synthesis_prompt = build_rag_synthesis_prompt(query, passages, language)
    answer = llm.call(synthesis_prompt, temperature=0.1)

    return {
        "success": True,
        "answer": append_disclaimer(answer, language),
        "route": "RAG",
        "sql": None,
        "passages": passages,
        "query_language": language,
        "data_freshness": _get_news_freshness(),
        "error": None,
    }


def _handle_hybrid(query: str, language: str, entities: dict) -> dict:
    """
    Execute both SQL and RAG pathways and combine the results.
    Used when a question needs both structured data and news context.
    """
    sql_result = _handle_sql(query, language, entities)
    rag_result = _handle_rag(query, language, entities)

    # Combine both answers into a single response
    combined_parts = []
    if sql_result["success"] and sql_result.get("answer"):
        # Strip disclaimer from the SQL answer before combining (we'll add once at the end)
        sql_answer_clean = sql_result["answer"].split("\n\n---\n")[0]
        combined_parts.append(f"**Structured Data:**\n{sql_answer_clean}")
    if rag_result["success"] and rag_result.get("answer"):
        rag_answer_clean = rag_result["answer"].split("\n\n---\n")[0]
        combined_parts.append(f"**Recent News:**\n{rag_answer_clean}")

    if not combined_parts:
        combined = "I was unable to retrieve data for this question from either the database or news corpus."
    else:
        combined = "\n\n".join(combined_parts)

    return {
        "success": sql_result["success"] or rag_result["success"],
        "answer": append_disclaimer(combined, language),
        "route": "HYBRID",
        "sql": sql_result.get("sql"),
        "sql_rows": sql_result.get("sql_rows", []),
        "passages": rag_result.get("passages", []),
        "query_language": language,
        "data_freshness": f"{_get_db_freshness()} | {_get_news_freshness()}",
        "error": None,
    }


def _handle_direct(query: str, language: str) -> dict:
    """Handle general knowledge questions about NEPSE that need no data retrieval."""
    prompt = build_direct_prompt(query, language)
    answer = llm.call(
        prompt, temperature=0.2
    )  # slight temperature for more natural prose
    return {
        "success": True,
        "answer": append_disclaimer(answer, language),
        "route": "DIRECT",
        "sql": None,
        "passages": [],
        "query_language": language,
        "data_freshness": None,
        "error": None,
    }


# Main entry point


def run(query: str) -> dict:
    """
    Process a natural language query end-to-end.
    This is the single function the chat API calls.

    Returns:
    {
        "success":        bool,
        "answer":         str,      # final answer with disclaimer appended
        "route":          str,      # 'SQL' | 'RAG' | 'HYBRID' | 'DIRECT' | 'OOS'
        "guardrail_type": str|None, # 'prediction' | 'advice' | None
        "sql":            str|None, # generated SQL (for transparency panel)
        "sql_rows":       list,     # raw rows (for transparency panel)
        "passages":       list,     # retrieved news passages (for transparency panel)
        "query_language": str,      # 'en' | 'ne' | 'mixed'
        "data_freshness": str|None, # human-readable freshness string
        "error":          str|None
    }
    """
    query = query.strip()
    if not query:
        return {
            "success": False,
            "answer": "Please enter a question.",
            "route": None,
            "guardrail_type": None,
            "sql": None,
            "sql_rows": [],
            "passages": [],
            "query_language": "en",
            "data_freshness": None,
            "error": "Empty query",
        }

    # Step 1 — Classify and route
    routing = classify(query)
    route = routing["route"]
    language = routing["language"]
    entities = routing["entities"]
    guardrail = routing.get("guardrail")

    # Step 2 — Guardrail intercept
    if route == "OOS" or guardrail:
        decline = build_decline_response(query, guardrail or "prediction")
        decline["guardrail_type"] = guardrail
        return decline

    # Step 3 — Dispatch to the correct pathway
    try:
        if route == "SQL":
            result = _handle_sql(query, language, entities)
        elif route == "RAG":
            result = _handle_rag(query, language, entities)
        elif route == "HYBRID":
            result = _handle_hybrid(query, language, entities)
        elif route == "DIRECT":
            result = _handle_direct(query, language)
        else:
            result = _handle_sql(query, language, entities)  # safe fallback
    except Exception as e:
        result = {
            "success": False,
            "answer": append_disclaimer(
                f"An unexpected error occurred while processing your question: {str(e)}",
                language,
            ),
            "route": route,
            "sql": None,
            "sql_rows": [],
            "passages": [],
            "query_language": language,
            "data_freshness": None,
            "error": str(e),
        }

    result["guardrail_type"] = None
    return result
