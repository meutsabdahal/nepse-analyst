"""Stage reports for a question in progress.

``pipeline.run()`` calls ``report(stage, language)`` as it moves from
understanding the question to querying the database or searching news and then
writing the answer. The streaming chat endpoint installs a listener with
``reporting()`` and forwards each stage to the browser; with no listener (the
plain endpoint, scripts, tests) a report does nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from nepse_analyst.messages import message

UNDERSTANDING = "understanding"
QUERYING_DATABASE = "querying_database"
SEARCHING_NEWS = "searching_news"
WRITING_ANSWER = "writing_answer"

# stage -> its label in the message table
_LABELS = {
    UNDERSTANDING: "stage_understanding",
    QUERYING_DATABASE: "stage_querying_database",
    SEARCHING_NEWS: "stage_searching_news",
    WRITING_ANSWER: "stage_writing_answer",
}
STAGES = tuple(_LABELS)

Listener = Callable[[str, str], None]

_listener: ContextVar[Listener | None] = ContextVar("progress_listener", default=None)


@contextmanager
def reporting(listener: Listener) -> Iterator[None]:
    """Send every ``report(stage, label)`` in the enclosed work to ``listener``."""
    token = _listener.set(listener)
    try:
        yield
    finally:
        _listener.reset(token)


def stage_label(stage: str, language: str) -> str:
    return message(_LABELS[stage], language)


def report(stage: str, language: str = "en") -> None:
    """Announce that the question has reached ``stage``; never raises."""
    listener = _listener.get()
    if listener is None:
        return
    try:
        listener(stage, stage_label(stage, language))
    except Exception:  # progress is best-effort; it must not break an answer
        pass
