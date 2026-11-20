"""Thumbs up / down ratings on answers, saved as evaluation data.

When an answer is sent, ``remember`` keeps what was asked and answered under
its request ID, in memory and for the most recent answers only. A rating is
accepted only for a remembered answer, so the server never records content it
did not produce, and it is appended to a JSON Lines file with that question
and answer, so each line stands on its own as an evaluation example. Unrated
answers are never written to disk, and nothing identifies who rated.

Ratings are events: changing or clearing a rating appends a new line, and the
latest line for a request ID is the current rating (see ``latest_ratings``).

Answers are remembered per process: after a restart, or on another worker,
older answers can no longer be rated.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RATINGS = ("up", "down", "none")  # "none" clears an earlier rating


def answer_record(query: str, response: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """What a rating is saved with: the question, the answer and how it was made."""
    basis = response.get("answer_basis") or {}
    passages = (response.get("sources") or {}).get("passages") or []
    return {
        "question": query,
        "answer": response.get("answer"),
        "route": response.get("route"),
        "answer_source": result.get("answer_source"),
        "answer_basis": basis.get("kind"),
        "query_language": response.get("query_language"),
        "success": response.get("success"),
        "error": response.get("error"),
        "sql": result.get("sql"),
        "sources": [{"title": p.get("title"), "url": p.get("url"), "published_at": p.get("published_at")}
                    for p in passages],
        "answered_at": response.get("timestamp"),
    }


class FeedbackStore:
    def __init__(self, path: str | Path, max_answers: int = 2000) -> None:
        self.path = Path(path)
        self._max_answers = max(1, max_answers)
        self._answers: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def remember(self, request_id: str, record: dict[str, Any]) -> None:
        """Keep an answer so it can be rated; the oldest is forgotten past ``max_answers``."""
        with self._lock:
            self._answers[request_id] = record
            self._answers.move_to_end(request_id)
            while len(self._answers) > self._max_answers:
                self._answers.popitem(last=False)

    def rate(self, request_id: str, rating: str) -> bool:
        """Save a rating for a remembered answer. False when the answer is not remembered."""
        if rating not in RATINGS:
            raise ValueError(f"rating must be one of {RATINGS}")
        with self._lock:
            record = self._answers.get(request_id)
            if record is None:
                return False
            line = {
                "request_id": request_id,
                "rating": rating,
                "rated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **record,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return True


def latest_ratings(lines: Iterable[str]) -> dict[str, dict[str, Any]]:
    """The current rating per request ID from a ratings file; cleared ratings are left out."""
    latest: dict[str, dict[str, Any]] = {}
    for line in lines:
        if line.strip():
            entry = json.loads(line)
            latest[entry["request_id"]] = entry
    return {request_id: entry for request_id, entry in latest.items() if entry["rating"] != "none"}
