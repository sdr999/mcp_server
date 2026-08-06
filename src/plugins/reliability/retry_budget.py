"""OTel-native retry budget tracker."""
from __future__ import annotations

import collections
import time
from dataclasses import dataclass
from typing import Deque, Tuple


@dataclass
class RetryBudgetConfig:
    max_retry_ratio: float = 0.2
    window_sec: float = 60.0
    min_retries_per_window: int = 3


class RetryBudget:
    def __init__(self, config: Optional[RetryBudgetConfig] = None):
        self.config = config or RetryBudgetConfig()
        self._history: Deque[Tuple[float, bool]] = collections.deque()  # (timestamp, is_retry)

    def record_attempt(self, is_retry: bool = False) -> None:
        now = time.monotonic()
        self._history.append((now, is_retry))
        self._evict_old(now)

    def can_retry(self) -> bool:
        now = time.monotonic()
        self._evict_old(now)

        if not self._history:
            return True

        total_calls = len(self._history)
        retry_calls = sum(1 for _, is_retry in self._history if is_retry)

        if retry_calls < self.config.min_retries_per_window:
            return True

        current_ratio = retry_calls / max(1, total_calls)
        return current_ratio <= self.config.max_retry_ratio

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.config.window_sec
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
