"""Sliding-window per-tenant Rate Limiter.

Adapted from Horus agent-tracer-plus budget/enforcer.py. Supports per-minute rate limits,
per-tenant isolation, and automated periodic eviction of stale tenant keys (H3 fix).
"""
from __future__ import annotations

import asyncio
import collections
import logging
import time
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

log = logging.getLogger("MCP_logger")


class RateLimitExceededError(Exception):
    """Raised when a tenant crosses their per-minute rate limit."""
    def __init__(self, message: str, reset_in: float = 60.0):
        super().__init__(message)
        self.reset_in = reset_in


@dataclass
class RateLimitConfig:
    max_requests_per_minute: Optional[int] = 600
    max_tool_calls_per_minute: Optional[int] = 100
    on_exceed: str = "reject"  # "reject" | "alert" | "log"
    tenant_id: str = ""


@dataclass
class _WindowEntry:
    timestamp: float
    count: int = 1


class RateLimitEnforcer:
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._window: Dict[str, Deque[_WindowEntry]] = collections.defaultdict(collections.deque)
        self._last_accessed: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, tenant_id: str = "", cost: int = 1) -> Tuple[bool, int, float]:
        """Check sliding-window rate limit for tenant_id.

        Returns (allowed: bool, remaining_tokens: int, reset_in_seconds: float).
        Raises RateLimitExceededError if on_exceed == 'reject' and limit crossed.
        """
        max_rpm = self.config.max_requests_per_minute
        if max_rpm is None:
            return True, 999999, 0.0

        key = tenant_id or self.config.tenant_id or "__global__"
        now = time.monotonic()
        window_start = now - 60.0

        async with self._lock:
            self._last_accessed[key] = now
            window = self._window[key]

            # Evict entries older than 60 seconds
            while window and window[0].timestamp < window_start:
                window.popleft()

            current_usage = sum(e.count for e in window)
            remaining = max(0, max_rpm - current_usage)

            if current_usage + cost > max_rpm:
                reset_in = max(1.0, 60.0 - (now - window[0].timestamp)) if window else 60.0
                msg = f"Rate limit exceeded for tenant '{key}': {current_usage + cost}/min > {max_rpm}/min"
                if self.config.on_exceed == "reject":
                    log.warning(msg)
                    raise RateLimitExceededError(msg, reset_in=reset_in)
                elif self.config.on_exceed == "alert":
                    log.warning("ALERT: %s", msg)
                else:
                    log.info(msg)
                return False, 0, reset_in

            # Record usage
            window.append(_WindowEntry(timestamp=now, count=cost))
            remaining = max(0, max_rpm - (current_usage + cost))
            return True, remaining, 60.0

    async def get_usage_stats(self, tenant_id: str = "") -> Dict[str, Any]:
        key = tenant_id or self.config.tenant_id or "__global__"
        now = time.monotonic()
        window_start = now - 60.0

        async with self._lock:
            window = self._window.get(key, collections.deque())
            recent = [e for e in window if e.timestamp >= window_start]
            used = sum(e.count for e in recent)

        max_rpm = self.config.max_requests_per_minute or 600
        return {
            "tenant_id": key,
            "used_requests_1m": used,
            "max_requests_per_minute": max_rpm,
            "remaining_requests": max(0, max_rpm - used),
        }

    async def evict_stale_tenants(self, max_idle_sec: float = 600.0) -> int:
        """Evicts tenant windows that have been idle for longer than max_idle_sec (H3 fix)."""
        now = time.monotonic()
        evicted = 0

        async with self._lock:
            stale_keys = [
                k for k, last in self._last_accessed.items()
                if (now - last) >= max_idle_sec or not self._window[k]
            ]
            for k in stale_keys:
                self._window.pop(k, None)
                self._last_accessed.pop(k, None)
                evicted += 1

        if evicted > 0:
            log.info("RateLimiter evicted %d stale tenant buckets", evicted)
        return evicted



class RateLimiterRegistry:
    def __init__(self, default_config: Optional[RateLimitConfig] = None):
        self.default_config = default_config or RateLimitConfig()
        self.enforcer = RateLimitEnforcer(self.default_config)
        self._cleanup_task: Optional[asyncio.Task] = None

    def start_cleanup_task(self, interval_sec: float = 300.0) -> None:
        try:
            loop = asyncio.get_running_loop()
            self._cleanup_task = loop.create_task(self._periodic_eviction(interval_sec))
        except RuntimeError:
            pass

    async def _periodic_eviction(self, interval_sec: float) -> None:
        while True:
            try:
                await asyncio.sleep(interval_sec)
                await self.enforcer.evict_stale_tenants()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Periodic tenant eviction error: %s", exc)

    def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
