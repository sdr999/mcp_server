"""
POC: Secured MCP server with mock OAuth (client_credentials) auth — SSE transport, built
on the standalone `fastmcp` package instead of the official `mcp` SDK.

This server is both a mock OAuth IdP (POST /token) and an MCP server (GET /sse).
MCP endpoints require a valid Bearer token issued by /token.

Why this variant exists:
    The `mcp` SDK's FastMCP (`mcp.server.fastmcp`) auto-enables DNS-rebinding protection
    with a localhost-only Host allowlist whenever its host is a loopback address. A server
    bound to 0.0.0.0 therefore answers local clients but rejects every remote one with
    421 Misdirected Request, which surfaces client-side as the opaque
    "ExceptionGroup: unhandled errors in a TaskGroup".

    The `fastmcp` package performs no Host-header validation at all, so that failure mode
    cannot occur here: this server is reachable from any client, whether it addresses the
    server by IP, hostname, or through a proxy / load balancer. Access is gated by the
    OAuth token, not by the Host header.

    Compare with poc_oauth_mcp_server.py, which is the same POC on the `mcp` SDK and needs
    explicit transport_security settings to be reachable remotely.

Run:
    cd agentic-mcp-server/src
    python poc_oauth_fastmcp_server.py

Environment:
    POC_OAUTH_CLIENT_ID      - OAuth client ID     (default: poc-oauth-client)
    POC_OAUTH_CLIENT_SECRET  - OAuth client secret (default: poc-oauth-secret)
    POC_OAUTH_FASTMCP_PORT   - port to listen on   (default: 8006)
    POC_BIND_HOST            - interface to bind   (default: 0.0.0.0)

Endpoints:
    POST http://<host>:8006/token    (no auth  -- issues Bearer tokens)
    GET  http://<host>:8006/health   (no auth  -- health check)
    GET  http://<host>:8006/sse      (Bearer token required)
    POST http://<host>:8006/messages (Bearer token required)

Smoke test:
    curl -X POST http://localhost:8006/token \\
      -H "Content-Type: application/x-www-form-urlencoded" \\
      -d "grant_type=client_credentials&client_id=poc-oauth-client&client_secret=poc-oauth-secret"
    # -> {"access_token": "<hex>", "token_type": "bearer", "expires_in": 3600}
"""
import os
import secrets
import time
from urllib.parse import parse_qs

import uvicorn
from starlette.responses import JSONResponse

from fastmcp import FastMCP

CLIENT_ID: str     = os.environ.get("POC_OAUTH_CLIENT_ID",     "poc-oauth-client")
CLIENT_SECRET: str = os.environ.get("POC_OAUTH_CLIENT_SECRET", "poc-oauth-secret")
MCP_PORT: int      = int(os.environ.get("POC_OAUTH_FASTMCP_PORT", "8006"))
BIND_HOST: str     = os.environ.get("POC_BIND_HOST", "0.0.0.0")

# In-memory token store:  token_hex(32) -> expiry_epoch
_token_store: dict = {}


class OAuthMcpApp:
    """
    Combined ASGI app — pure ASGI (no BaseHTTPMiddleware) so SSE streaming is not buffered.

    Routing:
      POST /token   -> issue access_token (no auth required)
      GET  /health  -> health probe       (no auth required)
      *             -> FastMCP SSE ASGI   (Bearer token required)
    """

    PUBLIC_PATHS = {"/token", "/health"}

    def __init__(self, mcp_asgi, token_store: dict):
        self.mcp_asgi = mcp_asgi
        self._ts = token_store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # lifespan and other scope types pass straight through to mcp_asgi
            await self.mcp_asgi(scope, receive, send)
            return

        path = scope.get("path", "")

        if path == "/health":
            await JSONResponse({"status": "ok", "server": "poc-oauth-fastmcp", "port": MCP_PORT})(
                scope, receive, send
            )
            return

        if path == "/token":
            await self._handle_token(scope, receive, send)
            return

        # All other paths (/sse, /messages, ...) require a valid Bearer token
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode()
        if not auth.startswith("Bearer "):
            await JSONResponse({"error": "Unauthorized"}, status_code=401)(scope, receive, send)
            return
        token = auth[7:]
        if token not in self._ts or self._ts[token] <= time.time():
            await JSONResponse({"error": "Unauthorized"}, status_code=401)(scope, receive, send)
            return

        await self.mcp_asgi(scope, receive, send)

    async def _handle_token(self, scope, receive, send):
        """Handle POST /token — OAuth 2.0 client_credentials grant."""
        body = b""
        more = True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)

        params = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        grant_type    = params.get("grant_type", "")
        client_id     = params.get("client_id", "")
        client_secret = params.get("client_secret", "")

        if (grant_type == "client_credentials"
                and client_id == CLIENT_ID
                and client_secret == CLIENT_SECRET):
            token = secrets.token_hex(32)
            self._ts[token] = time.time() + 3600
            resp = JSONResponse(
                {"access_token": token, "token_type": "bearer", "expires_in": 3600}
            )
        else:
            resp = JSONResponse({"error": "invalid_client"}, status_code=401)

        await resp(scope, receive, send)


def build_app():
    mcp = FastMCP(name="POC Even Odd OAuth FastMCP Server")

    @mcp.tool
    def check_even_odd(n: int) -> str:
        """Returns 'even' or 'odd' for the given integer n.   {"n":5} -> "odd" """
        return "even" if n % 2 == 0 else "odd"

    # No transport_security to configure: fastmcp does not validate the Host header, so
    # remote clients are never rejected with 421 regardless of how they address this server.
    mcp_asgi = mcp.http_app(transport="sse")
    return OAuthMcpApp(mcp_asgi, _token_store)


if __name__ == "__main__":
    print(f"[POC-OAUTH-FASTMCP] Starting on {BIND_HOST}:{MCP_PORT}  client_id='{CLIENT_ID}'")
    print("[POC-OAUTH-FASTMCP]   Host header validation: none (fastmcp) — reachable from anywhere")
    print("[POC-OAUTH-FASTMCP]   POST /token   -> issues Bearer token (no auth)")
    print("[POC-OAUTH-FASTMCP]   GET  /health  -> health probe (no auth)")
    print("[POC-OAUTH-FASTMCP]   GET  /sse     -> MCP SSE (Bearer token required)")
    uvicorn.run(build_app(), host=BIND_HOST, port=MCP_PORT, log_level="info")
