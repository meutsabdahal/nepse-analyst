import sqlite3
import time
import unittest
from unittest.mock import patch

from nepse_analyst.database import execute_query, validate_read_only_sql
from nepse_analyst.prompts import build_sql_synthesis_prompt

ENDLESS_COUNT = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r"
ENDLESS_ROWS = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT n FROM r"


def _memory_db():
    return patch("nepse_analyst.database.get_connection", side_effect=lambda **_: sqlite3.connect(":memory:"))


class SqlSafetyTests(unittest.TestCase):
    def test_select_is_allowed(self) -> None:
        is_valid, error = validate_read_only_sql("SELECT 1 AS ok")
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_with_query_is_allowed(self) -> None:
        is_valid, error = validate_read_only_sql(
            "WITH t AS (SELECT 1 AS x) SELECT x FROM t"
        )
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_write_query_is_rejected(self) -> None:
        is_valid, error = validate_read_only_sql("UPDATE companies SET is_active = 0")
        self.assertFalse(is_valid)
        self.assertEqual(error, "Only SELECT and WITH queries are allowed")

    def test_multiple_statements_are_rejected(self) -> None:
        is_valid, error = validate_read_only_sql("SELECT 1; DROP TABLE companies")
        self.assertFalse(is_valid)
        self.assertEqual(error, "Only one SQL statement is allowed")

    def test_execute_query_rejects_write_without_opening_connection(self) -> None:
        with patch(
            "nepse_analyst.database.get_connection",
            side_effect=AssertionError("get_connection should not be called"),
        ):
            result = execute_query("UPDATE companies SET is_active = 0")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Only SELECT and WITH queries are allowed")

    def test_execute_query_rejects_multi_statement_without_opening_connection(
        self,
    ) -> None:
        with patch(
            "nepse_analyst.database.get_connection",
            side_effect=AssertionError("get_connection should not be called"),
        ):
            result = execute_query("SELECT 1; SELECT 2")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Only one SQL statement is allowed")



class ConnectionTests(unittest.TestCase):
    def test_reading_a_missing_database_does_not_create_it(self) -> None:
        import os
        import tempfile

        from nepse_analyst import database

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "processed", "nepse.db")
            with patch.object(database, "DB_PATH", path):
                with self.assertRaises(FileNotFoundError):
                    database.get_connection()
                self.assertFalse(database.execute_query("SELECT 1")["success"])
            self.assertFalse(os.path.exists(os.path.dirname(path)))


class QueryLimitTests(unittest.TestCase):
    def test_runaway_query_is_stopped_at_the_time_limit(self) -> None:
        start = time.monotonic()
        with _memory_db():
            result = execute_query(ENDLESS_COUNT, timeout_ms=200)
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertFalse(result["success"])
        self.assertIn("0.2 s time limit", result["error"])

    def test_rows_are_capped_without_reading_the_whole_result(self) -> None:
        with _memory_db():
            result = execute_query(ENDLESS_ROWS, timeout_ms=2000, max_rows=5)
        self.assertTrue(result["success"])
        self.assertEqual([r["n"] for r in result["rows"]], [1, 2, 3, 4, 5])
        self.assertEqual(result["row_count"], 5)
        self.assertTrue(result["truncated"])

    def test_result_at_the_cap_is_not_truncated(self) -> None:
        with _memory_db():
            result = execute_query(ENDLESS_ROWS + " LIMIT 5", max_rows=5)
        self.assertEqual((result["row_count"], result["truncated"]), (5, False))

    def test_limits_can_be_disabled_for_trusted_sql(self) -> None:
        with _memory_db():
            result = execute_query(ENDLESS_ROWS + " LIMIT 1200", timeout_ms=None, max_rows=None)
        self.assertEqual((result["row_count"], result["truncated"]), (1200, False))

    def test_ordinary_errors_are_not_reported_as_timeouts(self) -> None:
        with _memory_db():
            result = execute_query("SELECT missing_column FROM sqlite_master", timeout_ms=200)
        self.assertFalse(result["success"])
        self.assertIn("no such column", result["error"])

    def test_synthesis_prompt_does_not_present_a_truncated_count_as_a_total(self) -> None:
        rows = [{"n": i} for i in range(5)]
        capped = build_sql_synthesis_prompt("q", "SELECT", rows, ["n"], "en", truncated=True)
        self.assertIn("At least 5 rows", capped)
        self.assertIn("5 rows:", build_sql_synthesis_prompt("q", "SELECT", rows, ["n"], "en"))


if __name__ == "__main__":
    unittest.main()
