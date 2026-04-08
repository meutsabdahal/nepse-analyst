from nepse_analyst.language_detector import detect_language
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

_DISCLAIMER_EN = (
    "\n\n---\n"
    "⚠️ *This information is for research purposes only and does not constitute "
    "financial advice. Past performance does not guarantee future results. "
    "Please consult a SEBON-registered broker or financial advisor before "
    "making any investment decisions.*"
)

_DISCLAIMER_NE = (
    "\n\n---\n"
    "⚠️ *यो जानकारी अनुसन्धान उद्देश्यका लागि मात्र हो र वित्तीय सल्लाह होइन। "
    "कृपया कुनै पनि लगानी निर्णय गर्नु अघि SEBON-दर्ता दलाल वा वित्तीय सल्लाहकारसँग "
    "परामर्श गर्नुहोस्।*"
)


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

    if guardrail_type == "prediction":
        if lang == "ne":
            message = (
                "माफ गर्नुस्, NEPSE Analyst ले मूल्य भविष्यवाणी गर्दैन। "
                "सेयरको भविष्यको मूल्य विश्वसनीय रूपमा अनुमान गर्न सम्भव छैन, "
                "र यस्तो दाबी गर्नु लगानीकर्ताहरूलाई हानिकारक हुन सक्छ।\n\n"
                "यसको सट्टा म यी प्रश्नहरूमा मद्दत गर्न सक्छु:\n"
                "• कम्पनीको EPS, P/E अनुपात, र बुक भ्यालु के हो?\n"
                "• कुन हाइड्रोपावर कम्पनीले लगातार लाभांश दिएको छ?\n"
                "• हालैको समाचार र घोषणाहरू के छन्?"
            )
        else:
            message = (
                "NEPSE Analyst does not predict stock prices or market movements. "
                "Price prediction cannot be done reliably, and claiming otherwise "
                "would be misleading and potentially harmful to investors.\n\n"
                "Here are things I *can* help you with instead:\n"
                "• What is a company's EPS, P/E ratio, and book value?\n"
                "• Which hydropower companies have paid consistent dividends?\n"
                "• What are the latest news and announcements for a company?"
            )

    elif guardrail_type == "advice":
        if lang == "ne":
            message = (
                "माफ गर्नुस्, NEPSE Analyst ले व्यक्तिगत लगानी सल्लाह दिँदैन। "
                "खरिद वा बिक्रीको सिफारिश गर्नु इजाजतपत्र प्राप्त वित्तीय सल्लाहकारको "
                "काम हो।\n\n"
                "कुनै पनि लगानी निर्णय गर्नु अघि SEBON-दर्ता दलाल वा "
                "वित्तीय सल्लाहकारसँग परामर्श गर्नुहोस्।\n\n"
                "म आधारभूत अनुसन्धानमा मद्दत गर्न सक्छु — कम्पनीको वित्तीय डेटा, "
                "क्षेत्र तुलना, र हालैका समाचारहरू।"
            )
        else:
            message = (
                "NEPSE Analyst does not provide personalised investment advice. "
                "Buy and sell recommendations are the role of a licensed financial advisor, "
                "not an AI research tool.\n\n"
                "Please consult a SEBON-registered broker or financial advisor "
                "before making any investment decisions.\n\n"
                "I can help with fundamental research — company financial data, "
                "sector comparisons, and recent news."
            )
    else:
        if lang == "ne":
            message = (
                "यो प्रश्न NEPSE Analyst को सुरक्षित कार्यक्षेत्र बाहिर पर्छ, "
                "त्यसैले म यसलाई सीधा रूपमा उत्तर दिन सक्दिनँ।\n\n"
                "म तलका अनुसन्धान कार्यहरूमा मद्दत गर्न सक्छु:\n"
                "• कम्पनीको EPS, P/E, र बुक भ्यालु\n"
                "• sector तुलना र ऐतिहासिक डेटा\n"
                "• हालको समाचार र घोषणाहरू"
            )
        else:
            message = (
                "This query is outside NEPSE Analyst's safe operating scope, "
                "so I cannot answer it directly.\n\n"
                "I can help with research tasks such as:\n"
                "• Company EPS, P/E ratio, and book value\n"
                "• Sector comparisons and historical data\n"
                "• Recent news and announcements"
            )

    disclaimer = _DISCLAIMER_NE if lang == "ne" else _DISCLAIMER_EN

    return {
        "success": True,
        "answer": message + disclaimer,
        "route": "OOS",
        "guardrail_type": guardrail_type,
        "sql": None,
        "passages": [],
        "query_language": lang,
        "data_freshness": None,
        "error": None,
    }


def append_disclaimer(text: str, language: str = "en") -> str:
    """Append the financial disclaimer to any answer string."""
    disclaimer = _DISCLAIMER_NE if language == "ne" else _DISCLAIMER_EN
    return text + disclaimer
