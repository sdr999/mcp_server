"""
POC: Secured MCP server with static Bearer API key auth — Streamable HTTP transport.
Exposes one tool: check_even_odd(n: int) -> str

Run:
    cd agentic-mcp-server/src
    python poc_even_odd_http_server.py

Environment:
    POC_API_KEY    - expected Authorization header value (default: poc-secret-123)
    POC_HTTP_PORT  - port to listen on                   (default: 8003)

MCP endpoint:  POST http://localhost:8003/mcp
Health check:  GET  http://localhost:8003/health

Verify unauthenticated call is rejected:
    curl -s -X POST http://localhost:8003/mcp                           -> 401
Verify authenticated MCP init succeeds:
    curl -s -X POST -H "Authorization: Bearer poc-secret-123" \\
         -H "Content-Type: application/json" \\
         -d '{"jsonrpc":"2.0","method":"initialize","params":{},"id":1}' \\
         http://localhost:8003/mcp
"""
import os
import uvicorn
from starlette.responses import JSONResponse

STATIC_TOKEN: str = os.environ.get("POC_API_KEY", "poc-secret-123")
MCP_PORT: int = int(os.environ.get("POC_HTTP_PORT", "8003"))
BIND_HOST: str = os.environ.get("POC_BIND_HOST", "0.0.0.0")

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


class StaticBearerMiddleware:
    """Pure ASGI middleware for HTTP transport — validates Authorization header."""

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
        await self.app(scope, receive, send)


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
        name="POC Even Odd HTTP Server",
        host=BIND_HOST,
        port=MCP_PORT,
        transport_security=build_transport_security(),
    )

    @mcp.tool()
    def check_even_odd(n: int) -> str:
        """Returns 'even' or 'odd' for the given integer n."""
        return "even" if n % 2 == 0 else "odd"

    asgi_app = mcp.streamable_http_app()
    return StaticBearerMiddleware(asgi_app)


if __name__ == "__main__":
    print(f"[POC-HTTP] Starting on {BIND_HOST}:{MCP_PORT}  token='{STATIC_TOKEN}'")
    _hosts = _effective_allowed_hosts()
    if _hosts == ["*"]:
        print("[POC-HTTP] Allowed Host headers: * (DNS-rebinding guard OFF)")
    else:
        print(f"[POC-HTTP] Allowed Host headers: {','.join(_hosts)}")
    app = build_app()
    uvicorn.run(app, host=BIND_HOST, port=MCP_PORT, log_level="info")
