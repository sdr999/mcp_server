# 02 — Security & Auth (`plugins/security.py`)

**Job:** enforce the MCP credential on protected routes and gate the admin API,
in three modes, with constant-time secret comparisons.

| Mode (`MCP_AUTH_TYPE`) | Server enforces | Client sends |
|------------------------|-----------------|--------------|
| `none` | nothing | nothing |
| `api_key` | a shared secret in a header | that header |
| `bearer_jwt` | a JWT validated against a JWKS (issuer/audience/scopes) | `Authorization: Bearer <jwt>` |

Two independent layers:
1. **MCP credential** — protects `/sse`, `/messages/`, `/status`, `/tools`, `/metrics`.
2. **Admin token** (`MCP_ADMIN_TOKEN`) — protects `/admin/*`, *independent of* the MCP mode.

## Building the MCP server + JWT verifier

In `bearer_jwt` mode we hand FastMCP a `JWTVerifier` (it protects `/sse` and
`/messages/`), and we **return the same verifier** so the custom read routes can
reuse it (see `read_guard` below). A missing audience is a footgun (accept any
token from that IdP), so we warn loudly.

```python
def build_mcp(ctx) -> Tuple[FastMCP, Optional[JWTVerifier]]:
    if ctx.auth_type == "bearer_jwt":
        if not ctx.jwt_audience:
            log.warning("MCP_JWT_AUDIENCE is not set: the JWT verifier accepts tokens "
                        "issued for any audience by this IdP. ...")
        auth = JWTVerifier(jwks_uri=ctx.jwks_url, issuer=ctx.jwt_issuer,
                           audience=ctx.jwt_audience, required_scopes=ctx.jwt_required_scopes)
        return FastMCP(name="Tool Server", auth=auth), auth
    return FastMCP(name="Tool Server"), None
```

## API-key middleware (constant-time, with exemptions)

Wraps the whole ASGI app in `api_key` mode. Two exemption classes:
- **health/readiness** — probes must work without a credential.
- **`/admin/*`** — these carry their own admin token; exempting them prevents
  the admin `Authorization: Bearer` from colliding with the api key (whose
  default header is *also* `Authorization`). Without this, admin routes were
  unreachable in `api_key` mode.

```python
class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in self._exempt or path.startswith("/admin/"):
            return await call_next(request)
        provided = request.headers.get(self._header, "")
        if not hmac.compare_digest(provided, self._value):   # constant-time
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)
```

> **Why `hmac.compare_digest`?** A normal `==` on secrets leaks length/prefix
> timing. Every secret comparison in this file uses the constant-time variant.

## `read_guard` — closing the read-route gap in JWT mode

The custom routes (`/status`, `/tools`, `/metrics`) are plain Starlette routes,
*not* MCP endpoints, so FastMCP's JWT auth doesn't cover them. In `api_key`
mode the middleware already did the check; in `bearer_jwt` mode we validate the
Bearer token here with the same verifier used for `/sse`.

```python
async def read_guard(request):
    st = request.app.state
    if getattr(st, "auth_type", "none") != "bearer_jwt":
        return None                          # none mode: open; api_key: middleware did it
    verifier = getattr(st, "jwt_verifier", None)
    if verifier is None:
        return None
    authz = request.headers.get("authorization", "")
    token = authz[7:] if authz.lower().startswith("bearer ") else ""
    if not token or (await verifier.verify_token(token)) is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None
```

Each read route calls it first:

```python
async def _status(request):
    if (denied := await read_guard(request)) is not None:
        return denied
    ...
```

## `admin_denied` — the admin gate

Applied at the top of every `/admin/*` handler. Three outcomes:
`503` (admin API disabled — token unset), `401` (wrong/missing token), or
`None` (allowed).

```python
def admin_denied(request):
    token = getattr(request.app.state, "admin_token", "")
    if not token:
        return JSONResponse({"error": "admin API disabled (set MCP_ADMIN_TOKEN)"}, status_code=503)
    authz = request.headers.get("authorization", "")
    provided = authz[7:] if authz.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(provided, token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None
```

## Endpoint × mode matrix

| Endpoint | `none` | `api_key` | `bearer_jwt` |
|----------|--------|-----------|--------------|
| `/healthz`, `/readyz` | open | open (exempt) | open (exempt) |
| `/sse`, `/messages/` | open | api key | JWT (FastMCP) |
| `/status`, `/tools`, `/metrics` | open | api key (middleware) | JWT (`read_guard`) |
| `/admin/*` | `MCP_ADMIN_TOKEN` | `MCP_ADMIN_TOKEN` | `MCP_ADMIN_TOKEN` |

## Gotchas / design notes

- The admin token is effectively **host code-execution access** (it can onboard
  and run tool code, pip-install, etc.). Treat it like a root credential.
- `app.state` carries `auth_type`, `jwt_verifier`, and `admin_token` so the
  route functions (which only receive a `request`) can reach them.
- Full setup examples (curl, Python MCP client, IdP token flow) live in
  `MCP_AUTH_GUIDE.md`.
