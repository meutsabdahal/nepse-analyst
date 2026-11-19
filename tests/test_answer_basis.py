import unittest
from unittest.mock import patch

import app as app_module
from nepse_analyst.chat_helpers import answer_basis

PASSAGES = [{"title": f"Article {i}"} for i in range(5)]


def _result(route, success=True, sql=None, passages=None, answer_source=None):
    return {"route": route, "success": success, "sql": sql, "passages": passages or [], "answer_source": answer_source}


class AnswerBasisTests(unittest.TestCase):
    def label(self, result):
        basis = answer_basis(result)
        return basis and basis["label"]

    def test_labels_per_route(self) -> None:
        self.assertEqual(self.label(_result("SQL", sql="SELECT 1", answer_source="generated_sql")), "From the database")
        self.assertEqual(self.label(_result("SQL", sql="SELECT 1", answer_source="rule:latest_metric")), "From the database")
        self.assertEqual(self.label(_result("RAG", passages=PASSAGES)), "From 5 news articles")
        self.assertEqual(self.label(_result("RAG", passages=PASSAGES[:1])), "From 1 news article")
        self.assertEqual(
            self.label(_result("HYBRID", sql="SELECT 1", passages=PASSAGES, answer_source="generated_sql")),
            "From the database and 5 news articles",
        )
        self.assertEqual(self.label(_result("DIRECT")), "General knowledge, no data checked")
        self.assertEqual(self.label(_result("OOS")), "Declined")

    def test_hybrid_reports_only_the_half_that_answered(self) -> None:
        news_only = _result("HYBRID", sql="SELECT bad", passages=PASSAGES[:2], answer_source="generated_sql_failed")
        self.assertEqual(self.label(news_only), "From 2 news articles")
        database_only = _result("HYBRID", sql="SELECT 1", answer_source="generated_sql")
        self.assertEqual(self.label(database_only), "From the database")

    def test_failed_answers_claim_no_source(self) -> None:
        self.assertIsNone(answer_basis(_result("SQL", success=False, sql="SELECT bad", answer_source="generated_sql_failed")))
        self.assertIsNone(answer_basis(_result("RAG", success=False)))
        self.assertIsNone(answer_basis(_result("DIRECT", success=False, answer_source="timeout")))

    def test_kinds(self) -> None:
        self.assertEqual(answer_basis(_result("DIRECT"))["kind"], "general_knowledge")
        self.assertEqual(answer_basis(_result("RAG", passages=PASSAGES))["news_articles"], 5)


class ChatResponseBasisTests(unittest.TestCase):
    def test_chat_response_carries_the_basis(self) -> None:
        def fake_run(query, request_id=None):
            return {"success": True, "answer": "NEPSE is Nepal's stock exchange.", "route": "DIRECT",
                    "answer_source": "direct", "passages": [], "sql": None, "error": None}

        with patch.object(app_module, "run", side_effect=fake_run), patch.object(
            app_module, "extract_symbol_from_result", return_value=None
        ):
            payload = app_module.chat(app_module.ChatRequest(message="What is NEPSE?"))
        self.assertEqual(payload["answer_basis"]["label"], "General knowledge, no data checked")


if __name__ == "__main__":
    unittest.main()
