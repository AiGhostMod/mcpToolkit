from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any


def should_record_request(path: str) -> bool:
    if path == "/healthz":
        return False
    if path == "/dashboard":
        return False
    if path.startswith("/api/"):
        return False
    return True


class CallHistory:
    def __init__(self, *, limit: int) -> None:
        self._limit = limit
        self._calls: deque[dict[str, Any]] = deque(maxlen=limit)
        self._lock = Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._calls.appendleft(entry)

    def recent(self, count: int) -> list[dict[str, Any]]:
        requested = max(1, min(count, self._limit))
        with self._lock:
            return list(self._calls)[:requested]

    def by_id(self, call_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._calls:
                if item["callId"] == call_id:
                    return item
        return None

    def length(self) -> int:
        with self._lock:
            return len(self._calls)

