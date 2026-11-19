"""Example questions shown in the web chat, grouped by type.

Every example is shown, so keep the list short. Each one must be answerable
from the current data, checked against the database when it was chosen:

- Fundamentals (EPS, P/E, book value) cover FY 2083/84 for about 210
  companies. ROE is empty everywhere, so no ROE examples.
- Dividends cover FY 2067/68 to 2082/83, prices run to the latest trading day,
  and the Banking, Hydropower and NEPSE indices start in mid-2025.
- No news examples: the news corpus ends in 2016 until it is rebuilt.
- No IPO examples: the IPO table stops at 2021 listings.

Examples must not copy benchmark questions; tests/test_example_questions.py
checks this, and that exactly one example is in Nepali.
"""

EXAMPLE_GROUPS: list[dict] = [
    {
        "group": "Companies",
        "questions": [
            "What is NICA's P/E ratio?",
            "What were HIDCL's 52-week high and low prices?",
            "HIDCL को पछिल्लो EPS कति छ?",
        ],
    },
    {
        "group": "Sectors",
        "questions": [
            "Which five microfinance companies have the highest EPS?",
            "Which development bank has the lowest P/E ratio?",
        ],
    },
    {
        "group": "Dividends",
        "questions": [
            "Which commercial banks paid a cash dividend in FY 2082/83?",
            "Show NABIL's cash dividend history.",
        ],
    },
    {
        "group": "Market",
        "questions": [
            "How did the Hydropower index change over the last six months?",
            "Which sector traded the most in the last 30 days?",
        ],
    },
    {
        "group": "Concepts",
        "questions": ["What does a P/E ratio tell an investor?"],
    },
]

EXAMPLE_QUESTIONS: list[str] = [q for group in EXAMPLE_GROUPS for q in group["questions"]]
