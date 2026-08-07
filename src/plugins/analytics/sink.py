"""Result-audit sinks + data-governance helpers.

A ResultSink stores per-call audit rows, kept SEPARATE from the RBAC audit table
(review R3). Content capture is opt-in; when on, values pass through layered
redaction (key-based + value-pattern) and token fingerprints are HMAC-keyed so
they cannot be dictionary-correlated (review R8).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger("MCP_logger")

# Secret-shaped value patterns (best-effort; documented as such).
_VALUE_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),   # JWT
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),              # bearer token
    re.compile(r"sk-[A-Za-z0-9]{16,}"),                            # api key style
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),                           # long hex secret
]


def redact(obj: Any, keys: set, depth: int = 0) -> Any:
    """Recursively redact by key name and by secret-shaped value. Best-effort."""
    if depth > 6:
        return "<max-depth>"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in keys:
                out[k] = "***"
            else:
                out[k] = redact(v, keys, depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, keys, depth + 1) for v in obj][:100]
    if isinstance(obj, str):
        s = obj
        for pat in _VALUE_PATTERNS:
            s = pat.sub("***", s)
        return s
    return obj


def token_fingerprint(value: Optional[str], secret: bytes) -> Optional[str]:
    """Keyed (HMAC) fingerprint -- opaque and non-correlatable, unlike a plain hash."""
    if not value:
        return None
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


class MemoryResultSink:
    """Bounded in-memory ring. Default sink -- no disk, no dependency."""

    def __init__(self, max_results: int = 1000):
        self._rows: Deque[dict] = deque(maxlen=max(0, max_results))
        self._lock = threading.Lock()

    def append(self, row: dict) -> None:
        with self._lock:
            self._rows.append(row)

    def query(self, tool: str = "", errors_only: bool = False,
              cursor: int = 0, limit: int = 50) -> dict:
        with self._lock:
            rows = list(self._rows)
        return _page(rows, tool, errors_only, cursor, limit)

    def close(self) -> None:  # symmetry with JsonlResultSink
        pass


class JsonlResultSink:
    """Durable append-only JSONL sink with TTL rotation + a bounded read tail.

    Writes survive restarts (durability); reads come from an in-memory tail so the
    admin endpoint never scans a large file. TTL drops rows older than the window.
    """

    def __init__(self, path: str, max_results: int = 1000, ttl_seconds: int = 604800):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tail: Deque[dict] = deque(maxlen=max(1, max_results))
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._writes = 0

    def append(self, row: dict) -> None:
        with self._lock:
            self._tail.append(row)
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, default=str) + "\n")
                self._writes += 1
                if self._writes % 500 == 0:
                    self._rotate_locked()
            except Exception:
                # durability is best-effort; the in-memory tail still serves reads
                log.debug("analytics jsonl write failed (suppressed)", exc_info=True)
                raise  # let the engine's breaker count this

    def _rotate_locked(self) -> None:
        cutoff = time.time() - self._ttl
        try:
            if not self._path.exists():
                return
            kept = []
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        if json.loads(line).get("ts", 0) >= cutoff:
                            kept.append(line)
                    except Exception:
                        continue
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text("".join(kept), encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            log.debug("analytics jsonl rotation failed (suppressed)", exc_info=True)

    def query(self, tool: str = "", errors_only: bool = False,
              cursor: int = 0, limit: int = 50) -> dict:
        cutoff = time.time() - self._ttl
        with self._lock:
            rows = [r for r in self._tail if r.get("ts", 0) >= cutoff]
        return _page(rows, tool, errors_only, cursor, limit)

    def close(self) -> None:
        with self._lock:
            self._rotate_locked()


class TenancyBackedSink:
    """Persists result-audit rows into the SAME database as the tenancy store,
    in a SEPARATE ``analytics_results`` collection/table. Sync ``append`` buffers
    on the hot path; ``aflush`` (awaited by the engine drain) batch-writes durably;
    ``aquery`` reads back org-scoped for RBAC. A bounded in-memory tail backs the
    sync ``query`` fallback so nothing on the read path blocks."""

    def __init__(self, store, max_results: int = 1000, ttl_seconds: int = 604800):
        self._store = store
        self._buffer: Deque[dict] = deque()
        self._tail: Deque[dict] = deque(maxlen=max(1, max_results))
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def append(self, row: dict) -> None:
        with self._lock:
            self._buffer.append(row)
            self._tail.append(row)

    async def aflush(self) -> None:
        with self._lock:
            batch = list(self._buffer)
            self._buffer.clear()
        if batch:
            await self._store.append_analytics(batch)   # durable, shared DB

    def query(self, tool: str = "", errors_only: bool = False,
              cursor: int = 0, limit: int = 50) -> dict:
        with self._lock:
            rows = list(self._tail)
        return _page(rows, tool, errors_only, cursor, limit)

    async def aquery(self, *, org_id=None, tool: str = "", errors_only: bool = False,
                     offset: int = 0, limit: int = 50) -> dict:
        return await self._store.query_analytics(
            org_id=org_id, tool=tool, errors_only=errors_only, limit=limit, offset=offset)

    def close(self) -> None:
        pass


def _page(rows: List[dict], tool: str, errors_only: bool, cursor: int, limit: int) -> dict:
    if tool:
        rows = [r for r in rows if r.get("tool") == tool]
    if errors_only:
        rows = [r for r in rows if not r.get("ok")]
    rows = list(reversed(rows))  # newest first
    cursor = max(0, cursor)
    limit = max(1, min(500, limit))
    page = rows[cursor:cursor + limit]
    nxt = cursor + limit if cursor + limit < len(rows) else None
    return {"total": len(rows), "cursor": cursor, "next_cursor": nxt, "results": page}


def build_sink(kind: str, *, max_results: int, ttl_seconds: int, path: Optional[str]):
    if kind == "jsonl":
        p = path or os.environ.get("MCP_ANALYTICS_JSONL_PATH", "logs/analytics_results.jsonl")
        return JsonlResultSink(p, max_results=max_results, ttl_seconds=ttl_seconds)
    return MemoryResultSink(max_results=max_results)


def hmac_secret_from_env() -> bytes:
    s = os.environ.get("MCP_ANALYTICS_HMAC_SECRET")
    if s:
        return s.encode("utf-8")
    # Per-process ephemeral secret: fingerprints stay stable within a process and
    # are non-correlatable across restarts. Set the env var for cross-process stability.
    return os.urandom(32)
