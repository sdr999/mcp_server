"""Starlette middleware for rate limiting and circuit breaking."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from .circuit_breaker import CircuitBreakerOpenError
from .rate_limiter import RateLimitExceededError, RateLimiterRegistry

log = logging.getLogger("MCP_logger")

EXEMPT_PATHS = {"/healthz", "/readyz", "/metrics", "/docs", "/openapi.json"}


class ReliabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate_limiter_registry: RateLimiterRegistry):
        super().__init__(app)
        self.rate_limiter_registry = rate_limiter_registry

    async def dispatch(self, request, call_next) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # Extract tenant_id from request.state set by IdentityMiddleware (runs before us via LIFO)
        tenant_id = getattr(request.state, "tenant_id", "") or ""

        # 1. Rate Limit Check
        try:
            allowed, remaining, reset_in = await self.rate_limiter_registry.enforcer.check_rate_limit(tenant_id)
        except RateLimitExceededError as exc:
            reset_in = getattr(exc, "reset_in", 60.0)
            return JSONResponse(
                {"error": "Too Many Requests", "message": str(exc)},
                status_code=429,
                headers={
                    "Retry-After": str(int(reset_in)),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + reset_in)),
                },
            )


        # 2. Downstream handler execution wrapped with circuit breaker handling
        try:
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response
        except CircuitBreakerOpenError as exc:
            return JSONResponse(
                {"error": "Service Unavailable", "message": str(exc)},
                status_code=503,
                headers={"Retry-After": "30"},
            )
