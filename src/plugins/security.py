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
    """Constant-time API-key check for the **MCP protocol endpoints** only
    (``/sse``, ``/messages``). FastMCP auths those itself in ``bearer_jwt`` mode
    but not in ``api_key`` mode, so this fills that gap. Every other route
    (health, admin, and the custom read/exec/upstream routes) enforces its own
    configurable policy via :func:`enforce`, so the middleware does not touch
    them — that's what makes per-route auth configurable."""

    def __init__(self, app, header: str, value: str, protected_prefixes=("/sse", "/messages")):
        super().__init__(app)
        self._header = header.lower()
        self._value = value
        # The MCP protocol path(s) depend on the transport: /sse + /messages for
        # SSE, /mcp for streamable HTTP. build_app passes the right ones.
        self._protected = tuple(protected_prefixes)

    async def dispatch(self, request, call_next):
        if request.url.path.startswith(self._protected):
            provided = request.headers.get(self._header, "")
            if not hmac.compare_digest(provided, self._value):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def _api_key_ok(request) -> bool:
    st = request.app.state
    provided = request.headers.get(getattr(st, "api_key_header", "authorization"), "")
    return hmac.compare_digest(provided, getattr(st, "api_key_value", ""))


async def _jwt_ok(request) -> bool:
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        return False                          # bearer_jwt configured but no verifier → fail closed
    authz = request.headers.get("authorization", "")
    token = authz[7:] if authz.lower().startswith("bearer ") else ""
    return bool(token) and (await verifier.verify_token(token)) is not None


async def enforce(request, policy: str):
    """Apply a per-route auth policy. Returns a 401/503 JSONResponse when denied,
    else None.

    - ``"none"``  → open.
    - ``"admin"`` → requires ``MCP_ADMIN_TOKEN`` (same gate as ``/admin/*``).
    - ``"mcp"``   → requires the MCP credential for the active ``MCP_AUTH_TYPE``:
      nothing in ``none`` mode, the api key in ``api_key`` mode, a valid JWT in
      ``bearer_jwt`` mode.
    """
    if policy == "none":
        return None
    if policy == "admin":
        return admin_denied(request)
    mode = getattr(request.app.state, "auth_type", "none")
    if mode == "api_key":
        return None if _api_key_ok(request) else JSONResponse({"error": "Unauthorized"}, status_code=401)
    if mode == "bearer_jwt":
        return None if await _jwt_ok(request) else JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None                               # none mode: open


async def read_guard(request):
    """Back-compat alias for ``enforce(request, "mcp")``."""
    return await enforce(request, "mcp")


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
