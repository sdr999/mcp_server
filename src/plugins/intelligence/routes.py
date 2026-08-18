"""Admin endpoints for intelligence log search."""
from __future__ import annotations

import logging
from typing import List
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..security import admin_denied

log = logging.getLogger("MCP_logger")


async def log_search_handler(request):
    if denied := await admin_denied(request):
        return denied
    index = getattr(request.app.state, "log_search_index", None)
    if not index:
        return JSONResponse({"error": "Log Search Index not initialized"}, status_code=503)

    query = request.query_params.get("q", "").strip()
    try:
        limit = min(50, max(1, int(request.query_params.get("limit", 10))))
    except ValueError:
        limit = 10

    results = index.search(query=query, limit=limit)
    return JSONResponse(
        {
            "query": query,
            "results_count": len(results),
            "results": results,
            "stats": index.get_stats(),
        }
    )


def intelligence_routes() -> List[Route]:
    return [
        Route("/admin/intelligence/search", endpoint=log_search_handler, methods=["GET"]),
    ]
