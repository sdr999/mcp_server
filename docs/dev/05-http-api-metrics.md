# 05 — HTTP API & Metrics (`plugins/routes.py`, `metrics.py`)

**Job:** expose health/readiness/observability/admin endpoints on top of the
FastMCP ASGI app, and a dependency-free Prometheus metrics registry.

## The route table

`feature_routes()` returns plain Starlette `Route`s that `build_app` appends to
the FastMCP app's router.

```python
def feature_routes() -> List[Route]:
    return [
        Route(HEALTH_PATH, _health, methods=["GET"]),                 # /healthz
        Route(READY_PATH,  _readyz, methods=["GET"]),                 # /readyz
        Route("/status",   _status, methods=["GET"]),
        Route("/tools",    _tools_catalog, methods=["GET"]),
        Route("/metrics",  _metrics, methods=["GET"]),
        Route("/admin/resync", _admin_resync, methods=["POST"]),
        Route("/admin/reload/{name}", _admin_reload, methods=["POST"]),
        Route("/admin/tool/{name}/disable", _admin_disable, methods=["POST"]),
        Route("/admin/tool/{name}/enable",  _admin_enable, methods=["POST"]),
        Route("/admin/tools/onboard", _admin_tools_onboard, methods=["POST"]),
        Route("/admin/tools/pending", _admin_tools_pending_list, methods=["GET"]),
        Route("/admin/tools/pending/{name}", _admin_tools_pending_detail, methods=["GET"]),
        Route("/admin/tools/pending/{name}/approve", _admin_tools_pending_approve, methods=["POST"]),
        Route("/admin/tools/pending/{name}/reject",  _admin_tools_pending_reject, methods=["POST"]),
    ]
```

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /healthz` | open | liveness — process is up |
| `GET /readyz` | open | readiness — `200` only after initial load, else `503` |
| `GET /status` | MCP cred | `{ready, auth, source:"local", stats}` |
| `GET /tools` | MCP cred | tool catalog `[{name, module, description, tags}]` |
| `GET /metrics` | MCP cred | Prometheus text |
| `POST /admin/resync` | admin | no-op `409` (no remote source; watcher covers edits) |
| `POST /admin/reload/{name}` | admin | reload the module owning a tool |
| `POST /admin/tool/{name}/disable\|enable` | admin | toggle a tool across reloads |
| `POST /admin/tools/onboard` | admin | submit a tool (doc 07) |
| `GET /admin/tools/pending[/{name}]` | admin | list / detail (incl. source + manifest) |
| `POST /admin/tools/pending/{name}/approve\|reject` | admin | resolve a pending submission |

## Readiness vs liveness

```python
async def _health(_request):
    return JSONResponse({"status": "ok"})            # always 200 once the process is up

async def _readyz(request):
    ready = bool(getattr(request.app.state, "ready", False))
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)
```

`app.state.ready` is flipped to `True` by the lifespan's `_bootstrap` after the
initial load (doc 04).

## Read routes are guarded, admin routes are gated

Every read route calls `read_guard` (doc 02); every admin route calls
`admin_denied`. Example admin handler (onboarding shown in doc 07):

```python
async def _admin_reload(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    module = st.loader.module_for_tool(name)
    if not module:
        return JSONResponse({"error": f"unknown tool {name!r}"}, status_code=404)
    st.loader.load_path(st.loader.file_for_module(module))
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "reloaded", "tool": name, "module": module})
```

## Metrics registration

`register_metrics` declares counters and **scrape-time gauges** (backed by a
callable, so they read live loader/onboarding state at scrape time — no
polling). Onboarding metrics are registered only if an onboarding manager is
present.

```python
def register_metrics(loader, app):
    METRICS.declare("mcp_tool_calls_total", "Total tool invocations")
    METRICS.declare("mcp_tool_errors_total", "Tool invocations that raised")
    METRICS.declare("mcp_tool_duration_seconds", "Tool execution wall-time")
    METRICS.gauge("mcp_ready", lambda: 1.0 if getattr(app.state, "ready", False) else 0.0, ...)
    METRICS.gauge("mcp_tools_loaded",  lambda: loader.stats()["total_tools"], ...)
    METRICS.gauge("mcp_modules_failed", lambda: loader.stats()["failed_modules"], ...)
    onboarding = getattr(app.state, "onboarding", None)
    if onboarding is not None:
        METRICS.declare("mcp_tool_onboards_total", "Onboarding actions by result ...")
        METRICS.gauge("mcp_tools_pending", onboarding.pending_count, "Submissions held pending")
```

| Metric | Type | Labels |
|--------|------|--------|
| `mcp_ready`, `mcp_tools_loaded`, `mcp_modules_failed`, `mcp_tools_disabled`, `mcp_tools_pending` | gauge | — |
| `mcp_tool_calls_total`, `mcp_tool_errors_total` | counter | `tool` |
| `mcp_reloads_total`, `mcp_load_failures_total`, `mcp_tool_onboards_total` | counter | (`result` for onboards) |
| `mcp_tool_duration_seconds` | summary | `tool` |

## The metrics registry (`metrics.py`)

A ~90-line in-house Prometheus registry — kept dependency-free on purpose.
Counters and summaries are stored under `(name, label_key)`; gauges hold a
callable evaluated at render time.

```python
class Metrics:
    def inc(self, name, value=1.0, **labels):
        with self._lock:
            self._counters[(name, _label_key(labels))] += value

    def observe(self, name, value, **labels):        # summary: _sum / _count
        with self._lock:
            key = (name, _label_key(labels))
            self._sum[key] += value
            self._count[key] += 1

    def gauge(self, name, fn, help_text=""):         # evaluated at scrape time
        self._gauges[name] = (help_text, fn)

    def render(self) -> str:                          # Prometheus text exposition
        ...
```

Locking guards the counter/summary dicts; gauge callables are invoked inside
`render` under the lock, with failures swallowed so one bad gauge can't break
the scrape.

## Gotchas / design notes

- `/admin/resync` intentionally returns `409` — there's no remote tool source
  to resync; it exists for API-shape parity with the Azure-backed sibling
  server. The watcher already handles local edits.
- Gauges are pull-based: no background thread updates them; they reflect state
  at the moment `/metrics` is scraped.
