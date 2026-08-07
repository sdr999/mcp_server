"""Admin endpoints for Chaos Engineering control."""
from __future__ import annotations

import logging
from typing import List
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..security import admin_denied

log = logging.getLogger("MCP_logger")


async def get_chaos_status_handler(request):
    if denied := await admin_denied(request):
        return denied
    engine = getattr(request.app.state, "chaos_engine", None)
    if not engine:
        return JSONResponse({"error": "Chaos Engine not initialized"}, status_code=503)
    return JSONResponse(engine.get_stats())


async def enable_chaos_handler(request):
    if denied := await admin_denied(request):
        return denied
    engine = getattr(request.app.state, "chaos_engine", None)
    if not engine:
        return JSONResponse({"error": "Chaos Engine not initialized"}, status_code=503)
    success = engine.enable()
    if not success:
        return JSONResponse(
            {"error": "Forbidden", "message": "Chaos Engine cannot be enabled unless MCP_ALLOW_CHAOS environment variable is true."},
            status_code=403,
        )
    return JSONResponse({"status": "enabled", "stats": engine.get_stats()})


async def disable_chaos_handler(request):
    if denied := await admin_denied(request):
        return denied
    engine = getattr(request.app.state, "chaos_engine", None)
    if not engine:
        return JSONResponse({"error": "Chaos Engine not initialized"}, status_code=503)
    engine.disable()
    return JSONResponse({"status": "disabled", "stats": engine.get_stats()})


async def configure_chaos_rules_handler(request):
    if denied := await admin_denied(request):
        return denied
    engine = getattr(request.app.state, "chaos_engine", None)
    if not engine:
        return JSONResponse({"error": "Chaos Engine not initialized"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        body = {}

    delay_ms = body.get("delay_ms", 0.0)
    exception_rate = body.get("exception_rate", 0.0)
    http_status = body.get("http_status")

    engine.configure_rules(delay_ms=delay_ms, exception_rate=exception_rate, http_status=http_status)
    return JSONResponse({"status": "rules_updated", "stats": engine.get_stats()})


def chaos_routes() -> List[Route]:
    return [
        Route("/admin/chaos", endpoint=get_chaos_status_handler, methods=["GET"]),
        Route("/admin/chaos/enable", endpoint=enable_chaos_handler, methods=["POST"]),
        Route("/admin/chaos/disable", endpoint=disable_chaos_handler, methods=["POST"]),
        Route("/admin/chaos/rules", endpoint=configure_chaos_rules_handler, methods=["POST"]),
    ]
