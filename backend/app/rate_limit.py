"""Small in-process fixed-window limiter for expensive public endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._next_cleanup = 0.0

    def allow(self, route: str, client_id: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        key = (route, client_id)
        with self._lock:
            if now >= self._next_cleanup:
                cutoff = now - window_seconds
                stale_keys = [event_key for event_key, values in self._events.items() if not values or values[-1] <= cutoff]
                for stale_key in stale_keys:
                    del self._events[stale_key]
                self._next_cleanup = now + window_seconds
            events = self._events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True
