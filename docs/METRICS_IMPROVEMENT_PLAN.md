# Metrics & Observability Improvement Plan

**Status:** proposed · **Branch:** `grade3` · **Scope:** tool-execution metrics,
caller-identity attribution, dashboard data richness.

## 1. Problem statement

The live dashboard is effectively limited to **invocation count, error count, and
a derived success rate** per tool. Two capabilities are missing:

1. **Performance signal** — latency, percentiles, throughput, concurrency, and an
   error taxonomy (validation vs runtime vs timeout).
2. **Caller attribution** — *who* called each tool: which agent, which person
   (subject), which org/workspace, under which token/role. Today this is not
   captured in metrics at all, and successful calls leave no audit trail.

## 2. Current state (as-is)

Recording happens in one place — the tool wrapper, `src/plugins/tool_loader.py:189-222`:

```python
METRICS.inc("mcp_tool_calls_total", tool=tool_name)          # :193
...
except Exception:
    METRICS.inc("mcp_tool_errors_total", tool=tool_name)      # :219
finally:
    METRICS.observe("mcp_tool_duration_seconds", ..., tool=tool_name)  # :222
```

The shim (`legacy_metrics.py` / `plugins/telemetry/metrics.py`) fans this out to a
Prometheus text endpoint and/or OTel instruments.

| Signal | Collected? | Surfaced on dashboard? | Notes |
|---|---|---|---|
| calls / errors / success-rate per tool | ✅ | ✅ | `get_tool_stats()` |
| duration (sum + count) per tool | ✅ | ❌ | observed but **dropped by `get_tool_stats()`** |
| latency percentiles (p50/p95/p99) | ❌ | ❌ | no histogram buckets |
| error taxonomy (400 vs 500 vs timeout) | ❌ | ❌ | all collapse into `errors_total` |
| in-flight / concurrency | ❌ | ❌ | — |
| caller identity (agent/subject/org/token) | ❌ | ❌ | wrapper never reads the Principal |
| per-call audit of successful calls | ❌ | ❌ | only RBAC deny/shadow write audit |
| cost / tokens per tenant+model | ✅ | ✅ | `cost/cost_tracker.py:50-51` |

**Key structural finding:** the dashboard bottleneck is
`get_tool_stats()` (`legacy_metrics.py:86`, `telemetry/metrics.py:110`). It reads
only `mcp_tool_calls_total` and `mcp_tool_errors_total` and ignores the duration
`_sum`/`_count` that are **already stored**. Latency is a *surfacing* problem
before it is a *collection* problem.

**Identity is available but unused.** `Principal` (`identity.py:86`) carries
`principal_id, issuer, subject, kind (user|service|agent), org_id, workspace_id,
roles, metadata`. It is resolved in `enforce()` and stored in the
`current_principal_var` ContextVar (`security.py:141`) — but
`tool_loader.py` has zero references to it, so nothing attributes a call to a caller.

## 3. Design principles

- **Cardinality discipline.** Prometheus labels must be bounded. `tool`, `org_id`,
  `workspace_id`, `kind`, `role`, `error_reason` are low-cardinality → safe as
  labels. `principal_id`, `subject`, agent id, token fingerprint are unbounded →
  **never** Prometheus labels; they belong in spans (exemplars) and the audit log.
- **Two planes.** *Aggregates* (Prometheus/dashboard) answer "how much / how fast /
  who broadly"; *per-event records* (audit log + traces) answer "who exactly did
  what, when". Don't conflate them.
- **Backward compatibility.** `get_tool_stats()` keeps its existing keys; new keys
  are additive so the current template keeps working.
- **Privacy.** Never emit raw tokens. Store a truncated SHA-256 fingerprint only.
  Subject/PII stays in the audit plane, gated behind admin auth.

## 4. Phased plan

### Phase 1 — Surface latency that is already collected (fast, low-risk)
- Extend `get_tool_stats()` (both impls) to read the duration `_sum`/`_count` and
  return `avg_latency_ms`, `call_count`, `last_called_ts`.
- Add columns to the dashboard template (`plugins/dashboard/templates.py:194`).
- **No new instrumentation.** Pure read-side change. Immediate visible win.

### Phase 2 — Richer latency + error taxonomy
- Real percentiles: maintain bounded histogram buckets per tool (p50/p95/p99),
  not just a running sum. Expose Prometheus `_bucket` series + computed quantiles
  in `get_tool_stats()`.
- Split errors by `reason` label: `validation` (400) | `runtime` (tool raised) |
  `timeout` | `sandbox`. Requires distinguishing the exception classes at
  `tool_loader.py:218` / `routes.py:248`.
- Add `mcp_tools_in_flight` gauge (inc at start, dec in `finally`).

### Phase 3 — Caller attribution
- In the wrapper, read `get_current_principal()`. Add **low-cardinality** labels
  to calls/errors/duration: `org_id`, `workspace_id`, `kind`, `role`.
- High-cardinality identity (`principal_id`, `subject`, agent id, token
  fingerprint) → span attributes (`spans.py`) + the audit row, not labels.
- Fix span `tenant_id`: currently passed as `""` from the wrapper
  (`tool_loader.py:209`); wire the principal's `org_id` through.

### Phase 4 — Per-call audit + dashboard breakdowns
- Write an audit row on **every** call (success included) via `store.log_audit`:
  `principal_id, subject, kind, org_id, workspace_id, tool, duration_ms, outcome,
  token_fp`.
- New dashboard panels: top callers, calls-by-agent-kind, latency leaderboard,
  error-reason breakdown.

## 5. Proposed metric surface (target)

```
mcp_tool_calls_total{tool,org_id,workspace_id,kind,role}
mcp_tool_errors_total{tool,reason,org_id,workspace_id,kind}
mcp_tool_duration_seconds_bucket{tool,le}          # histogram
mcp_tools_in_flight{tool}                           # gauge
# per-call detail (NOT metrics): audit log + trace span attributes
```

## 6. Testing & rollout
- Unit tests: `get_tool_stats()` returns latency keys; error-reason routing;
  cardinality guard (identity labels absent when no principal).
- Extend `tests/test_dashboard.py`, `tests/test_observability.py`,
  `tests/test_telemetry.py`.
- Rollout: Phase 1 ships alone (read-only); identity labels behind a config flag
  (`MCP_METRICS_IDENTITY_LABELS`) defaulting off for one release.

## 7. Open questions
- Audit write on the hot path: async-buffered or inline?
- Percentile accuracy vs memory: fixed buckets vs a t-digest/streaming estimator?

---

# Senior Architect Review

Reviewed against the actual code on `grade3`. The plan is directionally correct
(surface-first, cardinality-aware, two planes) but several load-bearing
assumptions are wrong or under-specified. Findings ordered by risk.

### R1 (blocker) — the identity mechanism is fragile across the middleware boundary
Phase 3 says "read `get_current_principal()` in the wrapper." But identity is
resolved by `IdentityMiddleware` (`identity.py:297`), a **`BaseHTTPMiddleware`**,
which sets the ContextVar at `:416` and **resets it at `:421`** in a `finally`.
Starlette runs the downstream app in a *different* `contextvars.Context` than a
`BaseHTTPMiddleware.dispatch`, so a ContextVar set there is **not guaranteed to be
visible in the endpoint / tool wrapper**. The only reliably-propagated handle is
`request.state.principal`, which the wrapper cannot see (it has no `request`).
For HTTP `/tools/{name}/call`, `enforce()` *also* sets the var inside the endpoint
task (`security.py:141`) so it may work there — but only when policy ≠ `none`, and
**not** on the `/mcp` protocol path.
→ **Action:** promote the old "open question" to a **Phase 0 spike**: prove, with a
test on *both* the HTTP and `/mcp` paths, that the wrapper actually observes the
principal before building labels/audit on it. If it doesn't, thread the principal
explicitly (capture at the route/FastMCP context and pass into `tool.run`), or move
identity resolution to pure ASGI middleware. Do not build Phases 3–4 on an
unverified ContextVar.

### R2 (blocker) — a percentile cannot be derived from sum/count
Phase 1 returning `avg_latency_ms` from `_sum`/`_count` is correct. But anything
claiming p50/p95/p99 from the existing summary is **mathematically impossible** —
sum and count carry no distribution. Percentiles require histogram buckets or a
streaming estimator (t-digest/DDSketch). When OTel is on, use the Histogram already
created at `telemetry/metrics.py:63` with explicit bucket boundaries and let the
backend compute quantiles; for the Legacy fallback, expose fixed `_bucket` series
and render a bucketed histogram — never a fabricated percentile.

### R3 (major) — Phase 4 implies a 5-store schema migration
`log_audit` (`tenancy/base.py:155`) has fixed columns
`(actor_principal, issuer, org_id, action, resource, decision, detail)` — no
`duration`, `kind`, `outcome`, or `token_fp` — implemented in **five** stores
(base/json/memory/mongo/sqlite). Writing per-call detail there means a migration
across all five, or overloading `detail` with JSON. Worse, an audit write on
**every successful call** is write-amplification on the hot path against a
transactional store.
→ **Action:** don't reuse the RBAC audit table for high-volume per-call events.
Introduce a **separate append-only buffered sink** (JSONL / async queue, sampled),
decoupled from `log_audit`. Keep `log_audit` for security-relevant events only.

### R4 (major) — the two shims will drift; extract shared aggregation
`legacy_metrics.py` and `telemetry/metrics.py` carry **near-identical**
`get_tool_stats()` and `render()`. Every phase edits both; they *will* diverge.
→ **Action (Phase 0):** extract the aggregation (`get_tool_stats`, label parsing,
bucket math) into one shared module both shims call. This single refactor de-risks
Phases 1–4 and is a prerequisite, not a nice-to-have.

### R5 (major) — cardinality is still under-budgeted
- `role` is `List[str]` (`identity.py:93`) — not a scalar. A `role` label needs a
  deterministic reduction (highest-privilege role) or it's ambiguous.
- `tool × org_id × workspace_id × kind × reason` is **multiplicative**. On a large
  tenant base this can explode the active series count and OOM the scrape.
→ **Action:** cap the metrics plane to `org_id` + `kind` (+ `reason` on errors).
Drop `workspace_id` and `role` from *labels* — keep them in the audit/trace plane.
Document a hard series-count ceiling and add a guard that refuses to emit a new
label set past it.

### R6 (moderate) — error taxonomy must be single-counted at one boundary
Validation (400) is currently detected in the **route** (`routes.py:248`,
`_ToolValidationError`), but the wrapper's `except Exception` at
`tool_loader.py:218` fires **first**, inside `tool.run`, and already increments a
generic error. Splitting into `validation|runtime|timeout|sandbox` must happen at
the wrapper with the same exception classes the route uses, and must **count each
failure exactly once** (today the route path can't reclassify what the wrapper
already counted).

### R7 (moderate) — dashboard fan-out won't scale with richer payloads
`_build_dashboard_summary` runs **per SSE client every 2s** (`dashboard/routes.py:97`)
and scans the whole counter dict. Adding per-caller/per-tool breakdowns multiplies
both payload size and the O(counters) scan by the client count.
→ **Action:** compute one snapshot per tick and fan it out to all SSE clients
(shared broadcast); pre-aggregate instead of re-scanning raw counters each render.

### R8 (minor) — token fingerprint should be keyed
Storing `sha256(token)[:n]` lets an attacker with a token dictionary correlate
fingerprints. Use an **HMAC** with a server secret so fingerprints are opaque and
non-reversible. Add a retention policy for the per-call sink (PII).

## Revised sequencing (post-review)

| Phase | Work | Gate |
|---|---|---|
| **0** | Identity-propagation spike (R1) + extract shared aggregation module (R4) | Must pass before 3–4 |
| **1** | Surface **avg latency + call count + last-called** from existing sum/count (R2: no percentiles yet) | Ships alone, read-only |
| **2** | Histogram buckets → real p50/p95/p99; `in_flight` gauge; single-counted error taxonomy (R6) | — |
| **3** | Caller labels limited to `org_id` + `kind` (R5); full identity → spans + sink | Depends on Phase 0 |
| **4** | Buffered per-call sink (R3), not the RBAC audit table; HMAC token fp (R8); dashboard broadcast + breakdowns (R7) | — |

**Bottom line:** Phase 1 is safe to ship now. Phases 3–4 must not start until the
Phase 0 spike proves identity actually reaches the wrapper and the shared
aggregation refactor lands — otherwise we build attribution on a ContextVar that
may be silently empty on the `/mcp` path.
