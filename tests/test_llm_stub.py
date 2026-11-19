import unittest
from unittest.mock import patch

from nepse_analyst import llm
from tests.llm_stub import echo_llm


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"response": "from the provider"}


class EchoStubTests(unittest.TestCase):
    def test_stub_echoes_the_quoted_text(self) -> None:
        self.assertEqual(echo_llm("Say 'OK' and nothing else."), "OK")
        self.assertEqual(echo_llm('say "pong" and nothing else'), "pong")

    def test_stub_rejects_other_prompts(self) -> None:
        with self.assertRaises(AssertionError):
            echo_llm("Which bank has the highest EPS?")

    def test_stub_can_replace_llm_call(self) -> None:
        with patch.object(llm, "call", side_effect=echo_llm):
            self.assertEqual(llm.call("Say 'ready' and nothing else"), "ready")


class NoProductionShortcutTests(unittest.TestCase):
    def test_echo_shaped_prompts_go_to_the_provider(self) -> None:
        with patch.object(llm, "LLM_PROVIDER", "ollama"), patch("requests.post", return_value=_Response()) as post:
            answer = llm.call("Say 'x' and nothing else")
        self.assertEqual(answer, "from the provider")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["prompt"], "Say 'x' and nothing else")


if __name__ == "__main__":
    unittest.main()
