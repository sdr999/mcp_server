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

### R1 identity-propagation spike — RESOLVED (both paths)
- `test_r1_identity_reaches_wrapper_http`: boots the real app via `TestClient`,
  subscribes a capture observer, calls `/tools/echo/call` with an admin token,
  asserts the principal the wrapper sees. **Finding: identity propagates on the
  HTTP path** (`subject == "admin-token"`).
- `test_r1_identity_reaches_wrapper_mcp`: runs the app under a **real uvicorn
  server** (full ASGI middleware stack + lifespan) and drives a genuine MCP
  `tools/call` for `echo` over `/mcp` with a bearer token via the fastmcp
  `Client` + `StreamableHttpTransport`. The `/mcp` path has no `enforce()` to
  re-set the ContextVar, so this is the strict test. **Finding: identity ALSO
  propagates on the `/mcp` protocol path** (`subject == "admin-token"`).
- **Conclusion:** caller-dimension attribution is real for both HTTP and
  MCP-protocol clients. No explicit principal-threading fix is required; the
  ContextVar set by `IdentityMiddleware` reaches the tool wrapper on both paths.

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

## Phase D — caller-dimension attribution
**Commit:** _(this change)_ · **Tests:** +3 · suite 250 passed.

- `engine.py` — bounded caller rollups (LRU-capped orgs + callers, `MAX_ORGS`/
  `MAX_CALLERS`; small `by_kind` map, P6). `_apply` records org/kind for all
  traffic and per-caller (HMAC fingerprint) only for **authenticated**
  (non-anonymous) principals. `get_stats` adds a `callers` block:
  `identity_coverage_percent`, `attributed_calls`, `by_kind`, `by_org`,
  `top_callers` (opaque fp), `orgs_tracked`.
- `dashboard/templates.py` — "Caller Attribution" cards (by agent kind / by org /
  top callers) with a coverage line. **Gated (P10):** when coverage is 0 the cards
  are replaced by an explanatory note rather than shipping empty/misleading data.
- Grounded by the R1 finding: identity reaches the wrapper on the HTTP path, so
  attribution is real there. `/mcp` cluster attribution still pending an MCP-client
  verification; the `scope` badge already declares process-vs-cluster honestly.
- Tests: attribution counts + coverage, anonymous-not-attributed (gate holds),
  org dimension bounded.

**Cluster scope (shared backend) — deferred:** the `scope=cluster` shared-state
backend (Redis/store) is documented and declared but not implemented in this
increment (needs infra not available here). The honesty guard — process-scope
badge + `analytics_scope` in every payload — is shipped, so no configuration
presents partial data as global.

## Phase F (partial) — reuse the tenancy DB (same database, separate collection)
**Commit:** _(this change)_ · **Tests:** +5 · suite 257 passed.

Persist result-audit rows into the **same database as the tenancy store**, in a
**separate `analytics_results` table/collection** — never the transactional `audit`
table (review R3).
- `plugins/tenancy/memory.py`, `plugins/tenancy/sqlite_store.py`: added the
  analytics capability — `append_analytics(rows)`, `query_analytics(org_id, tool,
  errors_only, limit, offset)` (org-scoped), `purge_analytics(cutoff)`. Sqlite
  creates `analytics_results` (+ `ix_analytics_org_ts` index) in `init_db()`.
- `plugins/analytics/sink.py`: `TenancyBackedSink` — sync `append` buffers on the
  hot path; `aflush` (awaited by the drain) batch-writes durably; `aquery` reads
  back org-scoped; a bounded tail backs the sync fallback.
- `plugins/analytics/engine.py`: `attach_store(store)` swaps to the tenancy-backed
  sink when `MCP_ANALYTICS_SINK=tenancy`; the drain awaits `_flush_store` each tick
  (same breaker on failure); `query_results(org_id=…)` reads DB-scoped.
- `plugins/analytics/routes.py`: `/results` computes RBAC scope from the principal
  (superadmin → all orgs; otherwise own `org_id`; mismatched `?org=` ignored) and
  queries the store with that filter.
- `plugins/app.py`: `analytics.attach_store(tenancy_store)` after the store is built
  (no-op for the default in-proc/jsonl sinks).

**Config:** `MCP_ANALYTICS_SINK=tenancy` (reuse the tenancy DB) alongside the
existing `memory` | `jsonl`. Reuses the tenancy DSN/backend selection — so `sqlite`
today, `mongodb`/custom via the same `register_backend` mechanism.

**Live-verified:** ran the real server with `MCP_ANALYTICS_SINK=tenancy`; 3 error
rows landed in `analytics_results`, `audit` stayed at **0** — same DB, separate
collection, read back org-scoped through `/admin/analytics/results`.

**Still open in Phase F:** switch `/analytics/*` from `admin_denied` (superadmin-only)
to `enforce(analytics:read)` with the new `analytics:read`/`read_content`/`manage`
permissions seeded into roles, so `org_admin` can read its own org (scoping code is
already in place); Mongo backend method impls (pattern mirrors sqlite).

## Status vs plan
| Phase | State |
|---|---|
| 0 seam + R1 spike | ✅ (HTTP **and** `/mcp` confirmed) |
| A hardened tool-dimension analytics | ✅ |
| B percentiles + heatmap + dashboard | ✅ |
| C durable sinks + redaction + HMAC | ✅ |
| D caller-dimension cards | ✅ (HTTP + `/mcp`); cluster shared-backend deferred |
| F reuse tenancy DB (same db, separate collection) | ✅ storage + org-scoped reads (sqlite/memory); endpoint RBAC-permission switch + Mongo impl pending |
| E TSDB-native aggregation | ⬜ (specced) |

## Live end-to-end tests (from the running-server verification)
The manual live-server run (real uvicorn + admin token + genuine `/mcp` call) was
captured as automated integration tests so the behavior is regression-guarded:
- `test_live_analytics_end_to_end_http` — boots the real app via `TestClient`,
  drives 25 attributed successes + 4 real runtime errors (a raising tool) + 3
  anonymous calls, then asserts the live endpoints: `/admin/analytics/summary`
  rollups + leaderboards, caller attribution (`by_kind.service`, coverage),
  `/admin/analytics/results?errors_only` (error metadata + `caller_fp`) with
  pagination, **admin-gating** (401 without token), the **runtime kill-switch**
  (disable → new calls not recorded), and Prometheus `/metrics` cross-check.
- `test_r1_identity_reaches_wrapper_mcp` — extended to also assert the `/mcp`
  protocol calls are counted and attributed in `/admin/analytics/summary` and
  appear in `/metrics`.

## Test summary
- Analytics suite: **29 tests**, all passing.
- Full suite: **252 passed**, 1 failure (`test_telemetry_bootstrap_lifecycle`) —
  pre-existing and environmental (OpenTelemetry not installed); confirmed to fail
  with these changes stashed.

## Key decisions / guardrails honored
- No hard dependency: wrapper imports only `observer.py`; disabling the plugin
  leaves the server fully functional (tested).
- Fail-open everywhere; errors never dropped under backpressure; all dimensions
  bounded; percentiles only from buckets; token fingerprints HMAC-keyed; result
  bodies opt-in.
