import unittest

from nepse_analyst.database import validate_read_only_sql


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


if __name__ == "__main__":
    unittest.main()
