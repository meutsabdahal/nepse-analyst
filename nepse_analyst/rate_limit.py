"""In-process, per-client rate limiting for the chat endpoint.

A sliding-window log: each client keeps the timestamps of its recent allowed
requests, and a request is refused when any window is full. Refused requests
are not recorded, so a client that keeps retrying is not locked out longer.

State lives in this process only. With several workers or instances, each
keeps its own counts (the effective limit is multiplied by their number);
use a shared store such as Redis, or limit at the proxy, for that setup.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence


class SlidingWindowLimiter:
    def __init__(
        self,
        limits: Sequence[tuple[int, float]],
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = 10_000,
    ) -> None:
        """``limits`` holds (max_requests, window_seconds) pairs; a 0 count disables that pair."""
        self.limits = tuple((count, window) for count, window in limits if count > 0 and window > 0)
        self._clock = clock
        self._max_clients = max_clients
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._longest = max((window for _, window in self.limits), default=0.0)
        self._keep = max((count for count, _ in self.limits), default=0)

    def hit(self, key: str) -> float | None:
        """Record a request for ``key``. Returns None if allowed, else seconds until a retry can succeed."""
        if not self.limits:
            return None
        with self._lock:
            now = self._clock()
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self._max_clients:
                    self._prune(now)
                events = self._events[key] = deque(maxlen=self._keep)
            retry_after = 0.0
            for count, window in self.limits:
                in_window = [t for t in events if t > now - window]
                if len(in_window) >= count:
                    # The oldest request still counted must leave the window first.
                    retry_after = max(retry_after, in_window[-count] + window - now)
            if retry_after > 0:
                return retry_after
            events.append(now)
            return None

    def _prune(self, now: float) -> None:
        """Drop clients with no request inside the longest window."""
        idle = [k for k, ev in self._events.items() if not ev or ev[-1] <= now - self._longest]
        for k in idle:
            del self._events[k]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def retry_after_header(seconds: float) -> str:
    return str(max(1, math.ceil(seconds)))
