from __future__ import annotations

import os
import sqlite3

from nepse_analyst.config import DB_PATH


# Table names
TABLE_COMPANIES = "companies"
TABLE_PRICE_HISTORY = "price_history"
TABLE_FUNDAMENTALS = "fundamentals"
TABLE_DIVIDENDS = "dividends"
TABLE_IPOS = "ipos"
TABLE_INDICES = "indices"

# Index names
INDEX_PRICE_SYMBOL_DATE = "idx_price_symbol_date"
INDEX_FUNDAMENTALS_SYMBOL = "idx_fundamentals_symbol"
INDEX_DIVIDENDS_SYMBOL = "idx_dividends_symbol"
INDEX_COMPANIES_SECTOR = "idx_companies_sector"
INDEX_INDICES_DATE = "idx_indices_date"


CREATE_TABLE_COMPANIES = f"""
CREATE TABLE IF NOT EXISTS {TABLE_COMPANIES} (
    symbol          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sector          TEXT NOT NULL,
    listed_shares   INTEGER,
    paid_up_value   REAL,
    total_paid_up   REAL,
    market_cap      REAL,
    is_active       INTEGER DEFAULT 1
);
""".strip()


CREATE_TABLE_PRICE_HISTORY = f"""
CREATE TABLE IF NOT EXISTS {TABLE_PRICE_HISTORY} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT REFERENCES {TABLE_COMPANIES}(symbol),
    trade_date      TEXT NOT NULL,
    open_price      REAL,
    high_price      REAL,
    low_price       REAL,
    close_price     REAL NOT NULL,
    volume          INTEGER,
    turnover        REAL
);
""".strip()


CREATE_TABLE_FUNDAMENTALS = f"""
CREATE TABLE IF NOT EXISTS {TABLE_FUNDAMENTALS} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT REFERENCES {TABLE_COMPANIES}(symbol),
    fiscal_year     TEXT NOT NULL,
    eps             REAL,
    pe_ratio        REAL,
    book_value      REAL,
    roe             REAL,
    net_profit      REAL,
    total_assets    REAL,
    revenue         REAL
);
""".strip()


CREATE_TABLE_DIVIDENDS = f"""
CREATE TABLE IF NOT EXISTS {TABLE_DIVIDENDS} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT REFERENCES {TABLE_COMPANIES}(symbol),
    fiscal_year     TEXT NOT NULL,
    cash_dividend   REAL,
    bonus_shares    REAL,
    book_close_date TEXT,
    announced_date  TEXT
);
""".strip()


CREATE_TABLE_IPOS = f"""
CREATE TABLE IF NOT EXISTS {TABLE_IPOS} (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT,
    company_name     TEXT NOT NULL,
    sector           TEXT,
    issue_date       TEXT,
    listing_date     TEXT,
    issue_price      REAL,
    listing_price    REAL,
    shares_issued    INTEGER,
    total_applicants INTEGER,
    oversubscription_rate REAL,
    status           TEXT
);
""".strip()


CREATE_TABLE_INDICES = f"""
CREATE TABLE IF NOT EXISTS {TABLE_INDICES} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT NOT NULL,
    index_name      TEXT NOT NULL,
    open_value      REAL,
    close_value     REAL NOT NULL,
    change_points   REAL,
    change_percent  REAL,
    turnover        REAL
);
""".strip()


CREATE_INDEX_PRICE_SYMBOL_DATE = f"""
CREATE INDEX IF NOT EXISTS {INDEX_PRICE_SYMBOL_DATE}
ON {TABLE_PRICE_HISTORY}(symbol, trade_date);
""".strip()


CREATE_INDEX_FUNDAMENTALS_SYMBOL = f"""
CREATE INDEX IF NOT EXISTS {INDEX_FUNDAMENTALS_SYMBOL}
ON {TABLE_FUNDAMENTALS}(symbol, fiscal_year);
""".strip()


CREATE_INDEX_DIVIDENDS_SYMBOL = f"""
CREATE INDEX IF NOT EXISTS {INDEX_DIVIDENDS_SYMBOL}
ON {TABLE_DIVIDENDS}(symbol);
""".strip()


CREATE_INDEX_COMPANIES_SECTOR = f"""
CREATE INDEX IF NOT EXISTS {INDEX_COMPANIES_SECTOR}
ON {TABLE_COMPANIES}(sector);
""".strip()


CREATE_INDEX_INDICES_DATE = f"""
CREATE INDEX IF NOT EXISTS {INDEX_INDICES_DATE}
ON {TABLE_INDICES}(trade_date, index_name);
""".strip()


SCHEMA_STATEMENTS: tuple[str, ...] = (
    CREATE_TABLE_COMPANIES,
    CREATE_TABLE_PRICE_HISTORY,
    CREATE_TABLE_FUNDAMENTALS,
    CREATE_TABLE_DIVIDENDS,
    CREATE_TABLE_IPOS,
    CREATE_TABLE_INDICES,
    CREATE_INDEX_PRICE_SYMBOL_DATE,
    CREATE_INDEX_FUNDAMENTALS_SYMBOL,
    CREATE_INDEX_DIVIDENDS_SYMBOL,
    CREATE_INDEX_COMPANIES_SECTOR,
    CREATE_INDEX_INDICES_DATE,
)

FULL_SCHEMA_SQL = "\n\n".join(SCHEMA_STATEMENTS)


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executescript(FULL_SCHEMA_SQL)  # combined CREATE TABLE + INDEX string
    conn.commit()
    conn.close()
