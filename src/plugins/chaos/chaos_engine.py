"""Chaos Engineering fault injection rule engine."""
from __future__ import annotations

import logging
import os
import random
import threading
from typing import Dict, Any, Optional

log = logging.getLogger("MCP_logger")


class ChaosEngine:
    """Manages active fault injection rules (synthetic latency, exception rate, HTTP status errors)."""

    def __init__(self, allow_chaos_env: bool = False):
        self._lock = threading.Lock()
        self._allow_chaos = allow_chaos_env or os.getenv("MCP_ALLOW_CHAOS", "").lower() in ("true", "1", "yes")
        self._enabled = False
        self._delay_ms: float = 0.0
        self._exception_rate: float = 0.0
        self._http_status: Optional[int] = None
        self._injections_count: int = 0

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._allow_chaos

    def enable(self) -> bool:
        if not self._allow_chaos:
            log.warning("Chaos engine enable rejected: MCP_ALLOW_CHAOS env is not set to true")
            return False
        with self._lock:
            self._enabled = True
        log.info("Chaos engine enabled")
        return True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
        log.info("Chaos engine disabled")

    def configure_rules(self, delay_ms: float = 0.0, exception_rate: float = 0.0, http_status: Optional[int] = None) -> None:
        with self._lock:
            self._delay_ms = max(0.0, float(delay_ms))
            self._exception_rate = max(0.0, min(1.0, float(exception_rate)))
            self._http_status = int(http_status) if http_status else None
        log.info("Chaos rules updated: delay_ms=%.1f, exception_rate=%.2f, http_status=%s", self._delay_ms, self._exception_rate, self._http_status)

    def should_inject_exception(self) -> bool:
        if not self.is_enabled or self._exception_rate <= 0:
            return False
        return random.random() < self._exception_rate

    def get_delay_sec(self) -> float:
        if not self.is_enabled or self._delay_ms <= 0:
            return 0.0
        return self._delay_ms / 1000.0

    def get_http_status(self) -> Optional[int]:
        if not self.is_enabled:
            return None
        return self._http_status

    def record_injection(self) -> None:
        with self._lock:
            self._injections_count += 1

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "allow_chaos_env": self._allow_chaos,
                "enabled": self._enabled and self._allow_chaos,
                "delay_ms": self._delay_ms,
                "exception_rate": self._exception_rate,
                "http_status": self._http_status,
                "total_injections": self._injections_count,
            }
