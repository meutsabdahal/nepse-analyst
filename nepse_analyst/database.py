from __future__ import annotations

import os
import re
import sqlite3

from nepse_analyst.config import DB_PATH, DB_BUSY_TIMEOUT_MS


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

_WRITE_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|"
    r"PRAGMA|VACUUM|REINDEX|ANALYZE|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b",
    flags=re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments so validation checks operate on executable tokens."""
    no_block_comments = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", no_block_comments)


def validate_read_only_sql(sql: str) -> tuple[bool, str | None]:
    """Validate that SQL is a single read-only SELECT/WITH statement."""
    stripped = (sql or "").strip()
    if not stripped:
        return False, "Empty SQL query"

    normalized = _strip_sql_comments(stripped)
    statements = [segment.strip() for segment in normalized.split(";") if segment.strip()]
    if len(statements) != 1:
        return False, "Only one SQL statement is allowed"

    statement = statements[0]
    upper = statement.upper()
    if not (upper.startswith("SELECT ") or upper.startswith("WITH ")):
        return False, "Only SELECT and WITH queries are allowed"

    if _WRITE_SQL_PATTERN.search(upper):
        return False, "Only read-only SQL is allowed"

    return True, None


def get_connection(read_only: bool = False):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    kwargs: dict = {"timeout": max(DB_BUSY_TIMEOUT_MS, 0) / 1000.0}
    db_target = DB_PATH
    if read_only:
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"Database not found at {DB_PATH}")
        db_target = f"file:{DB_PATH}?mode=ro"
        kwargs["uri"] = True

    conn = sqlite3.connect(db_target, **kwargs)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {max(DB_BUSY_TIMEOUT_MS, 0)}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_database():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.executescript(FULL_SCHEMA_SQL)  # combined CREATE TABLE + INDEX string
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def execute_query(sql: str) -> dict:
    conn = None
    try:
        is_valid, validation_error = validate_read_only_sql(sql)
        if not is_valid:
            return {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "error": validation_error,
            }

        conn = get_connection(read_only=True)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return {
            "success": True,
            "rows": [dict(zip(columns, row)) for row in rows],
            "columns": columns,
            "row_count": len(rows),
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "error": str(e),
        }
    finally:
        if conn is not None:
            conn.close()


def get_schema_summary() -> str:
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cursor.fetchall()]
        lines = []
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table})")
            cols = cursor.fetchall()
            col_defs = ", ".join(f"{c[1]} {c[2]}" for c in cols)
            lines.append(f"{table}({col_defs})")
        return "\n".join(lines)
    finally:
        if conn is not None:
            conn.close()
