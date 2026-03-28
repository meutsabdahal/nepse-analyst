import unittest

from nepse_analyst import pipeline


class PipelineContractTests(unittest.TestCase):
    def test_oos_route_contract(self) -> None:
        out = pipeline.run("Should I buy or sell NABIL right now?")
        self.assertEqual(out.get("route"), "OOS")
        self.assertIn(out.get("guardrail_type"), {"prediction", "advice"})

    def test_sql_contract_shape_with_stubs(self) -> None:
        orig_classify = pipeline.classify
        orig_generate = pipeline.generate_and_execute
        orig_llm_call = pipeline.llm.call
        try:
            pipeline.classify = lambda q: {
                "route": "SQL",
                "guardrail": None,
                "language": "en",
                "entities": {},
                "confidence": "high",
            }
            pipeline.generate_and_execute = lambda q: {
                "success": True,
                "question": q,
                "sql": "SELECT 1 AS x",
                "rows": [{"x": 1}],
                "columns": ["x"],
                "row_count": 1,
                "attempts": 1,
                "error": None,
            }
            pipeline.llm.call = lambda *a, **k: "Stubbed answer"

            out = pipeline.run("test")
            self.assertTrue(out.get("success"))
            self.assertEqual(out.get("route"), "SQL")
            self.assertTrue(out.get("sql"))
            self.assertIn("research purposes", out.get("answer", ""))
        finally:
            pipeline.classify = orig_classify
            pipeline.generate_and_execute = orig_generate
            pipeline.llm.call = orig_llm_call


if __name__ == "__main__":
    unittest.main()
