"""AnalyticsEngine -- the single in-process aggregator for tool analytics.

Design invariants (see docs/ANALYTICS_PLUGIN_PLAN.md):
  * Fail-open: nothing here may raise into, block, or slow a tool call.
  * Bounded: every dimension is capped (LRU) so memory is O(caps).
  * Off hot-path: ``record`` only enqueues (O(1)); a background task drains and
    does the real work. A dual-lane queue guarantees error events are never
    dropped for success events under load.
  * Honest scope: process-local rollups are declared as such.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from .bounded import HyperLogLog, LRUMap

log = logging.getLogger("MCP_logger")

# Fixed latency histogram boundaries (ms). Percentiles are estimated from these
# buckets -- honest quantiles, never derived from a running sum (see R2).
_LAT_BUCKETS_MS = (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_NUM_BUCKETS = len(_LAT_BUCKETS_MS) + 1  # + overflow lane


def _bucket_index(ms: float) -> int:
    for i, edge in enumerate(_LAT_BUCKETS_MS):
        if ms <= edge:
            return i
    return _NUM_BUCKETS - 1


def _percentile(hist, q: float) -> float:
    """Estimate the q-quantile (0..1) from bucket counts; returns the bucket's
    upper edge in ms (overflow -> last edge)."""
    total = sum(hist)
    if total == 0:
        return 0.0
    threshold = q * total
    cum = 0
    for i, c in enumerate(hist):
        cum += c
        if cum >= threshold:
            return float(_LAT_BUCKETS_MS[i]) if i < len(_LAT_BUCKETS_MS) else float(_LAT_BUCKETS_MS[-1])
    return float(_LAT_BUCKETS_MS[-1])


def _int_env(name: str, default: int, lo: int = 1, hi: int = 10_000_000) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, default))))
    except (ValueError, TypeError):
        return default


def _float_env(name: str, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(os.environ.get(name, default))))
    except (ValueError, TypeError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AnalyticsConfig:
    enabled: bool = True
    scope: str = "process"          # process | cluster (cluster needs shared backend)
    window_seconds: int = 60
    buckets: int = 60               # -> 1h sparkline at 1min buckets
    max_tools: int = 500
    max_orgs: int = 200
    max_callers: int = 1000
    max_results: int = 1000
    result_max_bytes: int = 4096
    capture_content: bool = False   # bodies OFF by default (data governance)
    success_sample_rate: float = 0.0
    drain_interval: float = 0.25
    success_lane: int = 20_000
    error_lane: int = 2_000
    min_samples: int = 20           # suppress percentiles/trends below this
    sink: str = "memory"            # memory | jsonl
    result_ttl_seconds: int = 604800
    jsonl_path: Optional[str] = None
    redact_keys: tuple = ("token", "password", "secret", "authorization", "api_key")

    @classmethod
    def from_env(cls) -> "AnalyticsConfig":
        scope = os.environ.get("MCP_ANALYTICS_SCOPE", "process").strip().lower()
        if scope not in ("process", "cluster"):
            scope = "process"
        return cls(
            enabled=_bool_env("MCP_ANALYTICS_ENABLED", True),
            scope=scope,
            window_seconds=_int_env("MCP_ANALYTICS_WINDOW_SECONDS", 60, 1, 3600),
            buckets=_int_env("MCP_ANALYTICS_BUCKETS", 60, 2, 1440),
            max_tools=_int_env("MCP_ANALYTICS_MAX_TOOLS", 500, 1, 100_000),
            max_orgs=_int_env("MCP_ANALYTICS_MAX_ORGS", 200, 1, 100_000),
            max_callers=_int_env("MCP_ANALYTICS_MAX_CALLERS", 1000, 1, 1_000_000),
            max_results=_int_env("MCP_ANALYTICS_RESULTS_MAX", 1000, 0, 1_000_000),
            result_max_bytes=_int_env("MCP_ANALYTICS_RESULT_MAX_BYTES", 4096, 64, 1_048_576),
            capture_content=_bool_env("MCP_ANALYTICS_CAPTURE_CONTENT", False),
            success_sample_rate=_float_env("MCP_ANALYTICS_SUCCESS_SAMPLE_RATE", 0.0),
            sink=(os.environ.get("MCP_ANALYTICS_SINK", "memory").strip().lower()
                  if os.environ.get("MCP_ANALYTICS_SINK", "memory").strip().lower() in ("memory", "jsonl", "tenancy")
                  else "memory"),
            result_ttl_seconds=_int_env("MCP_ANALYTICS_RESULT_TTL_SECONDS", 604800, 60, 31_536_000),
            jsonl_path=os.environ.get("MCP_ANALYTICS_JSONL_PATH"),
            redact_keys=tuple(
                k.strip().lower() for k in
                os.environ.get("MCP_ANALYTICS_REDACT_KEYS",
                               "token,password,secret,authorization,api_key").split(",")
                if k.strip()
            ),
        )


@dataclass
class ToolRollup:
    calls: int = 0
    errors: int = 0
    dur_sum: float = 0.0
    max_ms: float = 0.0
    last_ts: float = 0.0
    error_streak: int = 0
    last_error_ts: float = 0.0
    # ring of (bucket_index -> [calls, errors]) capped to `buckets`
    series: "Deque[tuple]" = field(default_factory=lambda: deque(maxlen=60))
    # fixed latency histogram for real percentiles
    hist: List[int] = field(default_factory=lambda: [0] * _NUM_BUCKETS)


class AnalyticsEngine:
    """Single aggregator. Subscribe() wires it into the neutral observer seam."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        self.cfg = config or AnalyticsConfig()
        self._lock = threading.Lock()
        self._succ: Deque[Any] = deque(maxlen=self.cfg.success_lane)
        self._err: Deque[Any] = deque(maxlen=self.cfg.error_lane)
        self._tools: LRUMap[ToolRollup] = LRUMap(self.cfg.max_tools, ToolRollup)
        from .sink import build_sink, hmac_secret_from_env, redact, token_fingerprint
        self._sink = build_sink(self.cfg.sink, max_results=self.cfg.max_results,
                                ttl_seconds=self.cfg.result_ttl_seconds, path=self.cfg.jsonl_path)
        self._store = None   # set by attach_store() when sink == "tenancy"
        self._hmac_secret = hmac_secret_from_env()
        self._redact = redact
        self._fingerprint = token_fingerprint
        self._redact_keys = set(self.cfg.redact_keys)
        self._callers = HyperLogLog(p=10)
        self._started_at = time.time()
        self._total_calls = 0
        self._total_errors = 0
        self._attributed_calls = 0   # calls with a non-anonymous principal
        self._hour_hist = [0] * 24   # calls by UTC hour-of-day
        # caller-dimension rollups (Phase D). Bounded so a large tenant base
        # cannot OOM the process. Only populated when identity is present.
        self._orgs: LRUMap[dict] = LRUMap(self.cfg.max_orgs, lambda: {"calls": 0, "errors": 0})
        self._caller_map: LRUMap[dict] = LRUMap(
            self.cfg.max_callers, lambda: {"calls": 0, "errors": 0, "org": None, "kind": None})
        self._kinds: Dict[str, int] = {}
        # self-metrics
        self.dropped_success = 0
        self.dropped_error = 0
        self.sink_errors = 0
        self.drain_lag = 0.0
        self.breaker_open = False
        self._sink_fail_streak = 0
        self._task: Optional[asyncio.Task] = None
        self._stop = False

    # -- store attachment (reuse the tenancy DB, separate collection) ------
    def attach_store(self, store) -> None:
        """When MCP_ANALYTICS_STORE=tenancy, persist result-audit rows into the
        SAME database as tenancy (a separate ``analytics_results`` collection),
        if the store advertises the analytics capability."""
        if self.cfg.sink == "tenancy" and store is not None and hasattr(store, "append_analytics"):
            from .sink import TenancyBackedSink
            self._store = store
            self._sink = TenancyBackedSink(store, max_results=self.cfg.max_results,
                                           ttl_seconds=self.cfg.result_ttl_seconds)
            log.info("analytics: persisting to the tenancy DB (analytics_results collection)")

    @property
    def queue_depth(self) -> int:
        return len(self._succ) + len(self._err)

    # -- neutral seam ------------------------------------------------------
    def subscribe(self) -> None:
        from ..observer import subscribe
        subscribe(self.record)

    def unsubscribe(self) -> None:
        from ..observer import unsubscribe
        unsubscribe(self.record)

    # -- hot path (O(1), non-blocking, total) ------------------------------
    def record(self, event) -> None:
        """Called from the wrapper via observer.emit. Only enqueues."""
        if not self.cfg.enabled:
            return
        try:
            if event.ok:
                if len(self._succ) >= self.cfg.success_lane:
                    self.dropped_success += 1   # deque drops oldest; count it
                self._succ.append(event)
            else:
                if len(self._err) >= self.cfg.error_lane:
                    self.dropped_error += 1     # reserve existing errors: drop the new one
                    return
                self._err.append(event)
        except Exception:  # pragma: no cover - defensive
            pass

    # -- background drain --------------------------------------------------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = False
            self._task = asyncio.get_running_loop().create_task(self._drain_loop())

    async def stop(self, timeout: float = 5.0) -> None:
        """Drain-and-cancel: flush queued events (errors first) within budget."""
        self._stop = True
        with contextlib.suppress(Exception):
            self._flush_once()  # final synchronous flush so no error record is lost
        with contextlib.suppress(Exception):
            await self._flush_store()  # final durable batch-write to the store
        with contextlib.suppress(Exception):
            self._sink.close()  # rotate/persist durable sink
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._task, timeout=timeout)

    async def _drain_loop(self) -> None:
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(self.cfg.drain_interval)
            now = time.perf_counter()
            self.drain_lag = max(0.0, (now - last) - self.cfg.drain_interval)
            last = now
            with contextlib.suppress(Exception):
                self._flush_once()
            await self._flush_store()

    async def _flush_store(self) -> None:
        """Await the durable batch-write for store-backed sinks (off hot path).
        A failing store trips the same breaker; tool calls are never affected."""
        aflush = getattr(self._sink, "aflush", None)
        if aflush is None:
            return
        try:
            await aflush()
            self._sink_fail_streak = 0
        except Exception:
            self.sink_errors += 1
            self._sink_fail_streak += 1
            if self._sink_fail_streak >= 5:
                self.breaker_open = True

    def _flush_once(self) -> None:
        # errors first (they are the valuable ones), then successes
        for lane in (self._err, self._succ):
            while lane:
                try:
                    event = lane.popleft()
                except IndexError:
                    break
                self._apply(event)

    # -- aggregation (drain thread only) -----------------------------------
    def _apply(self, event) -> None:
        try:
            ms = event.duration * 1000.0
            bucket = int(event.ts // self.cfg.window_seconds)
            with self._lock:
                self._total_calls += 1
                r = self._tools.get_or_create(event.tool)
                r.calls += 1
                r.dur_sum += ms
                r.max_ms = max(r.max_ms, ms)
                r.last_ts = event.ts
                r.hist[_bucket_index(ms)] += 1
                self._hour_hist[int(event.ts // 3600) % 24] += 1
                if event.ok:
                    r.error_streak = 0
                else:
                    r.errors += 1
                    r.error_streak += 1
                    r.last_error_ts = event.ts
                    self._total_errors += 1
                # rotate time-series bucket
                if r.series and r.series[-1][0] == bucket:
                    b = r.series[-1]
                    b[1] += 1
                    if not event.ok:
                        b[2] += 1
                else:
                    r.series.append([bucket, 1, 0 if event.ok else 1])
                # caller-dimension rollups (bounded). org/kind for all traffic;
                # per-caller only for authenticated (non-anonymous) principals.
                p = event.principal
                pid = getattr(p, "principal_id", None)
                if pid:
                    self._callers.add(pid)                 # unique-caller HLL
                org = getattr(p, "org_id", None) or "unknown"
                kind = getattr(p, "kind", None) or "unknown"
                if kind in self._kinds or len(self._kinds) < 20:
                    self._kinds[kind] = self._kinds.get(kind, 0) + 1
                ob = self._orgs.get_or_create(org)
                ob["calls"] += 1
                if not event.ok:
                    ob["errors"] += 1
                subject = getattr(p, "subject", None)
                if subject and subject != "anonymous":
                    self._attributed_calls += 1
                    fp = self._fingerprint(pid, self._hmac_secret) or "unknown"
                    cb = self._caller_map.get_or_create(fp)
                    cb["calls"] += 1
                    cb["org"] = org
                    cb["kind"] = kind
                    if not event.ok:
                        cb["errors"] += 1
            if not event.ok:
                self._capture_result(event, ms)
            elif self.cfg.success_sample_rate > 0:
                import random
                if random.random() < self.cfg.success_sample_rate:
                    self._capture_result(event, ms)
        except Exception:  # pragma: no cover - drain must never die on one event
            log.debug("analytics apply failed (suppressed)", exc_info=True)

    def _capture_result(self, event, ms: float) -> None:
        """Record an audit row. Metadata always; body only if capture_content."""
        if self.cfg.max_results == 0 or self.breaker_open:
            return
        try:
            p = event.principal
            row = {
                "ts": event.ts,
                "tool": event.tool,
                "ok": event.ok,
                "duration_ms": round(ms, 3),
                "error_type": type(event.error).__name__ if event.error else None,
                "error_msg": (str(event.error)[:512] if event.error else None),
                "org_id": getattr(p, "org_id", None),
                "kind": getattr(p, "kind", None),
                "caller_fp": self._fingerprint(getattr(p, "principal_id", None), self._hmac_secret),
            }
            if self.cfg.capture_content and event.result is not None:
                excerpt = self._redact(event.result, self._redact_keys)
                row["result_excerpt"] = self._safe_excerpt(excerpt)
            self._sink.append(row)
            self._sink_fail_streak = 0
        except Exception:
            self.sink_errors += 1
            self._sink_fail_streak += 1
            if self._sink_fail_streak >= 5:
                self.breaker_open = True  # self-disable capture; metadata rollups continue

    def _safe_excerpt(self, result: Any) -> str:
        try:
            s = result if isinstance(result, str) else repr(result)
        except Exception:
            s = "<unserializable>"
        return s[: self.cfg.result_max_bytes]

    # -- runtime control ---------------------------------------------------
    def set_control(self, *, enabled: Optional[bool] = None,
                    capture_content: Optional[bool] = None) -> dict:
        if enabled is not None:
            self.cfg.enabled = bool(enabled)
        if capture_content is not None:
            self.cfg.capture_content = bool(capture_content)
        return {"enabled": self.cfg.enabled, "capture_content": self.cfg.capture_content}

    # -- read side ---------------------------------------------------------
    def get_results(self, tool: str = "", errors_only: bool = False,
                    cursor: int = 0, limit: int = 50) -> dict:
        return self._sink.query(tool=tool, errors_only=errors_only, cursor=cursor, limit=limit)

    async def query_results(self, *, org_id=None, tool: str = "", errors_only: bool = False,
                            cursor: int = 0, limit: int = 50) -> dict:
        """RBAC-scoped read. When store-backed, reads from the shared DB filtered by
        org (``org_id=None`` = all orgs, for superadmin); otherwise the sync tail."""
        aquery = getattr(self._sink, "aquery", None)
        if aquery is not None:
            return await aquery(org_id=org_id, tool=tool, errors_only=errors_only,
                                offset=cursor, limit=limit)
        return self.get_results(tool=tool, errors_only=errors_only, cursor=cursor, limit=limit)

    def get_stats(self) -> dict:
        now = time.time()
        with self._lock:
            tools = {}
            leaderboard_calls, slowest, flakiest, trending = [], [], [], []
            for name, r in self._tools.items():
                avg_ms = (r.dur_sum / r.calls) if r.calls else 0.0
                succ = max(0, r.calls - r.errors)
                rate = 100.0 if r.calls == 0 else round(succ / r.calls * 100.0, 1)
                spark = [b[1] for b in r.series]
                trend = self._trend(r.series)
                # percentiles only when the sample is big enough to be meaningful
                if r.calls >= self.cfg.min_samples:
                    pcts = {"p50_ms": _percentile(r.hist, 0.50),
                            "p95_ms": _percentile(r.hist, 0.95),
                            "p99_ms": _percentile(r.hist, 0.99)}
                else:
                    pcts = {"p50_ms": None, "p95_ms": None, "p99_ms": None}
                tools[name] = {
                    "calls": r.calls, "errors": r.errors, "successes": succ,
                    "success_rate_percent": rate,
                    "avg_latency_ms": round(avg_ms, 2),
                    "max_latency_ms": round(r.max_ms, 2),
                    **pcts,
                    "error_streak": r.error_streak,
                    "last_called_ts": r.last_ts,
                    "sparkline": spark,
                    "trend": trend,
                }
                leaderboard_calls.append((name, r.calls))
                if r.calls >= self.cfg.min_samples:
                    slowest.append((name, round(avg_ms, 2)))
                if r.calls >= self.cfg.min_samples and r.errors:
                    flakiest.append((name, round(r.errors / r.calls * 100.0, 1)))
                if trend is not None:
                    trending.append((name, trend))
            uptime = now - self._started_at
            cpm = (self._total_calls / uptime * 60.0) if uptime > 0 else 0.0
            # caller-dimension view (P10: only meaningful with real identity)
            coverage = (self._attributed_calls / self._total_calls * 100.0) if self._total_calls else 0.0
            by_org = self._top([(k, v["calls"]) for k, v in self._orgs.items()], 5)
            top_callers = self._top([(k[:12], v["calls"]) for k, v in self._caller_map.items()], 5)
            callers_block = {
                "identity_coverage_percent": round(coverage, 1),
                "attributed_calls": self._attributed_calls,
                "by_kind": dict(self._kinds),
                "by_org": by_org,
                "top_callers": top_callers,
                "orgs_tracked": len(self._orgs),
            }
            return {
                "enabled": self.cfg.enabled,
                "scope": self.cfg.scope,
                "uptime_seconds": round(uptime, 1),
                "total_calls": self._total_calls,
                "total_errors": self._total_errors,
                "calls_per_min": round(cpm, 2),
                "tools_tracked": len(self._tools),
                "unique_callers_approx": self._callers.count(),
                "hour_heatmap": list(self._hour_hist),
                "callers": callers_block,
                "tools": tools,
                "leaderboards": {
                    "most_called": self._top(leaderboard_calls, 5),
                    "slowest": self._top(slowest, 5),
                    "flakiest": self._top(flakiest, 5),
                    "trending": self._top(trending, 5),
                },
                "self": {
                    "dropped_success": self.dropped_success,
                    "dropped_error": self.dropped_error,
                    "sink_errors": self.sink_errors,
                    "drain_lag_seconds": round(self.drain_lag, 4),
                    "breaker_open": self.breaker_open,
                    "queue_depth": len(self._succ) + len(self._err),
                    "tool_evictions": self._tools.evictions,
                },
            }

    def get_timeseries(self, tool: str) -> dict:
        with self._lock:
            r = self._tools.peek(tool)
            if r is None:
                return {"tool": tool, "buckets": [], "window_seconds": self.cfg.window_seconds}
            buckets = [{"bucket": b[0], "calls": b[1], "errors": b[2]} for b in r.series]
        return {"tool": tool, "window_seconds": self.cfg.window_seconds,
                "n": sum(b["calls"] for b in buckets), "buckets": buckets}

    @staticmethod
    def _trend(series) -> Optional[float]:
        if len(series) < 2:
            return None
        prev, cur = series[-2][1], series[-1][1]
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100.0, 1)

    @staticmethod
    def _top(pairs, n):
        return [{"name": k, "value": v} for k, v in sorted(pairs, key=lambda x: x[1], reverse=True)[:n]]

    @classmethod
    def from_env(cls, ctx=None) -> "AnalyticsEngine":
        return cls(AnalyticsConfig.from_env())
