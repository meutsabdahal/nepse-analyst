"""User-facing answer text, in every supported language, in one table.

Each entry holds the same message in English ("en") and Nepali ("ne") with the
same named ``str.format`` placeholders; tests/test_messages.py checks that
every entry has both languages and that their placeholders match, so a change
to one language cannot silently miss the other.

``message(key, language, **values)`` returns the Nepali text for "ne" and the
English text for anything else ("en", "mixed").
"""

from __future__ import annotations

LANGUAGES = ("en", "ne")

MESSAGES: dict[str, dict[str, str]] = {
    # -- guardrail declines --------------------------------------------------
    "decline_prediction": {
        "en": (
            "NEPSE Analyst does not predict stock prices or market movements. "
            "Price prediction cannot be done reliably, and claiming otherwise "
            "would be misleading and potentially harmful to investors.\n\n"
            "Here are things I *can* help you with instead:\n"
            "• What is a company's EPS, P/E ratio, and book value?\n"
            "• Which hydropower companies have paid consistent dividends?\n"
            "• What are the latest news and announcements for a company?"
        ),
        "ne": (
            "माफ गर्नुस्, NEPSE Analyst ले मूल्य भविष्यवाणी गर्दैन। "
            "सेयरको भविष्यको मूल्य विश्वसनीय रूपमा अनुमान गर्न सम्भव छैन, "
            "र यस्तो दाबी गर्नु लगानीकर्ताहरूलाई हानिकारक हुन सक्छ।\n\n"
            "यसको सट्टा म यी प्रश्नहरूमा मद्दत गर्न सक्छु:\n"
            "• कम्पनीको EPS, P/E अनुपात, र बुक भ्यालु के हो?\n"
            "• कुन हाइड्रोपावर कम्पनीले लगातार लाभांश दिएको छ?\n"
            "• हालैको समाचार र घोषणाहरू के छन्?"
        ),
    },
    "decline_advice": {
        "en": (
            "NEPSE Analyst does not provide personalised investment advice. "
            "Buy and sell recommendations are the role of a licensed financial advisor, "
            "not an AI research tool.\n\n"
            "Please consult a SEBON-registered broker or financial advisor "
            "before making any investment decisions.\n\n"
            "I can help with fundamental research — company financial data, "
            "sector comparisons, and recent news."
        ),
        "ne": (
            "माफ गर्नुस्, NEPSE Analyst ले व्यक्तिगत लगानी सल्लाह दिँदैन। "
            "खरिद वा बिक्रीको सिफारिश गर्नु इजाजतपत्र प्राप्त वित्तीय सल्लाहकारको "
            "काम हो।\n\n"
            "कुनै पनि लगानी निर्णय गर्नु अघि SEBON-दर्ता दलाल वा "
            "वित्तीय सल्लाहकारसँग परामर्श गर्नुहोस्।\n\n"
            "म आधारभूत अनुसन्धानमा मद्दत गर्न सक्छु — कम्पनीको वित्तीय डेटा, "
            "क्षेत्र तुलना, र हालैका समाचारहरू।"
        ),
    },
    "decline_out_of_scope": {
        "en": (
            "This query is outside NEPSE Analyst's safe operating scope, "
            "so I cannot answer it directly.\n\n"
            "I can help with research tasks such as:\n"
            "• Company EPS, P/E ratio, and book value\n"
            "• Sector comparisons and historical data\n"
            "• Recent news and announcements"
        ),
        "ne": (
            "यो प्रश्न NEPSE Analyst को सुरक्षित कार्यक्षेत्र बाहिर पर्छ, "
            "त्यसैले म यसलाई सीधा रूपमा उत्तर दिन सक्दिनँ।\n\n"
            "म तलका अनुसन्धान कार्यहरूमा मद्दत गर्न सक्छु:\n"
            "• कम्पनीको EPS, P/E, र बुक भ्यालु\n"
            "• sector तुलना र ऐतिहासिक डेटा\n"
            "• हालको समाचार र घोषणाहरू"
        ),
    },
    # -- SQL rule answers ------------------------------------------------------
    "dividend_streak": {
        "en": "In {sector}, these stocks have paid dividends consistently for the last {years} years: {symbols}.",
        "ne": "{sector} मा पछिल्ला {years} वर्ष लगातार लाभांश दिने कम्पनीहरू भेटिए: {symbols}।",
    },
    "dividend_coverage": {
        "en": (
            "Dividend data is not available for every sector in the current dataset. "
            "Overall coverage is {covered}/{total} symbols ({pct:.1f}%)."
        ),
        "ne": (
            "हालको डेटासेटमा सबै sector मा dividend data उपलब्ध छैन। "
            "कुल coverage: {covered}/{total} symbols ({pct:.1f}%)।"
        ),
    },
    "dividend_coverage_full": {
        "en": " Sectors with full coverage include: {sectors}.",
        "ne": " Full coverage भएका sector हरू: {sectors}.",
    },
    "dividend_coverage_partial": {
        "en": " Partial coverage examples: {sectors}.",
        "ne": " Partial coverage उदाहरण: {sectors}.",
    },
    "dividend_coverage_none": {
        "en": " Sectors with no dividend rows: {sectors}.",
        "ne": " कुनै dividend data नभएका sector: {sectors}.",
    },
    "price_range_no_history": {
        "en": (
            "Price history for {company} ({symbol}) is not available in the "
            "current dataset, so a 52-week high/low cannot be computed."
        ),
        "ne": (
            "{company} ({symbol}) को price history हाल डेटासेटमा उपलब्ध छैन, "
            "त्यसैले 52-week high/low गणना गर्न सकिएन।"
        ),
    },
    "price_range_no_values": {
        "en": (
            "Price rows exist for {company} ({symbol}) up to {date}, "
            "but high/low values are missing, so the 52-week range cannot be computed."
        ),
        "ne": (
            "{company} ({symbol}) का लागि {date} सम्म price history rows "
            "भए पनि high/low मान उपलब्ध नभएकाले 52-week range निकाल्न सकिएन।"
        ),
    },
    "price_high": {
        "en": "The 52-week high for {company} ({symbol}) is {high} (window ending {date}).",
        "ne": "{company} ({symbol}) को 52-week high ({date} सम्मको window) {high} छ।",
    },
    "price_low": {
        "en": "The 52-week low for {company} ({symbol}) is {low} (window ending {date}).",
        "ne": "{company} ({symbol}) को 52-week low ({date} सम्मको window) {low} छ।",
    },
    "price_range": {
        "en": (
            "The 52-week high for {company} ({symbol}) is {high} and "
            "the 52-week low is {low} (window ending {date})."
        ),
        "ne": "{company} ({symbol}) को 52-week high {high} र low {low} छ (window ending {date})।",
    },
    "metric_with_fy": {
        "en": "The latest {label} for {company} ({symbol}) is {value} in FY {fy}.",
        "ne": "{company} ({symbol}) को पछिल्लो {label} FY {fy} मा {value} छ।",
    },
    "metric": {
        "en": "The {label} for {company} ({symbol}) is {value}.",
        "ne": "{company} ({symbol}) को {label} {value} छ।",
    },
    # -- answers written without the LLM ---------------------------------------
    "sql_summary_empty": {
        "en": "The query executed successfully, but no rows were returned.",
        "ne": "क्वेरी सफल भयो, तर कुनै पङ्क्ति नतिजा फेला परेन।",
    },
    "sql_summary_header": {
        "en": "Query executed successfully. Retrieved {count} row(s). Top results:",
        "ne": "क्वेरी सफल भयो। कुल {count} पङ्क्ति प्राप्त भयो। शीर्ष नतिजा:",
    },
    "news_summary_empty": {
        "en": "No relevant news passages were found for this query.",
        "ne": "यस प्रश्नका लागि सम्बन्धित समाचार भेटिएन।",
    },
    "news_summary_header": {
        "en": "Based on retrieved passages, here are the most relevant headlines:",
        "ne": "प्राप्त समाचार अंशका आधारमा मुख्य शीर्षकहरू:",
    },
    "news_stale": {
        "en": "The news corpus appears stale. Last update: {latest} ({total} articles), about {days} days ago.",
        "ne": "समाचार कोष पुरानो हुन सक्छ। अन्तिम अपडेट: {latest} ({total} लेख), लगभग {days} दिन अगाडि।",
    },
    # -- failures --------------------------------------------------------------
    "sql_failed": {
        "en": (
            "I could not get the data for this question. It may not be in the current "
            "dataset, or it may help to ask it more specifically."
        ),
        "ne": (
            "यो प्रश्नको लागि संरचित डेटा प्राप्त गर्न सकिएन। "
            "डेटा उपलब्ध नहुन सक्छ, वा प्रश्नलाई अझ स्पष्ट रूपमा सोध्दा मद्दत पुग्न सक्छ।"
        ),
    },
    "news_unavailable": {
        "en": (
            "News retrieval is currently unavailable because the embedding/vector stack could not be loaded. "
            "Please verify model availability and retry."
        ),
        "ne": "समाचार खोज सुविधा हाल उपलब्ध छैन। एम्बेडिङ मोडेल वा भेक्टर स्टोर लोड हुन सकेन।",
    },
    "news_not_found": {
        "en": (
            "No relevant news or announcements were found for this query in the current corpus. "
            "The news corpus is updated weekly — try again after the next refresh."
        ),
        "ne": "यस प्रश्नसँग सम्बन्धित कुनै समाचार भेटिएन।",
    },
    "timeout": {
        "en": (
            "This question could not be answered within the {seconds:g} s time limit. "
            "Please try a narrower or more specific question."
        ),
        "ne": (
            "यो प्रश्नको उत्तर {seconds:g} सेकेन्डको समय सीमाभित्र तयार गर्न सकिएन। "
            "कृपया प्रश्नलाई अझ सानो वा स्पष्ट बनाएर फेरि प्रयास गर्नुहोस्।"
        ),
    },
    # -- progress stages (shown while a question is being answered) ---------
    "stage_understanding": {"en": "Understanding the question", "ne": "प्रश्न बुझ्दै"},
    "stage_querying_database": {"en": "Querying the database", "ne": "डाटाबेसबाट जानकारी खोज्दै"},
    "stage_searching_news": {"en": "Searching the news", "ne": "समाचार खोज्दै"},
    "stage_writing_answer": {"en": "Writing the answer", "ne": "उत्तर लेख्दै"},
    "unexpected_error": {
        "en": "Something went wrong while answering this question. Please try again in a moment.",
        "ne": "यो प्रश्नको उत्तर दिँदा समस्या आयो। कृपया केही समयपछि फेरि प्रयास गर्नुहोस्।",
    },
}


def message(key: str, language: str, **values: object) -> str:
    """The ``key`` message in ``language`` (Nepali for "ne", else English), filled with ``values``."""
    entry = MESSAGES[key]
    return entry.get(language, entry["en"]).format(**values)
