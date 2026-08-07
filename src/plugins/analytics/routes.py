"""Analytics endpoints, gated by RBAC permissions.

- Global aggregate dashboards + kill-switch require ``analytics:admin`` (superadmin).
- Per-org result rows require ``analytics:read`` and are org-scoped (an org_admin
  sees only its own org); captured bodies (``result_excerpt``) additionally require
  ``analytics:read_content``.
"""
from __future__ import annotations

import logging
from typing import List

from starlette.responses import JSONResponse
from starlette.routing import Route

from ..security import require_permission

log = logging.getLogger("MCP_logger")


def _engine(request):
    return getattr(request.app.state, "analytics", None)


def _perms(request):
    p = getattr(request.state, "principal", None)
    return p, (getattr(p, "permissions", None) or set())


async def summary_handler(request):
    if denied := await require_permission(request, "analytics:admin"):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    return JSONResponse(eng.get_stats())


async def timeseries_handler(request):
    if denied := await require_permission(request, "analytics:admin"):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    return JSONResponse(eng.get_timeseries(request.path_params["name"]))


async def leaderboard_handler(request):
    if denied := await require_permission(request, "analytics:admin"):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    by = request.query_params.get("by", "calls")
    key = {"calls": "most_called", "latency": "slowest",
           "errors": "flakiest", "trending": "trending"}.get(by, "most_called")
    return JSONResponse({"by": by, "leaderboard": eng.get_stats()["leaderboards"][key]})


def _apply_content_policy(data: dict, allowed: bool) -> dict:
    """Strip captured bodies unless the caller holds analytics:read_content."""
    if not allowed:
        for r in data.get("results", []):
            r.pop("result_excerpt", None)
    return data


async def results_handler(request):
    if denied := await require_permission(request, "analytics:read"):
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

    p, perms = _perms(request)
    # RBAC scope: analytics:admin (superadmin) sees all orgs; everyone else is
    # confined to their own org — a mismatched ?org= is ignored, never honored.
    org_scope = None if "analytics:admin" in perms else (getattr(p, "org_id", None) if p else None)
    data = await eng.query_results(
        org_id=org_scope, tool=qp.get("tool", ""), errors_only=errors_only,
        cursor=cursor, limit=limit)
    data = _apply_content_policy(data, "analytics:read_content" in perms)
    return JSONResponse(data)


async def control_handler(request):
    """Runtime kill-switch — global, so it requires analytics:admin."""
    if denied := await require_permission(request, "analytics:admin"):
        return denied
    eng = _engine(request)
    if not eng:
        return JSONResponse({"error": "analytics not enabled"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    state = eng.set_control(enabled=body.get("enabled"), capture_content=body.get("capture_content"))
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
