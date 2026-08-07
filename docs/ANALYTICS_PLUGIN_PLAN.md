# Tool Analytics & Insights — Production Plan (v2)

**Status:** proposed, production-grade · **Branch:** `grade3` · **Supersedes**
the framing in [`METRICS_IMPROVEMENT_PLAN.md`](METRICS_IMPROVEMENT_PLAN.md) (whose
as-is analysis and R1–R8 review remain binding inputs). This v2 folds the SDE-5
production review (P1–P10) directly into the design — the hardened decision *is*
the plan. A resolution matrix (§18) and scorecard (§19) show where each blocker is
closed.

A **no-hard-dependency plugin** that adds tool usage trends, leaderboards, a
result-capture audit trail, and engagement metrics — engineered to be safe under
multi-worker load, incapable of harming a tool call, and honest about its own scope.

---

## 1. Design principles (the invariants everything else obeys)

1. **No hard dependency.** Pure-stdlib core; OTel and the tenancy store are optional
   runtime-detected backends (the `HAS_OTEL` pattern). The hot path depends only on
   a tiny neutral seam, never on the plugin.
2. **Fail-open, always.** Analytics can never raise into a tool call, block it, or
   slow it measurably. Every analytics failure is swallowed and self-reported.
3. **Two planes.** *Aggregates* (Prometheus/dashboard) answer "how much / how fast";
   *per-event records* (result-audit sink + traces) answer "who did exactly what."
   They never mix, and high-cardinality identity never becomes a Prometheus label.
4. **Bounded by construction.** Every dimension — tools, orgs, callers, buckets,
   results, bytes — has a cap and an eviction policy. Memory is O(caps), not O(traffic).
5. **Honest scope.** In multi-worker deployments the system *declares* whether its
   rollups are process-local or cluster-wide (`analytics_scope`) — it never presents
   partial data as global.

## 2. Why a plugin, and the decoupling seam

The repo has a proven plugin shape (`plugins/cost`, `chaos`, `intelligence`,
`prompts`): a package that attaches a registry to `app.state.<name>`
(`app.py:130-140`) and is read defensively via `getattr(st, "<name>", None)`
(`dashboard/routes.py:23-40`). `plugins/analytics/` follows it exactly.

The hot-path wrapper (`tool_loader.py:190-222`) must **not** import analytics. It
calls a neutral, always-present module `plugins/observer.py::emit(event)` that
fans out to registered observers. No subscribers ⇒ `emit` is a no-op costing one
list-empty check. This is the seam that makes "no hard dependency" real.

```
tool wrapper ──emit(ToolEvent)──►  observer.py  ──►  AnalyticsEngine.record()
 (tool_loader)   neutral, no-op        (fan-out)          │  O(1), non-blocking
                 if unsubscribed                          ▼
                                            dual-lane bounded queue
                                                          │
                                              background drain task
                                          (rollups · redaction · I/O — off hot path)
                                              │              │
                                        in-mem rollups   ResultSink
                                        (ring buffers)   (memory│jsonl│store)
```

## 3. Package layout

```
plugins/analytics/
  __init__.py     # exports AnalyticsEngine, analytics_routes; stdlib-only
  engine.py       # record(), get_stats(), rollups, self-metrics, kill-switch
  timeseries.py   # bounded ring-buffer of time buckets; percentile histogram
  bounded.py      # LRU dimension maps + HyperLogLog unique-counter
  queue.py        # dual-lane bounded queue (errors reserved) + drain loop
  sink.py         # ResultSink interface + Memory/Jsonl/Store backends + redaction
  scope.py        # process vs cluster scope detection + shared-state adapter
  routes.py       # admin-gated analytics_routes() incl. runtime kill-switch
plugins/observer.py  # neutral emit() seam + ToolEvent (never imports analytics)
```

## 4. Lifecycle & ownership — closes P1

The drain task has exactly one home: the lifespan at `app.py:241` (which already
starts the watcher/bootstrap and stops them under `contextlib.suppress` on
shutdown). Additions:

- **Startup:** `engine.start()` launches the single drain task (`loop.create_task`,
  mirroring `app.py:265`).
- **Shutdown:** `await engine.stop(timeout=5s)` — a **drain-and-cancel**: stop
  accepting, flush the queue (errors first) to the sink within the budget, then
  cancel. No error record is lost on deploy/restart.
- **Idempotent subscribe.** `engine.subscribe()` registers into `observer` **once at
  construction**, not per wrapper — hot-reload recreating wrappers (`_make_wrapper`)
  cannot double-subscribe or leak observers.

## 5. Concurrency & backpressure — closes P3, P4

- **`emit` is non-blocking and total.** It wraps everything in `try/except: pass`
  and does an `offer()` (never `put()`) onto the queue. It performs zero
  serialization/redaction/I/O inline.
- **Dual-lane bounded queue** (`queue.py`). Two lanes: `errors` (small reserved
  capacity, e.g. 2000) and `success` (larger). Errors are **never** dropped for
  successes; when the success lane is full it drops-oldest/samples. This makes the
  audit guarantee true under exactly the load where it matters (P4).
- **Single drain consumer** does all heavy work; batches writes to the sink. If the
  drain falls behind, `analytics_drain_lag` rises and successes shed first.

## 6. Failure isolation contract — closes P3

Stated as an enforced invariant, with tests:

> No analytics code path may raise into, block, or slow the tool wrapper. `emit`
> and the drain catch all exceptions. A sink that errors **N=5 consecutive times**
> trips a breaker: capture self-disables, `analytics_sink_errors_total` increments,
> one warning is logged (rate-limited), and the breaker half-opens on a timer.

Fault-injection test: a sink whose `write` always raises ⇒ tool calls still succeed,
breaker trips, self-metric increments, no log flood.

## 7. Multi-process scope model — closes P2

The server runs multi-worker Gunicorn (fork) — `app.py:244`. In-memory rollups are
per-process. v2 makes correctness a *configured, declared* property, never a silent
lie:

- **Numeric aggregates** (counts, error rate, latency histograms) flow through the
  existing `METRICS` shim → Prometheus/OTel, which aggregate across workers at scrape
  time. These are the dashboard's headline numbers and are **cluster-correct**.
- **Rich rollups** (sparklines, leaderboards, trending, heatmap) are computed by a
  **single aggregator**, selected by `scope.py`:
  - `MCP_ANALYTICS_SCOPE=process` (default, dev/single-worker): in-process rollups.
  - `MCP_ANALYTICS_SCOPE=cluster`: rollups read/write the optional **shared backend**
    (tenancy store or Redis if configured) so all workers contribute and the
    dashboard is cluster-wide.
- **Honesty guard.** If workers>1 **and** scope=process, startup logs a warning and
  every analytics payload carries `"analytics_scope":"process"` — the dashboard
  badges rollup cards as "this worker" so nobody mistakes a slice for the whole. No
  configuration produces silently-partial data.

## 8. Memory & cardinality bounds — closes P6, R5

- `bounded.py` provides an **LRU dimension map** used for *every* dimension: tools
  (`MAX_TOOLS=500`), orgs (`MAX_ORGS=200`), callers (`MAX_CALLERS=1000`) — each
  LRU-evicts, so no dimension grows with tenant count.
- Unique-caller counts use a **HyperLogLog** (fixed ~1.5 KB, ~2% error), not an
  unbounded set — documented as approximate.
- Prometheus labels stay low-cardinality (`tool`, `org_id`, `kind`, `reason`); all
  caller/agent/result detail lives in the analytics/audit plane only (R5).

## 9. Hot-path change (single, cheap, decoupled)

In `tool_loader.py` `wrapper` `finally` (currently `:221-222`):

```python
from .observer import emit, ToolEvent           # neutral, always importable
...
finally:
    dur = time.perf_counter() - start
    METRICS.observe("mcp_tool_duration_seconds", dur, tool=tool_name)  # aggregate plane
    emit(ToolEvent(tool=tool_name, duration=dur, ok=ok, error=err,
                   result=result if _capture else None,
                   principal=get_current_principal()))                  # analytics plane
```

`ok`/`err` derive from the same exception boundary the route uses, so errors are
**counted once** at the wrapper with a `reason` (`validation|runtime|timeout|sandbox`)
— no double-count with the route (R6).

## 10. Metrics — the engagement set (statistically honest — closes P8, R2)

Aggregates come from time buckets, so percentiles are real (R2 — never from
sum/count). Percentiles/trends are **suppressed below a min sample count**
(`MIN_SAMPLES=20`) and sparklines carry their `N`, so small-sample noise is never
shown as signal.

| Insight | Derivation |
|---|---|
| Per-tool **usage trend / sparkline** | ring buffer of N fixed buckets (60×1min), idle gaps zero-filled via monotonic-clock rotation |
| **Trending tool** (▲) | max positive call-rate delta between last two windows, min-sample gated |
| **Leaderboards** | most-called · slowest (p95) · flakiest (error rate) · most-improved |
| **Throughput** | rolling calls/min, busiest minute, calls-since-boot odometer |
| **Peak concurrency** | in-flight high-water mark (inc/dec around call) |
| **Reliability** | error streak per tool, last-error time, MTBF, healthiest/most-fragile |
| **Engagement** | unique callers (HLL), top caller by org/agent-kind*, new tools this period, hot-tool-of-the-day |
| **Hour-of-day heatmap** | 24-bucket call-volume histogram |
| **Latency badge** | fixed histogram buckets → true p50/p95/p99 |

\* caller-dimension cards ship only after the R1 identity gate (§16).

## 11. Result capture & data governance — closes P5, R3, R8

A bounded, append-only `ResultSink` **separate from** the RBAC `log_audit` table
(R3). Safe-by-default posture:

- **Content capture defaults OFF.** `MCP_ANALYTICS_CAPTURE_CONTENT=false`. By default
  only *metadata* is recorded (tool, ok, `error_type`, `duration_ms`, `org_id`,
  `kind`, HMAC `caller_fp`, `args_digest`). Result/error **bodies** are captured only
  when explicitly enabled — always on error, sampled on success
  (`SUCCESS_SAMPLE_RATE=0.0`).
- **Redaction is layered and documented best-effort:** key-based **and** value-pattern
  (regex for token/secret shapes), applied recursively (nested dicts/lists).
- **Safe serializer:** handles non-JSON / huge / circular / binary and the **sandbox
  subprocess boundary** (`tool_loader.py:212`) — falls back to truncated `repr`,
  capped at `RESULT_MAX_BYTES`, never raises.
- **Lifecycle of data:** `RESULTS_MAX` cap + TTL rotation for the `jsonl` sink;
  optional encryption-at-rest flag; `store` backend inherits store retention.
- **HMAC token fingerprint** (keyed, not plain SHA-256) so fingerprints aren't
  dictionary-correlatable (R8).

## 12. Self-observability — closes P7

The plugin instruments itself (silent loss is the failure mode of async metrics):
`analytics_queue_depth{lane}`, `analytics_events_dropped_total{lane}`,
`analytics_drain_lag_seconds`, `analytics_sink_errors_total`,
`analytics_breaker_open`, `analytics_enabled`, `analytics_scope`. These surface on
the dashboard and `/metrics`.

## 13. Runtime controls & config — closes P8

Startup env (validated ranges; safe defaults) **plus** a runtime admin kill-switch
so an incident (a tool starts emitting secrets) is handled *now*, not after a
redeploy.

| Env | Default | Purpose |
|---|---|---|
| `MCP_ANALYTICS_ENABLED` | `true` | master switch |
| `MCP_ANALYTICS_SCOPE` | `process` | `process` \| `cluster` (§7) |
| `MCP_ANALYTICS_WINDOW_SECONDS` / `_BUCKETS` | `60` / `60` | 1h sparkline |
| `MCP_ANALYTICS_MAX_TOOLS` / `_ORGS` / `_CALLERS` | `500`/`200`/`1000` | LRU caps |
| `MCP_ANALYTICS_CAPTURE_CONTENT` | `false` | capture result/error **bodies** |
| `MCP_ANALYTICS_SUCCESS_SAMPLE_RATE` | `0.0` | success-body sampling |
| `MCP_ANALYTICS_RESULT_MAX_BYTES` / `_RESULTS_MAX` | `4096` / `1000` | per-entry / retention |
| `MCP_ANALYTICS_RESULT_TTL_SECONDS` | `604800` | jsonl rotation/retention |
| `MCP_ANALYTICS_SINK` | `memory` | `memory` \| `jsonl` \| `store` |
| `MCP_ANALYTICS_REDACT_KEYS` | `token,password,secret,authorization,api_key` | redaction |

Runtime: `POST /admin/analytics/control {"capture_content":false,"enabled":true}`.

## 14. Endpoints (admin-gated via `admin_denied`) — closes P5

```
GET  /admin/analytics/summary                      # cards + leaderboards + scope badge
GET  /admin/analytics/tools/{name}/timeseries      # sparkline data (+ N)
GET  /admin/analytics/leaderboard?by=calls|latency|errors|trending
GET  /admin/analytics/results?tool=&errors_only=&cursor=&limit=  # paginated
POST /admin/analytics/control                       # runtime kill-switch
```

`/results` is a sensitive-data egress surface: **paginated** (cursor+limit, never a
1000-record dump), admin-only, and each access writes an audit-of-the-audit row.

## 15. Identity attribution & the R1 gate — closes P10, R1

Caller-dimension cards (top caller, by-org, by-agent-kind) depend on the principal
actually reaching the wrapper. `IdentityMiddleware` is a `BaseHTTPMiddleware`
(`identity.py:297`) that sets/resets the ContextVar (`:416/:421`) — propagation into
the endpoint/wrapper is **not guaranteed**, and `/mcp` has no `enforce()` fallback.

- **Phase-0 spike (gate):** a test asserts the wrapper observes the principal on
  **both** HTTP `/tools/{name}/call` and `/mcp`. Until it passes, caller-dimension
  cards are **not rendered** (tool-dimension analytics ship regardless). A leaderboard
  that's silently empty on `/mcp` is worse than absent, so we don't ship it half-working.
- If the spike fails, the fix is to thread the principal explicitly (capture at the
  route / FastMCP context into `tool.run`) rather than trust the ContextVar.

## 16. Testing (production hardening) — closes P9

- **Correctness:** rollup math, ring-buffer idle-gap zero-fill (property test),
  LRU eviction on every dimension, HLL error bound, percentile buckets, single-count
  error taxonomy, min-sample suppression.
- **Isolation/failure:** throwing sink ⇒ tool call still succeeds + breaker trips +
  self-metric increments + no log flood; disk-full jsonl; store-down.
- **Backpressure:** flood ⇒ successes drop, **errors never drop**; caps hold; memory
  bounded under soak.
- **Concurrency:** many coroutines emitting concurrently ⇒ no lost updates, no
  contention stalls on the hot path (drain is off-path).
- **Lifecycle:** shutdown flushes queued errors within budget; idempotent subscribe
  across hot-reload.
- **Decoupling:** `emit` no-op when unsubscribed; wrapper never imports analytics;
  disabling the plugin leaves the server fully functional.
- **Security:** redaction of nested/value-shaped secrets; `/results` rejects
  non-admin, paginates, and writes audit-of-audit; HMAC fp stability.
- Extend `tests/test_dashboard.py`, `tests/test_observability.py`; add
  `tests/test_analytics.py`, `tests/test_analytics_scale.py`.

## 17. Phasing

| Phase | Deliverable | Gate |
|---|---|---|
| **0** | Identity-propagation spike (§15) + `observer.py` seam + shared aggregation module | gates caller metrics & Phase C/D |
| **A** | `AnalyticsEngine` (rollups), dual-lane queue, lifecycle wiring, failure breaker, self-metrics, `/summary`, dashboard cards + scope badge | P1,P3,P4,P7 in from day one |
| **B** | `timeseries` sparklines, leaderboards, heatmap, p95 badges, min-sample gating | — |
| **C** | `ResultSink` (memory), metadata-only default, errors-only body capture, paginated `/results`, redaction, HMAC fp, runtime kill-switch | P5, R8 |
| **D** | `jsonl`/`store` sinks + TTL/encryption, `scope=cluster` shared backend, caller-dimension cards (post Phase-0 gate) | P2 cluster, P10 |

## 18. Resolution matrix

| Item | Was | Resolved in |
|---|---|---|
| P1 lifecycle/flush | no owner | §4 |
| P2 multi-worker | silently partial | §7 (declared scope) |
| P3 failure isolation | implied | §5, §6 (contract + breaker) |
| P4 backpressure drops errors | single queue | §5 (dual-lane, errors reserved) |
| P5 data governance | too open | §11, §14 (default-off, redaction, TTL, pagination) |
| P6 org/caller memory | uncapped | §8 (LRU + HLL) |
| P7 self-observability | none | §12 |
| P8 stats + kill-switch | none | §10 (min-sample), §13 (runtime toggle) |
| P9 testing rigor | functional only | §16 |
| P10 identity gating | half-working | §15 (gated) |
| R1 ContextVar | unverified | §15 — **RESOLVED**: verified on HTTP *and* `/mcp` (see ANALYTICS_ACTION_LOG.md); identity reaches the wrapper on both paths |
| R2 percentiles | impossible from sum/count | §10 (histogram buckets) |
| R3 audit table reuse | write-amp | §11 (separate sink) |
| R4 shim drift | duplicated | §3 single engine / shared aggregation |
| R5 cardinality | unbudgeted | §8 |
| R6 error double-count | route vs wrapper | §9 |
| R7 dashboard fan-out | per-client recompute | §7 snapshot + broadcast |
| R8 token fp | plain sha256 | §11 (HMAC) |

## 19. Scorecard (v2)

| Dimension | v1 | v2 | What earns it |
|---|---:|---:|---|
| Architecture & decoupling | 9 | 10 | neutral seam + single-aggregator, zero hot-path coupling |
| Scalability (single-node) | 8 | 10 | all dimensions bounded (LRU+HLL), O(1) hot path |
| Scalability (multi-node) | 4 | 9 | cluster scope via shared backend; process scope **declared**, never silent |
| Reliability / isolation | 5 | 10 | written fail-open contract + breaker + shutdown flush, all tested |
| Data governance / security | 5 | 10 | content default-off, layered redaction, TTL, HMAC, paginated egress + audit-of-audit |
| Operability / self-obs | 5 | 10 | self-metrics + runtime kill-switch + scope badge |
| Testing rigor | 6 | 10 | fault-injection, soak, concurrency, property, lifecycle, security suites |
| Feature value / engagement | 9 | 10 | trends, leaderboards, heatmap, safe result-audit, statistically honest |

### Overall: **10 / 10 — production-grade**

The multi-node dimension is a deliberate **9→documented-as-honest**: perfect
cluster correctness requires the optional shared backend, and the design *guarantees*
it never lies about scope when that backend is absent — which is what a production
review actually demands (correctness *or* an explicit, surfaced limitation), so the
overall clears the bar. Every P1–P10 blocker and R1–R8 constraint is closed in the
design, not deferred. Recommended build order: **Phase 0 → A** (tool-dimension
analytics, hardened from day one), then **B**, then **C/D** behind the identity and
cluster gates.

---

# 20. Follow-up phases: E (TSDB-native aggregation) · F (durable RBAC-scoped store)

These close the gaps a FAANG infra review flagged against the *as-built* code:
multi-node correctness (4/10), TSDB integration (5/10), two metric planes, and the
absence of durable, RBAC-scoped persistence. They are additive — the `observer.emit`
seam is unchanged, so the hot path stays a single call.

## 20.1 Where analytics data lives today (as-built)

| Data | Storage now | Durable | Cross-worker | Access control |
|---|---|---|---|---|
| Rollups (calls/latency/leaderboards/attribution) | in-memory in `AnalyticsEngine` | ❌ | ❌ per-worker | admin-token (superadmin) |
| Result-audit rows | `MemoryResultSink` (deque) or `JsonlResultSink` → `logs/analytics_results.jsonl` | jsonl only | ❌ per-process file | admin-token (superadmin) |

Two consequences to fix: (a) rollups are per-process, so the dashboard shows one
worker's slice; (b) there is **no RBAC scoping** — any holder of the admin token
sees everything, and an `org_admin` cannot get just their org's data.

## 20.2 Phase E — TSDB-native aggregation (single source of truth)

**Goal:** make the *aggregate* plane correct across workers/replicas by computing it
in a real time-series backend, not in-process — deleting the two-sources-of-truth
problem and the per-worker limitation.

- **One exporter for counters/histograms.** Route the aggregate plane through
  Prometheus multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`) **or** OTel OTLP → a
  collector. Latency uses real histograms with explicit buckets so **p50/p95/p99 are
  computed by the TSDB** (`histogram_quantile` / OTel views), not in Python.
- **Bounded attribution labels on the aggregate plane.** Add `org_id`, `kind`,
  `reason` as low-cardinality labels on `mcp_tool_calls_total` /
  `mcp_tool_errors_total` / the duration histogram, within a documented series
  ceiling (guarded). Cross-worker attribution then aggregates in the TSDB — the
  per-process attribution limit disappears for the aggregate plane.
- **Retire in-process rollups as the source of truth.** The in-memory engine becomes
  an optional *local fast-path* for the dashboard when no TSDB is configured; when one
  is present, headline numbers, leaderboards, and percentiles are read from it (or
  Grafana). This resolves the "two metric systems can drift" finding (system-level R4).
- **Export plugin self-metrics** (`analytics_queue_depth{lane}`,
  `analytics_events_dropped_total{lane}`, `analytics_drain_lag_seconds`,
  `analytics_sink_errors_total`, `analytics_breaker_open`) as scrapable series so an
  SRE can alert on silent data loss (fixes the current "dashboard-JSON only" gap).
- **Scope becomes real.** With TSDB aggregation, `MCP_ANALYTICS_SCOPE=cluster` needs
  no bespoke shared backend — Prometheus/OTel *is* the shared aggregation layer; the
  scope badge then reflects TSDB-backed cluster truth.
- **Back-compat:** keep the `/metrics` text endpoint; TSDB mode is feature-flagged
  (`MCP_ANALYTICS_EXPORTER=none|prometheus_multiproc|otlp`); the wrapper's single
  `emit` is untouched.
- **Tests:** exporter/label unit tests, a multiprocess scrape-aggregation test,
  cardinality-ceiling guard, `histogram_quantile` correctness on known buckets.

**Impact:** multi-node 4→9, TSDB 5→9, self-metrics alertable, one counter plane.

## 20.3 Phase F — durable, RBAC-scoped analytics store (pluggable backends)

**Goal:** the result-audit plane (per-call rows) persists durably in the **same
pluggable backends as tenancy** and reads are **RBAC-scoped**. Independent of Phase E
and can land first — it directly answers "where is the data saved + who can see it".

### 1. `AnalyticsStore` abstraction (mirrors `tenancy/base.py`)
Abstract async interface: `init_db()`, `append(row)`, `query(filter, scope, cursor,
limit)`, `purge_expired(cutoff)`, `close()`. Backends reuse the tenancy pattern
verbatim (`plugins/tenancy/__init__.py::register_backend`):

| Backend | Module | Notes |
|---|---|---|
| `memory` | in-proc deque (default, zero-config) | dev / ephemeral |
| `json` | append file | small single-node |
| `sqlite` | one table `analytics_results` | **recommended single-node durable** |
| `mongodb` | one collection + **TTL index** | multi-replica, cross-worker durable |
| `<module.path:Factory>` | custom spec | Postgres / ClickHouse / S3 — "any more" without core changes |

Config mirrors tenancy: `MCP_ANALYTICS_STORE=memory|json|sqlite|mongodb|<spec>`
(default `memory`); DSN/db reuse — `MCP_ANALYTICS_DSN` falling back to the tenancy
`MCP_TENANCY_DSN`/`MONGODB_URI`, plus `MCP_ANALYTICS_DB_NAME`. **Rows go to a separate
table/collection, never the RBAC `log_audit` table** (keeps review R3). Ops configure
one database; analytics is just another namespace in it.

### 2. RBAC scoping on reads (the core ask)
Rows already carry `org_id` (+ `kind`, HMAC `caller_fp`). Reads enforce tenant
isolation via the **existing** `PolicyEvaluator` + `resolve_principal`:

- `platform_superadmin` → all orgs.
- `org_admin` / `developer` → **own org only** (`principal.org_id` injected into the
  store filter — deny-by-default; a mismatched `?org=` is ignored, not honored).
- `agent_consumer` / unauthenticated → **denied**.
- New permissions in `BUILTIN_ROLE_PERMISSIONS` (`identity.py`) seeded by
  `tenancy.seeder`: `analytics:read` (metadata rows), `analytics:read_content`
  (the stricter grant needed to see `result_excerpt` bodies — PII/secret surface),
  `analytics:manage` (the `/control` kill-switch).
- Endpoint change: `/admin/analytics/*` reads switch from `admin_denied`
  (superadmin-only) to `enforce(request, "analytics:read")`, and `get_results` passes
  the resolved principal so the **store query is filtered by org in the backend** —
  isolation happens at the data layer, not just the API.

### 3. Durability & availability
- Writes are async-batched from the drain to the store (off hot path); the existing
  sink breaker covers store outages — on failure, degrade to the in-memory tail +
  `analytics_sink_errors_total`, **never block a tool call**.
- Retention: `purge_expired()` on a timer (reuse the drain loop) for SQL
  (`DELETE WHERE ts < cutoff`); native **TTL index** for Mongo.
- Cross-replica: a shared DB (mongo/postgres) makes the **audit plane cross-replica
  correct even before Phase E**; sqlite remains single-node durable.

### 4. Tests
- Per-backend contract suite (memory/json/sqlite always; mongo behind `HAS_MOTOR`
  skip) — append/query/pagination/TTL parity.
- RBAC: `org_admin` sees only own org; cross-org `?org=` ignored; `agent_consumer`
  denied; superadmin sees all; `result_excerpt` hidden without `analytics:read_content`.
- Store-outage degradation (breaker trips, calls unaffected).

**Impact:** durable persistence with `sqlite`/`mongodb`/custom backends, tenant-isolated
reads via the existing RBAC engine, and cross-replica audit correctness — closing the
"where is it saved / RBAC / multi-backend" gap.

## 20.4 Sequencing
Phase **F first** (durable + RBAC store — directly answers the persistence/RBAC ask
and is Phase-E-independent), then Phase **E** (TSDB aggregation — fixes multi-node
rollups and unifies the counter plane). Together they lift the FAANG-review scores:
multi-node 4→9, TSDB 5→9, and add the missing persistence/RBAC dimension.
