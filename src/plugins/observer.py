"""Neutral tool-execution observer seam.

This module is the decoupling boundary between the hot-path tool wrapper and any
analytics/telemetry consumer. The wrapper depends only on this tiny module -- it
never imports the analytics plugin. If nothing subscribes, ``emit`` is a near-zero
cost no-op (one list-empty check), so the feature is truly optional and carries no
hard dependency.

Contract: ``emit`` never raises, never blocks, and never does I/O. Subscribers
receive a :class:`ToolEvent` and must themselves be non-blocking and total.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

log = logging.getLogger("MCP_logger")


@dataclass
class ToolEvent:
    """A single tool execution, handed to observers from the wrapper's finally."""
    tool: str
    duration: float                       # wall-time seconds
    ok: bool
    error: Optional[BaseException] = None
    result: Any = None                    # may be captured/redacted downstream
    principal: Any = None                 # Principal or None (may be blank on /mcp)
    ts: float = 0.0                       # wall-clock; filled by emit if unset


# Module-level subscriber registry. Kept as a plain list for the cheapest possible
# "is anyone listening?" check on the hot path.
_OBSERVERS: List[Callable[[ToolEvent], None]] = []


def subscribe(fn: Callable[[ToolEvent], None]) -> None:
    """Register an observer. Idempotent: a callable is never added twice, so
    hot-reload recreating tool wrappers cannot leak duplicate subscriptions."""
    if fn not in _OBSERVERS:
        _OBSERVERS.append(fn)


def unsubscribe(fn: Callable[[ToolEvent], None]) -> None:
    try:
        _OBSERVERS.remove(fn)
    except ValueError:
        pass


def clear() -> None:
    """Drop all subscribers (test helper)."""
    _OBSERVERS.clear()


def observer_count() -> int:
    return len(_OBSERVERS)


def emit(event: ToolEvent) -> None:
    """Fan an event out to subscribers. Total and non-blocking: any subscriber
    exception is swallowed so analytics can never harm a tool call."""
    if not _OBSERVERS:
        return
    if not event.ts:
        import time
        event.ts = time.time()
    for fn in _OBSERVERS:
        try:
            fn(event)
        except Exception:  # pragma: no cover - defensive; observers must not raise
            log.debug("analytics observer raised (suppressed)", exc_info=True)
