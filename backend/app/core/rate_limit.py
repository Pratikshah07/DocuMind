"""In-memory sliding-window rate limiter for expensive actions (upload, reprocess).

Per process: fine for a single-instance demo. Several instances would need a shared
store (e.g. Redis); see the deployment notes.
"""

import math
import threading
import time
from collections import defaultdict, deque

from starlette.requests import Request

from app.core.errors import RateLimitedError


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 3600) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        """Record an action for ``key`` or raise RateLimitedError. limit 0 disables."""
        if self.limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = math.ceil(hits[0] + self.window - now)
                raise RateLimitedError(
                    "Too many uploads from this network. "
                    f"Try again in about {math.ceil(retry_after / 60)} min.",
                    details={"retry_after_seconds": retry_after, "limit_per_hour": self.limit},
                )
            hits.append(now)


def client_ip(request: Request, *, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
