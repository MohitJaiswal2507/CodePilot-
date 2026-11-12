"""
In-process concurrency and per-user rate limiter for Docker sandbox executions.
Prevents authenticated users from overwhelming the host Docker daemon or CPU/RAM quotas.
"""

import time
import threading
from collections import deque
from contextlib import contextmanager
from typing import Dict, Deque, Iterator

from app.core.config import settings


class SandboxRateLimitError(Exception):
    """Raised when concurrency or sliding-window rate limits are exceeded."""

    def __init__(self, detail: str, retry_after_seconds: int = 2) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class SandboxExecutionLimiter:
    """Thread-safe concurrency and sliding-window rate guard for sandbox runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global_active: int = 0
        self._user_active: Dict[str, int] = {}
        self._user_windows: Dict[str, Deque[float]] = {}

    def reset(self) -> None:
        """Reset all active counters and rate-limit windows (primarily for tests)."""
        with self._lock:
            self._global_active = 0
            self._user_active.clear()
            self._user_windows.clear()

    @contextmanager
    def acquire(self, user_id: str) -> Iterator[None]:
        """
        Reserve both a per-user/global concurrency slot and a sliding-window quota token.
        Always releases the active concurrency slot on exit.
        """
        now = time.monotonic()
        max_global = max(1, settings.SANDBOX_MAX_CONCURRENT_EXECUTIONS)
        max_user = max(1, settings.SANDBOX_MAX_USER_CONCURRENT_EXECUTIONS)
        rate_limit = max(1, settings.SANDBOX_RATE_LIMIT_REQUESTS)
        window_seconds = max(1, settings.SANDBOX_RATE_LIMIT_WINDOW_SECONDS)

        with self._lock:
            user_active_count = self._user_active.get(user_id, 0)
            if user_active_count >= max_user:
                raise SandboxRateLimitError(
                    "Too many concurrent code executions for your account. "
                    "Please wait for an active execution to complete.",
                    retry_after_seconds=2,
                )

            if self._global_active >= max_global:
                raise SandboxRateLimitError(
                    "Code execution sandbox is currently at capacity. Please try again shortly.",
                    retry_after_seconds=2,
                )

            # Prune expired timestamps for this user's sliding window
            cutoff = now - window_seconds
            window = self._user_windows.get(user_id)
            if window is None:
                window = deque()
                self._user_windows[user_id] = window
            else:
                while window and window[0] <= cutoff:
                    window.popleft()

            if len(window) >= rate_limit:
                retry_after = int(window[0] + window_seconds - now) + 1
                raise SandboxRateLimitError(
                    f"Rate limit exceeded. Maximum {rate_limit} code executions "
                    f"per {window_seconds} seconds allowed.",
                    retry_after_seconds=max(1, retry_after),
                )

            # Atomically reserve slot and record request timestamp
            window.append(now)
            self._global_active += 1
            self._user_active[user_id] = user_active_count + 1

        try:
            yield
        finally:
            with self._lock:
                self._global_active = max(0, self._global_active - 1)
                remaining = self._user_active.get(user_id, 1) - 1
                if remaining <= 0:
                    self._user_active.pop(user_id, None)
                else:
                    self._user_active[user_id] = remaining


sandbox_limiter = SandboxExecutionLimiter()

