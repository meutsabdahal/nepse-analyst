"""Build the schema section of the SQL prompt from the database itself.

Table and column definitions come from SQLite (``PRAGMA table_info`` and
``foreign_key_list``). Value lists (sectors, index names, IPO statuses), date
ranges, and empty columns come from the current data, so the prompt cannot
drift from what the generated SQL actually runs against. Only the units and
formats in ``COLUMN_NOTES`` are written by hand; tests check that every note
names a real column.
"""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache

from nepse_analyst.config import DB_PATH
from nepse_analyst.database import FULL_SCHEMA_SQL, SCHEMA_STATEMENTS

# Tables shown to the model, in this order.
TABLES: tuple[str, ...] = (
    "companies", "price_history", "fundamentals", "dividends", "ipos", "indices",
)

# Units and formats that the data alone cannot show.
COLUMN_NOTES: dict[str, dict[str, str]] = {
    "companies": {
        "market_cap": "NPR, listed_shares x latest close_price",
        "is_active": "1 = currently listed",
    },
    "price_history": {
        "trade_date": "ISO date 'YYYY-MM-DD'",
        "turnover": "NPR",
    },
    "fundamentals": {
        "fiscal_year": "Nepali fiscal year 'YYYY/YY', e.g. '2081/82'",
        "eps": "earnings per share, NPR",
        "book_value": "book value per share, NPR",
        "roe": "return on equity, percent",
    },
    "dividends": {
        "fiscal_year": "Nepali fiscal year 'YYYY/YY'",
        "cash_dividend": "percent of face value (15.0 = 15%)",
        "bonus_shares": "stock dividend percent (10.0 = 10%)",
    },
    "ipos": {
        "issue_price": "NPR per share",
        "listing_price": "NPR, first traded price",
    },
    "indices": {
        "trade_date": "ISO date 'YYYY-MM-DD'",
    },
}

# Columns whose distinct values are listed in full.
VALUE_LIST_COLUMNS: dict[str, tuple[str, ...]] = {
    "companies": ("sector",),
    "ipos": ("status",),
    "indices": ("index_name",),
}
MAX_LISTED_VALUES = 40

# Columns whose min..max range is shown, so the model anchors relative time
# windows to the data instead of to today's date.
RANGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "price_history": ("trade_date",),
    "fundamentals": ("fiscal_year",),
    "dividends": ("fiscal_year",),
    "ipos": ("listing_date",),
    "indices": ("trade_date",),
}

RULES = """IMPORTANT RULES:
1. To filter by sector, JOIN companies and use one of the exact sector values listed above.
2. For "latest fiscal year", use: fiscal_year = (SELECT MAX(fiscal_year) FROM fundamentals).
3. Anchor every relative time window to the latest date in the data, never to date('now'); the data may end well before today.
   - "last N trading days": trade_date IN (SELECT DISTINCT trade_date FROM price_history ORDER BY trade_date DESC LIMIT N)
   - calendar windows ("past year", "52-week", "last 90 days"): trade_date > date((SELECT MAX(trade_date) FROM price_history WHERE symbol = 'XYZ'), '-365 day')
   - use the same pattern on indices.trade_date or ipos.listing_date for those tables.
4. Columns marked "no data" are NULL in every row; a query that needs them will return no useful result.
5. All monetary values are in NPR unless stated otherwise.
6. Return only the SQL query. No explanation. No markdown. No backticks."""


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _column_line(conn: sqlite3.Connection | None, table: str, col: sqlite3.Row | tuple, row_count: int) -> str:
    _cid, name, col_type, notnull, _default, pk = tuple(col)
    parts = [f"  {name} {col_type or ''}".rstrip()]
    if pk:
        parts.append("PRIMARY KEY")
    elif notnull:
        parts.append("NOT NULL")
    line = " ".join(parts)

    notes: list[str] = []
    if note := COLUMN_NOTES.get(table, {}).get(name):
        notes.append(note)
    if conn is not None and row_count:
        q = _ident(name)
        t = _ident(table)
        non_null = conn.execute(f"SELECT COUNT({q}) FROM {t}").fetchone()[0]
        if non_null == 0:
            notes.append("no data: NULL in every row")
        elif name in VALUE_LIST_COLUMNS.get(table, ()):
            values = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {q} FROM {t} WHERE {q} IS NOT NULL ORDER BY {q} LIMIT {MAX_LISTED_VALUES + 1}"
            )]
            shown = ", ".join(_quote(v) for v in values[:MAX_LISTED_VALUES])
            more = ", ..." if len(values) > MAX_LISTED_VALUES else ""
            notes.append(f"only these values: {shown}{more}")
        elif name in RANGE_COLUMNS.get(table, ()):
            lo, hi = conn.execute(f"SELECT MIN({q}), MAX({q}) FROM {t}").fetchone()
            notes.append(f"data spans {lo} to {hi}")
    return f"{line}  -- {'; '.join(notes)}" if notes else line


def build_schema_context(conn: sqlite3.Connection | None) -> str:
    """Schema text for the SQL prompt.

    With ``conn`` the text reflects that database. Without one it falls back
    to the declared schema (``database.SCHEMA_STATEMENTS``) and omits value
    lists, ranges and row counts.
    """
    schema_conn = conn
    if schema_conn is None:
        schema_conn = sqlite3.connect(":memory:")
        schema_conn.executescript(FULL_SCHEMA_SQL)

    lines = [
        "You are a SQLite expert. The database contains Nepal Stock Exchange (NEPSE) data.",
        "",
        "DATABASE SCHEMA (generated from the live database):" if conn is not None
        else "DATABASE SCHEMA (declared schema; database not available, so no value lists):",
    ]
    foreign_keys: list[str] = []
    for table in TABLES:
        cols = schema_conn.execute(f"PRAGMA table_info({_ident(table)})").fetchall()
        if not cols:
            continue
        row_count = (
            conn.execute(f"SELECT COUNT(*) FROM {_ident(table)}").fetchone()[0] if conn is not None else 0
        )
        header = f"{table} ({row_count} rows)" if conn is not None else table
        lines += ["", header]
        lines += [_column_line(conn, table, col, row_count) for col in cols]
        for fk in schema_conn.execute(f"PRAGMA foreign_key_list({_ident(table)})").fetchall():
            _id, _seq, ref_table, from_col, to_col = tuple(fk)[:5]
            foreign_keys.append(f"{table}.{from_col} -> {ref_table}.{to_col}")

    if foreign_keys:
        lines += ["", "FOREIGN KEYS: " + ", ".join(foreign_keys)]
    lines += ["", RULES]

    if conn is None:
        schema_conn.close()
    return "\n".join(lines) + "\n"


@lru_cache(maxsize=4)
def _cached_context(db_path: str, mtime_ns: int) -> str:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not present & set(TABLES):
            # An empty or unrelated file: describe the declared schema, not an empty one.
            return build_schema_context(None)
        return build_schema_context(conn)
    finally:
        conn.close()


def get_schema_context(db_path: str = DB_PATH) -> str:
    """Schema context for ``db_path``, rebuilt whenever the file changes."""
    try:
        mtime_ns = os.stat(db_path).st_mtime_ns
    except OSError:
        return build_schema_context(None)
    try:
        return _cached_context(db_path, mtime_ns)
    except sqlite3.Error:
        return build_schema_context(None)


__all__ = [
    "COLUMN_NOTES",
    "RULES",
    "SCHEMA_STATEMENTS",
    "TABLES",
    "build_schema_context",
    "get_schema_context",
]
