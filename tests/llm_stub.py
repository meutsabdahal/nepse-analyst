"""Test stand-in for ``nepse_analyst.llm.call``.

Answers echo prompts ("Say 'x' and nothing else") with ``x`` and fails the
test on anything else, so a test using it cannot reach a real provider by
accident. Patch it in where a test needs a predictable LLM:

    with patch("nepse_analyst.llm.call", side_effect=echo_llm): ...
"""

from __future__ import annotations

import re

_ECHO = re.compile(r"\s*Say\s+['\"](.+?)['\"]\s+and\s+nothing\s+else\.?\s*", re.IGNORECASE)


def echo_llm(prompt: str, system: str = "", temperature: float = 0.0, max_timeout_sec: float | None = None) -> str:
    match = _ECHO.fullmatch(prompt)
    if not match:
        raise AssertionError(f"echo_llm received a prompt it does not stub: {prompt[:80]!r}")
    return match.group(1)
