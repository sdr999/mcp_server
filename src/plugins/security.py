"""Authentication & authorization plumbing.

Three MCP auth modes (``MCP_AUTH_TYPE``): ``none`` | ``api_key`` | ``bearer_jwt``.
The admin API (``/admin/*``) is independently gated by ``MCP_ADMIN_TOKEN``
regardless of the MCP auth mode, and is disabled entirely when that token is
unset. All secret comparisons use ``hmac.compare_digest`` (constant-time).
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional, Tuple

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = logging.getLogger("MCP_logger")

HEALTH_PATH = "/healthz"
READY_PATH = "/readyz"
EXEMPT_PATHS = {HEALTH_PATH, READY_PATH}


def build_mcp(ctx) -> Tuple[FastMCP, Optional[JWTVerifier]]:
    """Return (mcp, jwt_verifier). The verifier is reused to protect the custom
    read routes (/status, /tools, /metrics) in bearer_jwt mode."""
    if ctx.auth_type == "bearer_jwt":
        if not ctx.jwt_audience:
            log.warning(
                "MCP_JWT_AUDIENCE is not set: the JWT verifier accepts tokens issued "
                "for any audience by this IdP. Set MCP_JWT_AUDIENCE to restrict access."
            )
        auth = JWTVerifier(
            jwks_uri=ctx.jwks_url,
            issuer=ctx.jwt_issuer,
            audience=ctx.jwt_audience,
            required_scopes=ctx.jwt_required_scopes,
        )
        return FastMCP(name="Tool Server", auth=auth), auth
    return FastMCP(name="Tool Server"), None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Constant-time API-key check. Exempts liveness/readiness paths for probes."""

    def __init__(self, app, header: str, value: str, exempt=EXEMPT_PATHS):
        super().__init__(app)
        self._header = header.lower()
        self._value = value
        self._exempt = set(exempt)

    async def dispatch(self, request, call_next):
        if request.url.path in self._exempt:
            return await call_next(request)
        provided = request.headers.get(self._header, "")
        if not hmac.compare_digest(provided, self._value):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


async def read_guard(request):
    """Enforce the MCP credential on the custom read routes.

    - api_key mode: already enforced by ApiKeyMiddleware (returns None here).
    - bearer_jwt mode: validate the Bearer JWT with the same verifier used for
      /sse, closing the gap where these routes would otherwise be unauthenticated.
    - none mode: open.
    Returns a 401 JSONResponse when denied, else None.
    """
    st = request.app.state
    if getattr(st, "auth_type", "none") != "bearer_jwt":
        return None
    verifier = getattr(st, "jwt_verifier", None)
    if verifier is None:
        return None
    authz = request.headers.get("authorization", "")
    token = authz[7:] if authz.lower().startswith("bearer ") else ""
    if not token or (await verifier.verify_token(token)) is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


def admin_denied(request):
    """Return a JSONResponse if the admin request is unauthorized, else None."""
    token = getattr(request.app.state, "admin_token", "")
    if not token:
        return JSONResponse({"error": "admin API disabled (set MCP_ADMIN_TOKEN)"}, status_code=503)
    authz = request.headers.get("authorization", "")
    provided = authz[7:] if authz.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(provided, token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None
