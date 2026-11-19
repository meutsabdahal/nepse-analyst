"""Per-request time budget.

``pipeline.run()`` opens a deadline for each question. While it is open, every
LLM call and SQL query gets at most the time that is left (see ``budget``), so
one question cannot hold a worker for the sum of its calls' own timeouts.
Outside a request (scripts, tests) there is no deadline and calls keep their
own limits.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# A call is not started with less time than this; it could not finish anyway.
MIN_CALL_SEC = 1.0

_expires_at: ContextVar[float | None] = ContextVar("request_deadline", default=None)


class DeadlineExceeded(TimeoutError):
    """The request's time budget ran out before a call could start."""


@contextmanager
def request_deadline(seconds: float | None) -> Iterator[None]:
    """Set a deadline ``seconds`` from now for the enclosed work.

    ``None`` or 0 means no deadline. A nested deadline can shorten the
    current one but never extend it.
    """
    current = _expires_at.get()
    new = time.monotonic() + seconds if seconds and seconds > 0 else None
    if new is None or (current is not None and current <= new):
        yield
        return
    token = _expires_at.set(new)
    try:
        yield
    finally:
        _expires_at.reset(token)


def remaining() -> float | None:
    """Seconds left before the deadline (may be negative), or None without one."""
    expires_at = _expires_at.get()
    return None if expires_at is None else expires_at - time.monotonic()


def expired() -> bool:
    left = remaining()
    return left is not None and left <= 0


def budget(cap: float, minimum: float = MIN_CALL_SEC) -> float:
    """Timeout for one call: ``cap`` cut to the time left.

    Raises ``DeadlineExceeded`` when less than ``minimum`` seconds are left.
    """
    left = remaining()
    if left is None:
        return cap
    if left < minimum:
        raise DeadlineExceeded(f"request time limit reached ({max(left, 0):.1f} s left)")
    return min(cap, left)


def sleep(seconds: float) -> None:
    """Sleep between retries, unless the deadline would pass first."""
    left = remaining()
    if left is not None and seconds >= left - MIN_CALL_SEC:
        raise DeadlineExceeded(f"request time limit reached; not waiting {seconds:g} s to retry")
    time.sleep(seconds)
