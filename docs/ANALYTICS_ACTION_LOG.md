# Analytics Plugin — Action Log

Chronological record of the tool-analytics feature built on branch `metric-up`.
Design: [`ANALYTICS_PLUGIN_PLAN.md`](ANALYTICS_PLUGIN_PLAN.md) (v2, production-grade).
Constraints carried from [`METRICS_IMPROVEMENT_PLAN.md`](METRICS_IMPROVEMENT_PLAN.md)
(review items R1–R8) and the SDE-5 production review (P1–P10).

## Branch & lineage
- Cut `metric-up` from `grade3` (which carries the plan docs).
- All work committed and pushed to `origin/metric-up`. No PR opened (not requested).

---

## Phase 0 + A — seam + hardened tool-dimension analytics
**Commit:** `954e740` · **Tests:** 15 new · suite 238 passed (1 pre-existing telemetry fail).

Files added:
- `src/plugins/observer.py` — neutral `emit()` seam + `ToolEvent`. The hot-path
  wrapper depends only on this; no-op when unsubscribed; swallows subscriber
  errors (fail-open). Idempotent `subscribe()` so hot-reload can't leak observers.
- `src/plugins/analytics/__init__.py`, `engine.py`, `bounded.py`, `routes.py`.
  - `AnalyticsEngine`: single aggregator. Dual-lane bounded queue (error events
    reserved, never dropped for successes — P4). Background drain owned by the
    lifespan with drain-and-flush on shutdown (P1). LRU-bounded tool dimension +
    HyperLogLog unique-caller estimate (P6). Rollups: calls/errors/success-rate/
    avg+max latency/error-streak. Self-metrics: queue depth, drops, drain lag,
    breaker (P7). Runtime kill-switch via `set_control` (P8). Metadata-only
    result-audit ring, bodies OFF by default (P5).
  - Fail-open contract: `record`, `_apply`, `_capture_result` all swallow; sink
    breaker self-disables capture after 5 consecutive failures (P3).

Files changed:
- `src/plugins/tool_loader.py` — one cheap `emit()` in the wrapper `finally`
  (captures ok/err/result + `get_current_principal()`), guarded by
  `contextlib.suppress` so analytics can never break a call (R6 single-count kept).
- `src/plugins/app.py` — instantiate engine, `subscribe()` once, start/stop in the
  lifespan (`app.py:241`), routes wired.
- `src/plugins/dashboard/routes.py` — defensive `analytics` block in the summary
  (`getattr(st, "analytics", None)`) — no hard dependency.

---

## Phase B — real percentiles, hour heatmap, dashboard cards
**Commit:** `f6b59d7` · **Tests:** +3 · suite 241 passed.

- `engine.py` — fixed latency histogram buckets → honest **p50/p95/p99** per tool
  (never from sum/count — R2), gated below `min_samples`. UTC **hour-of-day**
  call heatmap.
- `dashboard/templates.py` — new **"Analytics & Insights"** section: headline
  counters + self-health (queue/drops/breaker), scope badge (THIS WORKER/CLUSTER),
  leaderboards (most-called/slowest/flakiest/trending), per-tool latency+trend
  table (p50/p95/p99, ▲/▼ trend, error streak), and a by-hour heatmap strip.
  `analytics` excluded from the raw key-value dump.

---

## Phase 0 spike (R1) + Phase C — durable sinks, redaction, HMAC
**Commit:** _(this change)_ · **Tests:** +7 · suite 247 passed.

### R1 identity-propagation spike — RESOLVED
- Added `test_r1_identity_reaches_wrapper_http`: boots the real app via
  `TestClient`, subscribes a capture observer, calls `/tools/echo/call` with an
  admin token, and asserts the principal the wrapper sees.
- **Finding: identity DOES propagate to the wrapper on the HTTP path**
  (`subject == "admin-token"`). Caller-dimension metrics are therefore **viable**
  — the plan's biggest open question is answered for `/tools/{name}/call`.
- Remaining: verify the `/mcp` protocol path with an MCP client session before
  shipping caller cards cluster-wide (Phase D).

### Phase C — result-audit data plane
- `src/plugins/analytics/sink.py` (new):
  - `redact()` — recursive **key-based + value-pattern** redaction (JWT / bearer /
    api-key / long-hex), depth-capped; documented best-effort (P5).
  - `token_fingerprint()` — **HMAC-keyed** fingerprint, non-correlatable (R8).
  - `MemoryResultSink` (default, no disk) and `JsonlResultSink` (durable
    append-only + in-memory read tail + TTL rotation).
  - `build_sink()`, `hmac_secret_from_env()`.
- `engine.py` — routes capture through the configured sink; adds `caller_fp`;
  redacts result bodies when content capture is enabled; `get_results` delegates
  to the sink; sink closed/rotated on shutdown. New config
  (`MCP_ANALYTICS_SINK`, `_RESULT_TTL_SECONDS`, `_JSONL_PATH`, `_REDACT_KEYS`,
  `_HMAC_SECRET`).

Tests added: redaction (nested + value patterns), HMAC fingerprint (keyed +
stable), JSONL durability + query, content-off-by-default, results pagination.

---

## Status vs plan
| Phase | State |
|---|---|
| 0 seam + R1 spike | ✅ (HTTP path confirmed; `/mcp` still to verify) |
| A hardened tool-dimension analytics | ✅ |
| B percentiles + heatmap + dashboard | ✅ |
| C durable sinks + redaction + HMAC | ✅ |
| D cluster scope + caller-dimension cards | ⬜ (unblocked by R1 on HTTP) |

## Test summary
- Analytics suite: **24 tests**, all passing.
- Full suite: **247 passed**, 1 failure (`test_telemetry_bootstrap_lifecycle`) —
  pre-existing and environmental (OpenTelemetry not installed); confirmed to fail
  with these changes stashed.

## Key decisions / guardrails honored
- No hard dependency: wrapper imports only `observer.py`; disabling the plugin
  leaves the server fully functional (tested).
- Fail-open everywhere; errors never dropped under backpressure; all dimensions
  bounded; percentiles only from buckets; token fingerprints HMAC-keyed; result
  bodies opt-in.
