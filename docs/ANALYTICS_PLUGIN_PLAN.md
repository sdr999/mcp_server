# Tool Analytics & Insights — Plugin Implementation Plan

**Status:** proposed · **Branch:** `grade3` · **Supersedes framing of**
[`METRICS_IMPROVEMENT_PLAN.md`](METRICS_IMPROVEMENT_PLAN.md) (keeps its as-is
analysis and the senior-architect review R1–R8 as binding constraints).

This re-plans the metrics work as a **first-class plugin with no hard dependency**,
scalable by construction, and adds engagement ("fun") metrics: per-tool usage
trends over time, leaderboards, and optional **tool-result capture for audit**
(always on error, sampled on success).

## 1. Why a plugin, and what "no hard dependency" means here

The codebase already has a proven plugin shape (`plugins/cost`, `plugins/chaos`,
`plugins/intelligence`, `plugins/prompts`): each is a package that

1. exports a registry/service class + optional middleware + a `*_routes()` fn,
2. is instantiated in `app.py` and attached to `app.state.<name>`
   (`app.py:130-140`), and
3. is read **defensively** by the dashboard via `getattr(st, "<name>", None)`
   (`dashboard/routes.py:23-40`) — if the plugin isn't wired, the feature simply
   doesn't appear. Nothing breaks.

The new `plugins/analytics/` package follows exactly this contract. "No hard
dependency" is enforced two ways:

- **Pure stdlib core.** The engine uses only `collections`, `threading`, `time`,
  `json`. OpenTelemetry and the tenancy store are *optional* backends detected at
  runtime (same pattern as `telemetry/__init__.py`'s `HAS_OTEL`).
- **A neutral emit seam.** The tool wrapper (`tool_loader.py:190-222`) must not
  import `analytics`. Instead it calls a tiny always-present module
  `plugins/observer.py::emit(event)` that fans out to a list of registered
  observers. If analytics never loads, the observer list is empty and `emit` is a
  near-zero-cost no-op. This is the decoupling seam — the hot path depends only on
  a 20-line neutral module, never on the plugin.

```
tool wrapper (tool_loader.py)
      │  emit(ToolEvent)              ← neutral seam, no-op if unsubscribed
      ▼
plugins/observer.py  ──fan-out──►  AnalyticsEngine.record()   (O(1), lock-light)
                                         │
                        ┌────────────────┼─────────────────┐
                        ▼                ▼                 ▼
                  in-mem rollups   background drain     ResultSink
                  (ring buffers)   (heavy work off      (memory | jsonl | store)
                                    hot path)
```

## 2. Package layout

```
plugins/analytics/
  __init__.py        # exports AnalyticsEngine, analytics_routes; stdlib-only
  engine.py          # AnalyticsEngine: record() + get_stats() + rollups
  timeseries.py      # bounded ring-buffer of time buckets (per tool)
  sink.py            # ResultSink interface + Memory/Jsonl/Store backends
  routes.py          # admin-gated analytics_routes()
plugins/observer.py  # neutral emit() seam + ToolEvent dataclass (no analytics import)
```

Wiring in `app.py` (mirrors `cost`/`chaos`, ~4 lines):

```python
from .analytics import AnalyticsEngine, analytics_routes
analytics = AnalyticsEngine.from_env(ctx)          # honors MCP_ANALYTICS_* flags
app.state.analytics = analytics
analytics.subscribe()                               # registers into observer.emit
for route in analytics_routes():
    app.router.routes.append(route)
```

Dashboard reads it defensively — one added line in `_build_dashboard_summary`:

```python
analytics = getattr(st, "analytics", None)
summary["analytics"] = analytics.get_stats() if analytics else {}
```

## 3. The hot-path change (single, cheap, decoupled)

In `tool_loader.py` `wrapper` `finally` block (currently `:221-222`):

```python
from .observer import emit, ToolEvent          # neutral, always importable
...
finally:
    dur = time.perf_counter() - start
    METRICS.observe("mcp_tool_duration_seconds", dur, tool=tool_name)
    emit(ToolEvent(tool=tool_name, duration=dur, ok=ok,
                   error=err, result=result if capture else None,
                   principal=get_current_principal()))   # blanks tolerated (R1)
```

`emit` does **not** serialize, redact, or write anything inline — it pushes to a
bounded queue drained by a background task. Hot path stays allocation-light.

## 4. Metrics — the fun set (and how each is computed)

Aggregates live in the analytics plane (in-memory rollups), **not** as
high-cardinality Prometheus labels (honors review R5). Because the engine keeps
time buckets, it *can* compute real percentiles (unlike sum/count — review R2).

| Insight | How it's derived | Storage |
|---|---|---|
| **Per-tool usage trend / sparkline** | ring buffer of N fixed-width time buckets (default 60×1min); last-60 points | `timeseries.py` |
| **Trending tool** (▲ biggest mover) | max positive delta in call-rate between last two windows | rollup |
| **Top-N leaderboards** | most-called · slowest (avg + p95) · flakiest (error rate) · most-improved | rollup |
| **Throughput** | rolling calls/min, busiest minute, calls-since-boot odometer | rollup |
| **Peak concurrency** | in-flight high-water mark (inc/dec around call) | gauge |
| **Reliability flavor** | current error streak per tool, last-error time, MTBF, "healthiest/most-fragile tool" | rollup |
| **Engagement** | unique-callers count (bounded set), top caller by org/agent-kind, new tools onboarded this period, "hot tool of the day" | rollup |
| **Hour-of-day heatmap** | 24-bucket call-volume histogram | ring |
| **Latency histogram** | fixed buckets → true p50/p95/p99 badge per tool | `timeseries.py` |

All of these render as dashboard cards: sparklines, trend arrows, leaderboards, a
heatmap strip, and headline "odometer" numbers.

## 5. Tool-result capture for audit (optional, safe-by-default)

`ResultSink` records tool outputs for audit — **always on error**, **sampled on
success** (default 0%, i.e. errors-only until opted in). This is *not* the RBAC
`log_audit` table (review R3): it's a separate, bounded, append-only sink.

- **Backends:** `memory` (bounded deque, default), `jsonl` (rotating file),
  `store` (reuse tenancy store if present — shared across replicas).
- **Safety rails:** per-entry byte cap (`_RESULT_MAX_BYTES`), max retained
  (`_RESULTS_MAX`), key redaction (`_REDACT_KEYS`), success sampling
  (`_SUCCESS_SAMPLE_RATE`), and **HMAC** token fingerprint — never raw tokens
  (review R8). Serialization/redaction happen on the **background drain**, never
  the hot path.
- **Record shape:** `ts, tool, ok, error_type, error_msg, duration_ms,
  org_id, kind, caller_fp, args_digest, result_excerpt`.
- **Endpoint:** `GET /admin/analytics/results?tool=&errors_only=` (admin-gated).

Errors get the richest capture (full error type/message + args digest + result if
any) so failures are debuggable after the fact.

## 6. Scalability (designed in, not bolted on)

- **Bounded memory everywhere.** Max tracked tools (LRU-evicted), max buckets per
  series, max retained results, max bytes per entry — all configurable, all with
  safe defaults. No unbounded growth regardless of traffic or tool count.
- **O(1) hot path.** `emit` → bounded `queue.Queue`; a single background drain task
  does rollups, redaction, and I/O. If the queue is full, **drop-oldest**
  (sampling) rather than block a tool call (backpressure safety).
- **Cardinality guard.** Caller/agent/result detail stays in the analytics plane;
  Prometheus labels remain low-cardinality (`tool`, `org_id`, `kind`, `reason`).
- **Horizontal scale.** In-memory rollups are per-process — documented. For a
  multi-replica deploy: aggregates come from Prometheus scrape+sum across replicas;
  the result-audit sink uses the `store` backend so it's shared. The plugin
  abstracts this behind `ResultSink`, so scaling is a config change, not a rewrite.
- **Dashboard fan-out.** Compute one analytics snapshot per SSE tick and broadcast
  to all clients instead of recomputing per client (review R7).

## 7. Configuration (all optional, conservative defaults)

| Env var | Default | Purpose |
|---|---|---|
| `MCP_ANALYTICS_ENABLED` | `true` | master switch (plugin still no-hard-dep) |
| `MCP_ANALYTICS_WINDOW_SECONDS` | `60` | time-bucket width |
| `MCP_ANALYTICS_BUCKETS` | `60` | buckets per tool (→ 1h sparkline) |
| `MCP_ANALYTICS_MAX_TOOLS` | `500` | LRU cap on tracked tools |
| `MCP_ANALYTICS_RESULTS_ENABLED` | `true` | capture results (errors-only by default) |
| `MCP_ANALYTICS_SUCCESS_SAMPLE_RATE` | `0.0` | fraction of successes captured |
| `MCP_ANALYTICS_RESULT_MAX_BYTES` | `4096` | per-entry cap |
| `MCP_ANALYTICS_RESULTS_MAX` | `1000` | retained records |
| `MCP_ANALYTICS_SINK` | `memory` | `memory` \| `jsonl` \| `store` |
| `MCP_ANALYTICS_REDACT_KEYS` | `token,password,secret,authorization,api_key` | redaction |

## 8. Endpoints (admin-gated, via `admin_denied`)

```
GET /admin/analytics/summary                 # headline cards + leaderboards
GET /admin/analytics/tools/{name}/timeseries # sparkline data for one tool
GET /admin/analytics/leaderboard?by=calls|latency|errors|trending
GET /admin/analytics/results?tool=&errors_only=true
```

## 9. Testing

- **Engine:** record/rollup correctness, ring-buffer bounds, LRU eviction,
  percentile buckets, trend delta, error-streak/MTBF.
- **Sink:** byte cap, retention cap, redaction, success sampling, **error always
  captured**, HMAC fingerprint stability.
- **Decoupling:** `emit` is a no-op when unsubscribed; wrapper never imports
  analytics; disabling the plugin leaves the server fully functional.
- **Scalability:** flood N events → assert memory caps hold; drain is async (no
  hot-path I/O); backpressure drops instead of blocking.
- **Integration:** dashboard summary includes `analytics` only when wired;
  endpoints reject non-admin. Extend `tests/test_dashboard.py`,
  `tests/test_observability.py`; add `tests/test_analytics.py`.

## 10. Phasing

| Phase | Deliverable | Risk |
|---|---|---|
| **A** | `observer.py` seam + `emit()` in wrapper + `AnalyticsEngine` (calls/errors/duration rollup) + `/summary` + dashboard cards | low — additive, no-op when off |
| **B** | `timeseries.py` sparklines + trend arrows + leaderboards + hour heatmap + p95 badges | low |
| **C** | `ResultSink` (memory) — errors-only capture + `/results` endpoint | med — privacy rails |
| **D** | `jsonl`/`store` sinks, HMAC fp, success sampling, dashboard broadcast, multi-replica docs | med — I/O + scale |

**Constraints carried from the architect review:** R2 (percentiles only from
buckets, never sum/count), R3 (separate sink, not `log_audit`), R4 (single engine
is the one aggregator — no shim drift), R5 (caller detail off Prometheus labels),
R6 (single-count errors at the wrapper), R7 (dashboard broadcast), R8 (HMAC token
fingerprint). R1 (ContextVar propagation) remains a Phase-A spike: the event
carries whatever principal is resolvable and tolerates blanks, so analytics ships
even if identity attribution needs the propagation fix first.
