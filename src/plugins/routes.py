"""HTTP routes: liveness, readiness, status, tool catalog, metrics, admin API.

Auth summary (see docs/MCP_AUTH_GUIDE.md):
  /healthz, /readyz            -- always open (probes).
  /status, /tools, /metrics    -- open in `none`; api-key in `api_key`; JWT in `bearer_jwt`.
  /admin/*                     -- always gated by MCP_ADMIN_TOKEN; 503 if unset.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from metrics import METRICS
from .notifications import notify_tools_changed
from .security import HEALTH_PATH, READY_PATH, admin_denied, read_guard

log = logging.getLogger("MCP_logger")


async def _health(_request):
    return JSONResponse({"status": "ok"})


async def _readyz(request):
    ready = bool(getattr(request.app.state, "ready", False))
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)


async def _status(request):
    if (denied := await read_guard(request)) is not None:
        return denied
    st = request.app.state
    return JSONResponse({
        "ready": bool(getattr(st, "ready", False)),
        "auth": st.auth_type,
        "source": "local",
        "stats": st.loader.stats(),
    })


async def _tools_catalog(request):
    if (denied := await read_guard(request)) is not None:
        return denied
    return JSONResponse({"tools": request.app.state.loader.catalog()})


async def _metrics(request):
    if (denied := await read_guard(request)) is not None:
        return denied
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")


def register_metrics(loader, app) -> None:
    """Declare counters and scrape-time gauges backed by loader/app state."""
    METRICS.declare("mcp_tool_calls_total", "Total tool invocations")
    METRICS.declare("mcp_tool_errors_total", "Tool invocations that raised")
    METRICS.declare("mcp_tool_duration_seconds", "Tool execution wall-time")
    METRICS.declare("mcp_reloads_total", "Module (re)loads that registered tools")
    METRICS.declare("mcp_load_failures_total", "Module loads that failed or yielded no tools")
    METRICS.gauge("mcp_ready", lambda: 1.0 if getattr(app.state, "ready", False) else 0.0,
                  "1 once the initial tool load has completed")
    METRICS.gauge("mcp_tools_loaded", lambda: loader.stats()["total_tools"], "Currently registered tools")
    METRICS.gauge("mcp_modules_failed", lambda: loader.stats()["failed_modules"], "Modules currently failing to load")
    METRICS.gauge("mcp_tools_disabled", lambda: loader.stats()["disabled_tools"], "Disabled tools")


async def _admin_resync(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    # No remote tool source: nothing to sync, the filesystem watcher already
    # picks up local edits. Kept for parity with the admin API shape.
    return JSONResponse({"status": "skipped", "reason": "no remote tool source configured"}, status_code=409)


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


async def _admin_disable(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    if not st.loader.disable(name):
        return JSONResponse({"error": f"unknown tool {name!r}"}, status_code=404)
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "disabled", "tool": name})


async def _admin_enable(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    module = st.loader.enable(name)
    if module:
        st.loader.load_path(st.loader.file_for_module(module))
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "enabled", "tool": name, "reloaded": bool(module)})


def feature_routes() -> List[Route]:
    return [
        Route(HEALTH_PATH, _health, methods=["GET"]),
        Route(READY_PATH, _readyz, methods=["GET"]),
        Route("/status", _status, methods=["GET"]),
        Route("/tools", _tools_catalog, methods=["GET"]),
        Route("/metrics", _metrics, methods=["GET"]),
        Route("/admin/resync", _admin_resync, methods=["POST"]),
        Route("/admin/reload/{name}", _admin_reload, methods=["POST"]),
        Route("/admin/tool/{name}/disable", _admin_disable, methods=["POST"]),
        Route("/admin/tool/{name}/enable", _admin_enable, methods=["POST"]),
    ]
