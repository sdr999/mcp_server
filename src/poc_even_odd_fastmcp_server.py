"""
POC: Secured MCP server with static Bearer API key auth — SSE transport, built on the
standalone `fastmcp` package instead of the official `mcp` SDK.

Why this variant exists:
    The `mcp` SDK's FastMCP (`mcp.server.fastmcp`) auto-enables DNS-rebinding protection
    with a localhost-only Host allowlist whenever its host is a loopback address. A server
    bound to 0.0.0.0 therefore answers local clients but rejects every remote one with
    421 Misdirected Request, which surfaces client-side as the opaque
    "ExceptionGroup: unhandled errors in a TaskGroup".

    The `fastmcp` package performs no Host-header validation at all, so that failure mode
    cannot occur here: this server is reachable from any client, whether it addresses the
    server by IP, hostname, or through a proxy / load balancer. Access is gated by the
    bearer token, not by the Host header.

    Compare with poc_even_odd_server.py, which is the same POC on the `mcp` SDK and needs
    explicit transport_security settings to be reachable remotely.

Run:
    cd agentic-mcp-server/src
    python poc_even_odd_fastmcp_server.py

Environment:
    POC_API_KEY       - expected Bearer token value (default: poc-secret-123)
    POC_FASTMCP_PORT  - port to listen on           (default: 8005)
    POC_BIND_HOST     - interface to bind           (default: 0.0.0.0)

MCP endpoint:  GET  http://<host>:8005/sse
Health check:  GET  http://<host>:8005/health

Verify unauthenticated call is rejected:
    curl -s -o /dev/null -w '%{http_code}' http://localhost:8005/sse    -> 401
Verify authenticated call succeeds:
    curl -s -H "Authorization: Bearer poc-secret-123" http://localhost:8005/sse
"""
import os

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from fastmcp import FastMCP

STATIC_TOKEN: str = os.environ.get("POC_API_KEY", "poc-secret-123")
MCP_PORT: int = int(os.environ.get("POC_FASTMCP_PORT", "8005"))
BIND_HOST: str = os.environ.get("POC_BIND_HOST", "0.0.0.0")


class StaticBearerMiddleware:
    """Pure ASGI middleware — avoids BaseHTTPMiddleware buffering that breaks SSE streaming."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            if scope.get("path") == "/health":
                await self.app(scope, receive, send)
                return
            auth = headers.get(b"authorization", b"").decode()
            if auth != f"Bearer {STATIC_TOKEN}":
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        # lifespan scope passes straight through: the SSE app's session manager starts there
        await self.app(scope, receive, send)


def build_app():
    mcp = FastMCP(name="POC Even Odd FastMCP Server")

    @mcp.tool
    def check_even_odd(n: int) -> str:
        """Returns 'even' or 'odd' for the given integer n."""
        return "even" if n % 2 == 0 else "odd"

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    # No transport_security to configure: fastmcp does not validate the Host header, so
    # remote clients are never rejected with 421 regardless of how they address this server.
    asgi_app = mcp.http_app(transport="sse")
    return StaticBearerMiddleware(asgi_app)


if __name__ == "__main__":
    print(f"[POC-FASTMCP] Starting on {BIND_HOST}:{MCP_PORT}  token='{STATIC_TOKEN}'")
    print("[POC-FASTMCP] Host header validation: none (fastmcp) — reachable from anywhere")
    uvicorn.run(build_app(), host=BIND_HOST, port=MCP_PORT, log_level="info")
