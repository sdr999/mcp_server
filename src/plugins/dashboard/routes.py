"""Dashboard HTTP, JSON Key-Value Summary, and EventSource SSE streaming endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Set

from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from .templates import DASHBOARD_HTML
from ..security import admin_denied

log = logging.getLogger("MCP_logger")

MAX_SSE_CLIENTS = 10
_active_sse_clients: Set[asyncio.Queue] = set()


def _build_dashboard_summary(request) -> dict:
    st = request.app.state
    loader = getattr(st, "loader", None)
    stats = loader.stats() if loader else {}
    cb_registry = getattr(st, "circuit_breakers", None)
    cb_stats = cb_registry.all_stats() if cb_registry else {}

    rate_limiter = getattr(st, "rate_limiters", None)
    default_rpm = getattr(getattr(rate_limiter, "default_config", None), "max_requests_per_minute", 600) if rate_limiter else 600

    from metrics import METRICS
    registered_tools = [t["name"] for t in loader.catalog()] if loader else []
    tool_metrics = METRICS.get_tool_stats(registered_tools) if hasattr(METRICS, "get_tool_stats") else {}

    cost_tracker = getattr(st, "cost_tracker", None)
    cost_summary = cost_tracker.get_stats() if cost_tracker else {}
    chaos_engine = getattr(st, "chaos_engine", None)
    chaos_summary = chaos_engine.get_stats() if chaos_engine else {}
    prompt_repo = getattr(st, "prompt_repository", None)
    prompts_count = len(prompt_repo.list_prompts()) if prompt_repo else 0
    analytics = getattr(st, "analytics", None)
    analytics_summary = analytics.get_stats() if analytics else {}

    # Phase 5 & 6: Task Queue, Upstream Health & System Watchdog stats
    task_queue = getattr(st, "task_queue", None)
    task_queue_stats = task_queue.get_stats() if task_queue else {}
    health_checker = getattr(st, "upstream_health_checker", None)
    upstream_health_stats = health_checker.get_stats() if health_checker else {}
    system_watchdog = getattr(st, "system_watchdog", None)
    watchdog_stats = system_watchdog.get_stats() if system_watchdog else {}

    return {
        "server_status": "READY" if getattr(st, "ready", False) else "LOADING",
        "ready": bool(getattr(st, "ready", False)),
        "total_tools": stats.get("total_tools", 0),
        "loaded_modules": stats.get("loaded_modules", 0),
        "failed_modules": stats.get("failed_modules", 0),
        "disabled_tools": stats.get("disabled_tools", 0),
        "active_sse_clients": len(_active_sse_clients),
        "rate_limit_default_rpm": default_rpm,
        "auth_mode": getattr(st, "auth_type", "none"),
        "mcp_transport": getattr(st, "mcp_transport", "http"),
        "total_spend_usd": cost_summary.get("total_spend_usd", 0.0),
        "chaos_enabled": chaos_summary.get("enabled", False),
        "total_prompts": prompts_count,
        "circuit_breakers": cb_stats,
        "tool_metrics": tool_metrics,
        "cost_summary": cost_summary,
        "chaos_summary": chaos_summary,
        "analytics": analytics_summary,
        "task_queue": task_queue_stats,
        "upstream_health": upstream_health_stats,
        "system_watchdog": watchdog_stats,
    }




async def dashboard_html_handler(request):
    if denied := await admin_denied(request):
        return denied
    if request.query_params.get("format") == "json" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(_build_dashboard_summary(request))
    return HTMLResponse(DASHBOARD_HTML)


async def dashboard_json_handler(request):
    if denied := await admin_denied(request):
        return denied
    return JSONResponse(_build_dashboard_summary(request))


async def dashboard_sse_handler(request):
    if denied := await admin_denied(request):
        return denied

    if len(_active_sse_clients) >= MAX_SSE_CLIENTS:
        return JSONResponse(
            {"error": "Too Many Connections", "message": "Max 10 active SSE dashboard clients allowed."},
            status_code=429,
        )

    client_queue: asyncio.Queue = asyncio.Queue()
    _active_sse_clients.add(client_queue)

    async def event_generator():
        try:
            while True:
                payload = _build_dashboard_summary(request)
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
        finally:
            _active_sse_clients.discard(client_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def dashboard_routes() -> List[Route]:
    return [
        Route("/admin/dashboard", endpoint=dashboard_html_handler, methods=["GET"]),
        Route("/admin/dashboard/json", endpoint=dashboard_json_handler, methods=["GET"]),
        Route("/admin/dashboard/stream", endpoint=dashboard_sse_handler, methods=["GET"]),
    ]
