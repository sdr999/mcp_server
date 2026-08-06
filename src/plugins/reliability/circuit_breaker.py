"""3-state Circuit Breaker pattern.

Adapted directly from Horus agent-tracer-plus storage/resilience.py.
Implements CLOSED -> OPEN -> HALF_OPEN state transitions to prevent cascading failures.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("MCP_logger")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Raised when a request is rejected because the circuit is OPEN."""


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
        name: str = "upstream",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    def _should_attempt_reset(self) -> bool:
        if self._opened_at is None:
            return False
        return (time.monotonic() - self._opened_at) >= self.recovery_timeout

    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    log.info("[CircuitBreaker:%s] Recovery confirmed -> returning to CLOSED", self.name)
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    self._opened_at = None

    async def _on_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0

            if self._state == CircuitState.HALF_OPEN:
                log.warning(
                    "[CircuitBreaker:%s] Recovery probe failed (%s) -> reopening circuit",
                    self.name, exc
                )
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    log.error(
                        "[CircuitBreaker:%s] %d consecutive failures -> opening circuit for %.1fs",
                        self.name, self._failure_count, self.recovery_timeout
                    )
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()

    async def call(self, coro_func: Callable, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    log.info("[CircuitBreaker:%s] Attempting recovery probe (HALF_OPEN)", self.name)
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                else:
                    remaining = self.recovery_timeout - (time.monotonic() - (self._opened_at or 0))
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN. Recovery in ~{remaining:.1f}s"
                    )

        try:
            result = await coro_func(*args, **kwargs)
            await self._on_success()
            return result
        except CircuitBreakerOpenError:
            raise
        except Exception as exc:
            await self._on_failure(exc)
            raise

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        log.info("[CircuitBreaker:%s] Manually reset to CLOSED", self.name)

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "opened_at": self._opened_at,
        }


class CircuitBreakerRegistry:
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> CircuitBreaker:
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    name=name,
                )
            return self._breakers[name]

    def all_stats(self) -> Dict[str, Dict[str, Any]]:
        return {name: cb.stats() for name, cb in self._breakers.items()}
