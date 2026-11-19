"""The answer renderer's Markdown subset (web/markdown.js), run under Node."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

MARKDOWN_JS = Path(__file__).resolve().parents[1] / "web" / "markdown.js"
NODE = shutil.which("node")

_RUNNER = """
const md = require(process.argv[1]);
let input = "";
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
    const { fn, text } = JSON.parse(input);
    process.stdout.write(JSON.stringify(md[fn](text)));
});
"""


@unittest.skipUnless(NODE, "node is not installed")
class AnswerMarkdownTests(unittest.TestCase):
    def call(self, fn: str, text: str):
        out = subprocess.run(
            [NODE, "-e", _RUNNER, str(MARKDOWN_JS)],
            input=json.dumps({"fn": fn, "text": text}),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return json.loads(out.stdout)

    def blocks(self, text: str):
        return self.call("parseMarkdownBlocks", text)

    def inline(self, text: str):
        return self.call("parseMarkdownInline", text)

    def test_bold_has_no_literal_asterisks(self) -> None:
        self.assertEqual(
            self.inline("EPS is **Rs 33.89** this year"),
            [
                {"type": "text", "text": "EPS is "},
                {"type": "strong", "children": [{"type": "text", "text": "Rs 33.89"}]},
                {"type": "text", "text": " this year"},
            ],
        )

    def test_hybrid_section_headings(self) -> None:
        blocks = self.blocks("**Structured Data:**\nNABIL closed at Rs 549.\n\n**Recent News:**\nNABIL announced [1].")
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "paragraph"])
        self.assertTrue(blocks[0]["text"].startswith("**Structured Data:**\n"))
        nodes = self.inline(blocks[1]["text"])
        self.assertEqual(nodes[0]["type"], "strong")
        self.assertEqual(nodes[-2], {"type": "citation", "number": 1, "text": "[1]"})

    def test_bullet_and_numbered_lists(self) -> None:
        blocks = self.blocks("Top payers:\n- NABIL: 12.5%\n* NIMB: 10%\n\n1. First\n2. Second\n   continued")
        self.assertEqual(blocks[0], {"type": "paragraph", "text": "Top payers:"})
        self.assertEqual(blocks[1], {"type": "list", "ordered": False, "start": 1, "items": ["NABIL: 12.5%", "NIMB: 10%"]})
        self.assertEqual(blocks[2], {"type": "list", "ordered": True, "start": 1, "items": ["First", "Second continued"]})

    def test_list_survives_blank_lines_between_items(self) -> None:
        blocks = self.blocks("- one\n\n- two\n\nAfter the list.")
        self.assertEqual(blocks[0]["items"], ["one", "two"])
        self.assertEqual(blocks[1], {"type": "paragraph", "text": "After the list."})

    def test_headings_become_bold_lines(self) -> None:
        self.assertEqual(self.blocks("### Summary ###\nText"), [
            {"type": "heading", "text": "Summary"},
            {"type": "paragraph", "text": "Text"},
        ])

    def test_only_http_links_are_links(self) -> None:
        self.assertEqual(
            self.inline("[Notice](https://example.com/a?b=1)"),
            [{"type": "link", "text": "Notice", "href": "https://example.com/a?b=1"}],
        )
        for unsafe in ("[x](javascript:alert(1))", "[x](data:text/html,hi)", "[x](/relative)"):
            with self.subTest(unsafe=unsafe):
                self.assertEqual(self.inline(unsafe), [{"type": "text", "text": unsafe}])

    def test_html_stays_text(self) -> None:
        text = "<img src=x onerror=alert(1)> **<b>bold</b>**"
        nodes = self.inline(text)
        self.assertEqual(nodes[0], {"type": "text", "text": "<img src=x onerror=alert(1)> "})
        self.assertEqual(nodes[1]["children"], [{"type": "text", "text": "<b>bold</b>"}])

    def test_stray_asterisks_are_left_alone(self) -> None:
        for text in ("5 * 3 = 15", "**unclosed bold", "** spaced **"):
            with self.subTest(text=text):
                self.assertEqual(self.inline(text), [{"type": "text", "text": text}])


if __name__ == "__main__":
    unittest.main()
