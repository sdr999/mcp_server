"""Admin-gated analytics endpoints."""
from __future__ import annotations

import logging
from typing import List

from starlette.responses import JSONResponse
from starlette.routing import Route

from ..security import admin_denied

log = logging.getLogger("MCP_logger")


def _engine(request):
    return getattr(request.app.state, "analytics", None)


async def summary_handler(request):
    if denied := await admin_denied(request):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    return JSONResponse(eng.get_stats())


async def timeseries_handler(request):
    if denied := await admin_denied(request):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    return JSONResponse(eng.get_timeseries(request.path_params["name"]))


async def leaderboard_handler(request):
    if denied := await admin_denied(request):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    by = request.query_params.get("by", "calls")
    key = {"calls": "most_called", "latency": "slowest",
           "errors": "flakiest", "trending": "trending"}.get(by, "most_called")
    return JSONResponse({"by": by, "leaderboard": eng.get_stats()["leaderboards"][key]})


async def results_handler(request):
    if denied := await admin_denied(request):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    qp = request.query_params
    try:
        cursor = max(0, int(qp.get("cursor", 0)))
    except ValueError:
        cursor = 0
    try:
        limit = int(qp.get("limit", 50))
    except ValueError:
        limit = 50
    errors_only = qp.get("errors_only", "").lower() in ("1", "true", "yes")
    # RBAC scope: superadmin sees all orgs; anyone else is confined to their own
    # org (a mismatched ?org= is ignored, never honored). Enforced in the store query.
    p = getattr(request.state, "principal", None)
    perms = getattr(p, "permissions", set()) or set()
    roles = getattr(p, "roles", []) or []
    is_super = ("platform:admin" in perms) or ("platform_superadmin" in roles)
    org_scope = None if is_super else (getattr(p, "org_id", None) if p else None)
    data = await eng.query_results(
        org_id=org_scope, tool=qp.get("tool", ""), errors_only=errors_only,
        cursor=cursor, limit=limit)
    return JSONResponse(data)


async def control_handler(request):
    """Runtime kill-switch for incident response (disable capture without restart)."""
    if denied := await admin_denied(request):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = body.get("enabled")
    capture = body.get("capture_content")
    state = eng.set_control(enabled=enabled, capture_content=capture)
    log.info("analytics control updated: %s", state)
    return JSONResponse(state)


def analytics_routes() -> List[Route]:
    return [
        Route("/admin/analytics/summary", endpoint=summary_handler, methods=["GET"]),
        Route("/admin/analytics/tools/{name}/timeseries", endpoint=timeseries_handler, methods=["GET"]),
        Route("/admin/analytics/leaderboard", endpoint=leaderboard_handler, methods=["GET"]),
        Route("/admin/analytics/results", endpoint=results_handler, methods=["GET"]),
        Route("/admin/analytics/control", endpoint=control_handler, methods=["POST"]),
    ]
