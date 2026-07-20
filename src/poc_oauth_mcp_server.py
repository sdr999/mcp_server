"""
POC: Secured MCP server with mock OAuth (client_credentials) auth — SSE transport.
Exposes one tool: check_even_odd(n: int) -> str

This server is both a mock OAuth IdP (POST /token) and an MCP server (GET /sse).
MCP endpoints require a valid Bearer token issued by /token.

Run:
    cd agentic-mcp-server/src
    python poc_oauth_mcp_server.py

Environment:
    POC_OAUTH_CLIENT_ID     - OAuth client ID     (default: poc-oauth-client)
    POC_OAUTH_CLIENT_SECRET - OAuth client secret (default: poc-oauth-secret)
    POC_OAUTH_PORT          - port to listen on   (default: 8004)

Endpoints:
    POST http://localhost:8004/token    (no auth  -- issues Bearer tokens)
    GET  http://localhost:8004/health   (no auth  -- health check)
    GET  http://localhost:8004/sse      (Bearer token required)
    POST http://localhost:8004/messages (Bearer token required)

Smoke test:
    curl -X POST http://localhost:8004/token \\
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

CLIENT_ID: str     = os.environ.get("POC_OAUTH_CLIENT_ID",     "poc-oauth-client")
CLIENT_SECRET: str = os.environ.get("POC_OAUTH_CLIENT_SECRET", "poc-oauth-secret")
MCP_PORT: int      = int(os.environ.get("POC_OAUTH_PORT", "8004"))
BIND_HOST: str     = os.environ.get("POC_BIND_HOST", "0.0.0.0")

# DNS-rebinding guard policy. The MCP SDK arms a localhost-only Host allowlist whenever
# FastMCP's host is loopback, which 421s every remote client. Policy here:
#   bound to 0.0.0.0 / :: -> serving the network on purpose -> guard OFF, any Host ok
#   bound to loopback     -> guard ON, localhost only
# Override with POC_ALLOWED_HOSTS: comma-separated Host values (":*" port wildcard,
# e.g. "10.20.2.185:*"), or "*" to accept any Host.
POC_ALLOWED_HOSTS: str = os.environ.get("POC_ALLOWED_HOSTS", "")

_WILDCARD_BINDS = {"0.0.0.0", "::", ""}
_LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]


def _effective_allowed_hosts() -> list:
    if POC_ALLOWED_HOSTS:
        return [h.strip() for h in POC_ALLOWED_HOSTS.split(",") if h.strip()]
    return ["*"] if BIND_HOST in _WILDCARD_BINDS else list(_LOOPBACK_HOSTS)

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
            await JSONResponse({"status": "ok", "server": "poc-oauth-mcp", "port": MCP_PORT})(
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


def build_transport_security():
    """Build the Host/Origin allowlist for MCP's DNS-rebinding protection."""
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = _effective_allowed_hosts()
    if hosts == ["*"]:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
    )


def build_app():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        name="POC Even Odd OAuth Server",
        host=BIND_HOST,
        port=MCP_PORT,
        transport_security=build_transport_security(),
    )

    @mcp.tool()
    def check_even_odd(n: int) -> str:
        """Returns 'even' or 'odd' for the given integer n.   {"n":5} -> "odd" """
        return "even" if n % 2 == 0 else "odd"

    mcp_asgi = mcp.sse_app()
    return OAuthMcpApp(mcp_asgi, _token_store)


if __name__ == "__main__":
    print(f"[POC-OAUTH] Starting on {BIND_HOST}:{MCP_PORT}  client_id='{CLIENT_ID}'")
    _hosts = _effective_allowed_hosts()
    if _hosts == ["*"]:
        print("[POC-OAUTH]   Allowed Host headers: * (DNS-rebinding guard OFF)")
    else:
        print(f"[POC-OAUTH]   Allowed Host headers: {','.join(_hosts)}")
    print(f"[POC-OAUTH]   POST /token   -> issues Bearer token (no auth)")
    print(f"[POC-OAUTH]   GET  /health  -> health probe (no auth)")
    print(f"[POC-OAUTH]   GET  /sse     -> MCP SSE (Bearer token required)")
    app = build_app()
    uvicorn.run(app, host=BIND_HOST, port=MCP_PORT, log_level="info")
