import os
import re
import sqlite3
import tempfile
import time
import unittest

from nepse_analyst.database import FULL_SCHEMA_SQL
from nepse_analyst.prompts import build_sql_prompt
from nepse_analyst.schema_context import (
    COLUMN_NOTES,
    RANGE_COLUMNS,
    TABLES,
    VALUE_LIST_COLUMNS,
    build_schema_context,
    get_schema_context,
)


def _declared_columns() -> dict[str, list[str]]:
    conn = sqlite3.connect(":memory:")
    conn.executescript(FULL_SCHEMA_SQL)
    try:
        return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in TABLES}
    finally:
        conn.close()


def _sample_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(FULL_SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO companies (symbol, name, sector) VALUES (?, ?, ?)",
        [("NABIL", "Nabil Bank Limited", "Commercial Banks"), ("AHPC", "Arun Valley", "Hydropower")],
    )
    conn.executemany(
        "INSERT INTO price_history (symbol, trade_date, close_price) VALUES (?, ?, ?)",
        [("NABIL", "2024-01-01", 500.0), ("NABIL", "2024-03-15", 510.0)],
    )
    conn.execute("INSERT INTO fundamentals (symbol, fiscal_year, eps) VALUES ('NABIL', '2080/81', 30.0)")
    conn.execute(
        "INSERT INTO ipos (symbol, company_name, issue_price, listing_date, status) "
        "VALUES ('AHPC', 'Arun Valley', 100, '2020-01-01', 'listed')"
    )
    conn.executemany(
        "INSERT INTO indices (trade_date, index_name, close_value) VALUES (?, ?, ?)",
        [("2024-03-15", "NEPSE", 2000.0), ("2024-03-15", "Banking", 1500.0)],
    )
    conn.commit()
    conn.close()


class SchemaContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "nepse.db")
        _sample_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            self.context = build_schema_context(conn)
        finally:
            conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def column_line(self, table: str, column: str) -> str:
        block = self.context.split(f"\n{table} (", 1)[1].split("\n\n", 1)[0]
        match = re.search(rf"^  {column} .*$", block, re.MULTILINE)
        self.assertIsNotNone(match, f"{table}.{column} missing")
        return match.group(0)

    def test_every_declared_column_is_listed(self):
        for table, columns in _declared_columns().items():
            for column in columns:
                with self.subTest(column=f"{table}.{column}"):
                    self.column_line(table, column)
        self.assertIn("oversubscription_rate", self.column_line("ipos", "oversubscription_rate"))

    def test_value_lists_come_from_the_data(self):
        self.assertIn("only these values: 'Commercial Banks', 'Hydropower'", self.column_line("companies", "sector"))
        self.assertIn("only these values: 'Banking', 'NEPSE'", self.column_line("indices", "index_name"))
        self.assertIn("only these values: 'listed'", self.column_line("ipos", "status"))
        for absent in ("Telecom", "'upcoming'", "'allotment'", "Microfinance'"):
            self.assertNotIn(absent, self.context.split("IMPORTANT RULES")[0])

    def test_empty_columns_are_marked(self):
        self.assertIn("no data", self.column_line("companies", "market_cap"))
        self.assertIn("no data", self.column_line("ipos", "oversubscription_rate"))
        self.assertNotIn("no data", self.column_line("price_history", "close_price"))

    def test_date_ranges_come_from_the_data(self):
        self.assertIn("data spans 2024-01-01 to 2024-03-15", self.column_line("price_history", "trade_date"))
        self.assertIn("data spans 2080/81 to 2080/81", self.column_line("fundamentals", "fiscal_year"))

    def test_foreign_keys_from_schema(self):
        self.assertIn("price_history.symbol -> companies.symbol", self.context)

    def test_rules_do_not_suggest_wall_clock_dates(self):
        self.assertNotIn("date('now', ", self.context)
        self.assertIn("never to date('now')", self.context)

    def test_missing_database_falls_back_to_declared_schema(self):
        text = get_schema_context(os.path.join(self.tmp.name, "missing.db"))
        self.assertIn("declared schema", text)
        self.assertIn("oversubscription_rate", text)
        self.assertNotIn("only these values", text)

    def test_cache_refreshes_when_database_changes(self):
        before = get_schema_context(self.db_path)
        self.assertNotIn("'Microfinance'", before)
        time.sleep(0.01)
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO companies (symbol, name, sector) VALUES ('CBBL', 'Chhimek', 'Microfinance')")
        conn.commit()
        conn.close()
        os.utime(self.db_path, ns=(time.time_ns(), time.time_ns() + 1_000_000))
        self.assertIn("'Microfinance'", get_schema_context(self.db_path))


class HandWrittenNotesTests(unittest.TestCase):
    def test_notes_and_column_lists_name_real_columns(self):
        declared = _declared_columns()
        for source in (COLUMN_NOTES, VALUE_LIST_COLUMNS, RANGE_COLUMNS):
            for table, columns in source.items():
                for column in columns:
                    with self.subTest(column=f"{table}.{column}"):
                        self.assertIn(column, declared.get(table, []))


class SqlPromptTests(unittest.TestCase):
    def test_prompt_uses_generated_schema(self):
        prompt = build_sql_prompt("placeholder")
        self.assertIn("DATABASE SCHEMA (", prompt)
        self.assertIn("oversubscription_rate", prompt)
        self.assertIn("Question: placeholder", prompt)


if __name__ == "__main__":
    unittest.main()
