SCHEMA_CONTEXT = """
You are a SQLite expert. The database is called nepse.db and contains Nepal Stock Exchange (NEPSE) data.

DATABASE SCHEMA:

companies(symbol TEXT PRIMARY KEY, name TEXT, sector TEXT, listed_shares INTEGER, 
          paid_up_value REAL, total_paid_up REAL, market_cap REAL, is_active INTEGER)
  -- sector values: 'Commercial Banks', 'Hydropower', 'Life Insurance', 'Development Banks',
  --                'Finance Companies', 'Microfinance', 'Non-Life Insurance', 'Hotels & Tourism',
  --                'Manufacturing', 'Trading', 'Mutual Funds', 'Investment', 'Telecom', 'Others'

price_history(id, symbol TEXT, trade_date TEXT, open_price REAL, high_price REAL,
              low_price REAL, close_price REAL, volume INTEGER, turnover REAL)
  -- trade_date is ISO string: '2026-03-10'
  -- turnover is in NPR (Nepalese Rupees)

fundamentals(id, symbol TEXT, fiscal_year TEXT, eps REAL, pe_ratio REAL, book_value REAL,
             roe REAL, net_profit REAL, total_assets REAL, revenue REAL)
  -- fiscal_year format: '2080/81' (Nepali fiscal year)
  -- eps = earnings per share in NPR
  -- book_value = book value per share in NPR
  -- roe = return on equity as a percentage

dividends(id, symbol TEXT, fiscal_year TEXT, cash_dividend REAL, bonus_shares REAL,
          book_close_date TEXT, announced_date TEXT)
  -- cash_dividend = percentage of face value (e.g. 15.0 means 15%)
  -- bonus_shares = percentage stock dividend (e.g. 10.0 means 10%)

ipos(id, symbol TEXT, company_name TEXT, sector TEXT, issue_date TEXT, listing_date TEXT,
     issue_price REAL, listing_price REAL, shares_issued INTEGER, 
     total_applicants INTEGER, status TEXT)
  -- status: 'listed' | 'upcoming' | 'allotment'

indices(id, trade_date TEXT, index_name TEXT, open_value REAL, close_value REAL,
        change_points REAL, change_percent REAL, turnover REAL)
  -- index_name values: 'NEPSE', 'Banking', 'Hydropower', 'Development Banks', 
  --                    'Life Insurance', 'Manufacturing And Processing', 'Microfinance'

FOREIGN KEYS: price_history.symbol → companies.symbol
              fundamentals.symbol → companies.symbol
              dividends.symbol → companies.symbol

IMPORTANT RULES:
1. Always use JOIN with companies table when filtering by sector
2. For "latest fiscal year", use: WHERE fiscal_year = (SELECT MAX(fiscal_year) FROM fundamentals)
3. For "last N trading days", use: WHERE trade_date >= date('now', '-N days') or ORDER BY trade_date DESC LIMIT N
4. For "52-week high/low", query price_history for the last 365 days
5. All monetary values are in NPR unless stated otherwise
6. Return only the SQL query. No explanation. No markdown. No backticks.
"""


FEW_SHOT_EXAMPLES = """
EXAMPLE 1 — Simple fundamental lookup with sector filter:
Question: Which commercial bank has the highest EPS in the latest fiscal year?
SQL: SELECT c.symbol, c.name, f.eps, f.fiscal_year FROM fundamentals f JOIN companies c ON f.symbol = c.symbol WHERE c.sector = 'Commercial Banks' AND f.fiscal_year = (SELECT MAX(fiscal_year) FROM fundamentals WHERE symbol IN (SELECT symbol FROM companies WHERE sector = 'Commercial Banks')) ORDER BY f.eps DESC LIMIT 1

EXAMPLE 2 — Dividend history with consecutive year logic:
Question: List all hydropower companies that paid cash dividends in fiscal year 2080/81.
SQL: SELECT c.symbol, c.name, d.cash_dividend, d.fiscal_year FROM dividends d JOIN companies c ON d.symbol = c.symbol WHERE c.sector = 'Hydropower' AND d.fiscal_year = '2080/81' AND d.cash_dividend > 0 ORDER BY d.cash_dividend DESC

EXAMPLE 3 — Price history aggregation (52-week range):
Question: What is the 52-week high and low for NABIL Bank?
SQL: SELECT symbol, MAX(high_price) as week52_high, MIN(low_price) as week52_low FROM price_history WHERE symbol = 'NABIL' AND trade_date >= date('now', '-365 days')

EXAMPLE 4 — Cross-sector turnover comparison:
Question: Which sector has had the highest average daily turnover over the last 30 trading days?
SQL: SELECT c.sector, AVG(ph.turnover) as avg_daily_turnover FROM price_history ph JOIN companies c ON ph.symbol = c.symbol WHERE ph.trade_date IN (SELECT DISTINCT trade_date FROM price_history ORDER BY trade_date DESC LIMIT 30) GROUP BY c.sector ORDER BY avg_daily_turnover DESC LIMIT 1

EXAMPLE 5 — IPO oversubscription:
Question: What are the top 5 most oversubscribed IPOs in NEPSE history?
SQL: SELECT company_name, symbol, total_applicants, shares_issued, issue_price, listing_price FROM ipos WHERE status = 'listed' AND total_applicants IS NOT NULL ORDER BY total_applicants DESC LIMIT 5

EXAMPLE 6 — EPS comparison across multiple companies (P/E by market cap):
Question: What is the P/E ratio of the top 3 commercial banks by market capitalisation?
SQL: SELECT c.symbol, c.name, c.market_cap, f.pe_ratio, f.fiscal_year FROM fundamentals f JOIN companies c ON f.symbol = c.symbol WHERE c.sector = 'Commercial Banks' AND f.fiscal_year = (SELECT MAX(fiscal_year) FROM fundamentals) AND f.pe_ratio IS NOT NULL ORDER BY c.market_cap DESC LIMIT 3
"""


def build_sql_prompt(question: str) -> str:
    return f"""{SCHEMA_CONTEXT}

WORKED EXAMPLES:
{FEW_SHOT_EXAMPLES}

Now write the SQL query for this question. Return ONLY the SQL. No explanation, no markdown, no backticks.

Question: {question}
SQL:"""
