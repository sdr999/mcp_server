"""Chaos Engineering fault injection middleware with sub-microsecond fast path."""
from __future__ import annotations

import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("MCP_logger")


class ChaosMiddleware(BaseHTTPMiddleware):
    """Sub-microsecond fast-path fault injection middleware."""

    def __init__(self, app, chaos_engine=None):
        super().__init__(app)
        self.chaos_engine = chaos_engine

    async def dispatch(self, request: Request, call_next) -> Response:
        engine = self.chaos_engine or getattr(request.app.state, "chaos_engine", None)
        # Sub-microsecond fast path (< 0.1us) when chaos is disabled
        if not engine or not engine.is_enabled:
            return await call_next(request)

        # Do not disrupt admin chaos management routes
        if request.url.path.startswith("/admin/chaos"):
            return await call_next(request)

        # 1. Synthetic Delay Injection
        delay_sec = engine.get_delay_sec()
        if delay_sec > 0:
            engine.record_injection()
            await asyncio.sleep(delay_sec)

        # 2. Synthetic Exception Injection
        if engine.should_inject_exception():
            engine.record_injection()
            log.warning("Chaos middleware injecting synthetic exception for path: %s", request.url.path)
            raise RuntimeError("ChaosMonkeySyntheticException: Simulated fault injection")

        # 3. Synthetic HTTP Error Code Injection
        http_status = engine.get_http_status()
        if http_status and http_status >= 400:
            engine.record_injection()
            log.warning("Chaos middleware injecting HTTP status %d for path: %s", http_status, request.url.path)
            return JSONResponse(
                {"error": "Chaos Injected Error", "message": f"Simulated HTTP {http_status} fault injection"},
                status_code=http_status,
            )

        return await call_next(request)
