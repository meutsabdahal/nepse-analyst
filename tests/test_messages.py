import ast
import string
import unittest
from pathlib import Path

from nepse_analyst.messages import LANGUAGES, MESSAGES, message

ROOT = Path(__file__).resolve().parents[1]


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class MessageTableTests(unittest.TestCase):
    def test_every_message_exists_in_every_language(self) -> None:
        for key, entry in MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(set(entry), set(LANGUAGES))
                self.assertTrue(all(text.strip() for text in entry.values()))

    def test_placeholders_match_across_languages(self) -> None:
        for key, entry in MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(_fields(entry["ne"]), _fields(entry["en"]))

    def test_language_selection(self) -> None:
        self.assertIn("time limit", message("timeout", "en", seconds=60))
        self.assertIn("सेकेन्ड", message("timeout", "ne", seconds=60))
        self.assertEqual(message("timeout", "mixed", seconds=60), message("timeout", "en", seconds=60))

    def test_every_message_used_in_code_exists(self) -> None:
        used = set()
        for path in [*(ROOT / "nepse_analyst").rglob("*.py"), ROOT / "app.py"]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "message"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    used.add(node.args[0].value)
        self.assertTrue(used)
        self.assertLessEqual(used, set(MESSAGES))

    def test_every_message_in_the_table_is_referenced(self) -> None:
        constants = set()
        for path in [*(ROOT / "nepse_analyst").rglob("*.py"), ROOT / "app.py"]:
            if path.name == "messages.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    constants.add(node.value)
        self.assertEqual(set(MESSAGES) - constants, set())

    def test_pipeline_has_no_inline_nepali(self) -> None:
        text = (ROOT / "nepse_analyst" / "pipeline.py").read_text(encoding="utf-8")
        self.assertFalse(any("ऀ" <= ch <= "ॿ" for ch in text))


if __name__ == "__main__":
    unittest.main()
