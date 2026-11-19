from nepse_analyst.language_detector import detect_language
from nepse_analyst.messages import message
import re

# English prediction/advice signals
_PREDICTION_KEYWORDS_EN = [
    "will go up",
    "will go down",
    "will rise",
    "will fall",
    "will increase",
    "will decrease",
    "will it go",
    "price tomorrow",
    "price next week",
    "price next month",
    "price prediction",
    "predict",
    "forecast",
    "target price",
    "best stock",
    "best shares",
    "quick returns",
    "fast returns",
    "what will the nepse",
    "where will nepse",
    "index by end of",
    "price by end",
    "future price",
    "going to be worth",
]

# Nepali prediction/advice signals (Devanagari)
_PREDICTION_KEYWORDS_NE = [
    "बढ्छ",
    "घट्छ",
    "नाफा हुन्छ",
    "मूल्य बढ्छ",
    "मूल्य घट्छ",
    "भोलि",
    "अर्को हप्ता",
    "अर्को महिना",
    "लक्ष्य मूल्य",
    "भविष्य मूल्य",
]


# Detection functions


def is_prediction_query(query: str) -> bool:
    """
    Returns True if the query is asking for a price prediction or market forecast.
    Checks both English keywords and Nepali keywords.
    """
    q_lower = query.lower()
    if any(kw in q_lower for kw in _PREDICTION_KEYWORDS_EN):
        return True
    # Handle variable token spans like "Will NABIL stock go up tomorrow?"
    if re.search(r"\bwill\b.*\bgo\s+(up|down)\b", q_lower):
        return True
    if any(kw in query for kw in _PREDICTION_KEYWORDS_NE):
        return True
    return False


def is_advice_query(query: str) -> bool:
    """
    Returns True if the query is asking for personalised investment advice
    (buy/sell recommendations, portfolio suggestions).
    """
    q_lower = query.lower()
    advice_signals = [
        "should i",
        "should we",
        "should i buy",
        "should i sell",
        "should i hold",
        "buy or sell",
        "good time to buy",
        "good time to sell",
        "when to buy",
        "when to sell",
        "recommend",
        "advice",
        "advise",
        "what should",
        "tell me to buy",
        "tell me to sell",
        "best stock to buy",
        "best investment",
        "worth buying",
        "worth investing",
        "good investment",
    ]
    if any(s in q_lower for s in advice_signals):
        return True
    nepali_advice = ["किन्नु पर्छ", "बेच्नु पर्छ", "सल्लाह", "सुझाव"]
    if any(s in query for s in nepali_advice):
        return True
    return False


def get_guardrail_type(query: str) -> str | None:
    """
    Returns 'prediction', 'advice', or None if the query passes all guardrails.
    Call this before routing — if it returns non-None, skip retrieval entirely.
    """
    if is_advice_query(query):
        return "advice"
    if is_prediction_query(query):
        return "prediction"
    return None


# Response builders


def build_decline_response(query: str, guardrail_type: str) -> dict:
    """
    Build a complete decline response for out-of-scope queries.
    Returns the same dict structure as pipeline.run() so the UI handles it uniformly.
    """
    lang = detect_language(query)

    key = {"prediction": "decline_prediction", "advice": "decline_advice"}.get(
        guardrail_type, "decline_out_of_scope"
    )
    answer = message(key, lang)

    return {
        "success": True,
        "answer": answer,
        "route": "OOS",
        "guardrail_type": guardrail_type,
        "sql": None,
        "passages": [],
        "query_language": lang,
        "data_freshness": None,
        "error": None,
    }
