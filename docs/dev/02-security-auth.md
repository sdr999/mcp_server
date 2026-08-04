# 02 — Security & Auth (`plugins/security.py`)

**Job:** authenticate callers, and let each route's required credential be
configured independently. Two credential types, three per-route policies.

## Credentials

| Credential | Set by | Used for |
|------------|--------|----------|
| **MCP credential** | `MCP_AUTH_TYPE` = `none` / `api_key` / `bearer_jwt` | the MCP protocol (`/sse`, `/messages`) and any route with policy `mcp` |
| **Admin token** | `MCP_ADMIN_TOKEN` | `/admin/*` (always) and any route with policy `admin` |

- `api_key` — a shared secret in a header, compared with `hmac.compare_digest`.
- `bearer_jwt` — a JWT validated against a JWKS (issuer / audience / scopes) via
  FastMCP's `JWTVerifier`.

## Per-route auth policies (configurable)

Each custom route reads a **policy** — `none` | `mcp` | `admin` — from
`app.state`, defaulting to the historical behavior. This is the "make it
configurable" surface:

| Env var | Route(s) | Default |
|---------|----------|---------|
| `MCP_READ_AUTH` | `/status`, `/tools` | `mcp` |
| `MCP_METRICS_AUTH` | `/metrics` | `mcp` (set `none` for open Prometheus scraping) |
| `MCP_TOOL_CALL_AUTH` | `POST /tools/{name}/call` | `mcp` (set `admin` to restrict execution) |
| `MCP_UPSTREAM_AUTH` | `/mcp/upstreams*` | `mcp` |

`/admin/*` is **always** gated by `MCP_ADMIN_TOKEN` (not configurable — it's the
security anchor), and `/sse` + `/messages` **always** require the MCP credential.

## The one dispatcher: `enforce`

Every custom route calls this; it resolves the policy against the active auth
mode. This is the single place auth decisions are made.

```python
async def enforce(request, policy: str):
    if policy == "none":
        return None
    if policy == "admin":
        return admin_denied(request)                 # requires MCP_ADMIN_TOKEN
    mode = getattr(request.app.state, "auth_type", "none")   # policy == "mcp"
    if mode == "api_key":
        return None if _api_key_ok(request) else JSONResponse({"error": "Unauthorized"}, status_code=401)
    if mode == "bearer_jwt":
        return None if await _jwt_ok(request) else JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None                                       # none mode: open
```

Usage in a route:

```python
async def _metrics(request):
    if (denied := await enforce(request, request.app.state.metrics_auth)) is not None:
        return denied
    return PlainTextResponse(METRICS.render(), ...)
```

## Why the middleware got smaller

The `ApiKeyMiddleware` used to guard *all* non-exempt routes, which meant a
route's auth couldn't be configured (the middleware always ran first) and the
admin `Authorization` header collided with the api key. Now the middleware
guards **only the MCP protocol endpoints** — everything else self-enforces via
`enforce`, which is what makes per-route policies possible.

```python
class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/sse") or path.startswith("/messages"):
            provided = request.headers.get(self._header, "")
            if not hmac.compare_digest(provided, self._value):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)
```

(FastMCP auths `/sse` + `/messages` itself in `bearer_jwt` mode; this middleware
covers the `api_key` mode where it doesn't.)

## Building the MCP server + JWT verifier

```python
def build_mcp(ctx):
    if ctx.auth_type == "bearer_jwt":
        if not ctx.jwt_audience:
            log.warning("MCP_JWT_AUDIENCE is not set: accepts tokens for any audience ...")
        auth = JWTVerifier(jwks_uri=ctx.jwks_url, issuer=ctx.jwt_issuer,
                           audience=ctx.jwt_audience, required_scopes=ctx.jwt_required_scopes)
        return FastMCP(name="Tool Server", auth=auth), auth
    return FastMCP(name="Tool Server"), None
```

The returned verifier is stashed on `app.state.jwt_verifier` and reused by
`_jwt_ok` so the custom routes validate JWTs with the same rules as `/sse`.

## The admin gate

```python
def admin_denied(request):
    token = getattr(request.app.state, "admin_token", "")
    if not token:
        return JSONResponse({"error": "admin API disabled (set MCP_ADMIN_TOKEN)"}, status_code=503)
    provided = ... # Bearer token from Authorization
    if not hmac.compare_digest(provided, token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None
```

## Endpoint × credential matrix (with defaults)

| Endpoint | none | api_key | bearer_jwt |
|----------|------|---------|------------|
| `/healthz`, `/readyz` | open | open | open |
| `/sse`, `/messages` | open | api key (middleware) | JWT (FastMCP) |
| `/status`, `/tools` | `MCP_READ_AUTH` | ″ | ″ |
| `/metrics` | `MCP_METRICS_AUTH` | ″ | ″ |
| `POST /tools/{name}/call` | `MCP_TOOL_CALL_AUTH` | ″ | ″ |
| `/mcp/upstreams*` | `MCP_UPSTREAM_AUTH` | ″ | ″ |
| `/admin/*` | `MCP_ADMIN_TOKEN` | ″ | ″ |

## Thorough security review (findings & posture)

**Strengths**
- All secret comparisons are constant-time (`hmac.compare_digest`) — api key,
  admin token, signed-tool hashes/HMAC.
- Auth decisions are centralized in `enforce` / `admin_denied` — one place to
  audit, no per-route drift.
- Fail-closed defaults: `bearer_jwt` with a missing verifier denies; an unset
  admin token disables `/admin/*` (503) rather than opening it.
- Input that reaches dangerous sinks is grammar-validated first: `--config`
  paths (traversal-safe), pip specs (injection-safe, doc 06), tool names
  (`^[A-Za-z_]\w{0,63}$`).
- Defaults are safe: every configurable route defaults to `mcp`; onboarding is
  admin-only; signed-tools and sandbox are available for hardening.

**Residual risks / operator responsibilities (documented, by design)**
- The **admin token is host code-execution access** — it can onboard code,
  `pip install`, and (if `MCP_TOOL_CALL_AUTH=admin`) run tools. Treat it as a
  root credential; prefer per-environment tokens and rotate.
- Onboarding **runs submitted code and pip in the server's own environment**.
  For untrusted submitters, combine `MCP_SANDBOX_TOOLS`,
  `MCP_REQUIRE_SIGNED_TOOLS`, `MCP_TOOL_INSTALL_ONLY_BINARY`, and a locked-down
  container/user (doc 07/08).
- **Federation trust is transitive**: calling an upstream executes on *their*
  server with whatever credential you configured. Only add upstreams you trust;
  scope `MCP_UPSTREAM_AUTH` appropriately.
- `MCP_JWT_AUDIENCE` unset ⇒ any token that IdP minted is accepted — the server
  warns; always set it in production.
- There is **no built-in rate limiting or per-caller identity** (one shared
  admin token) — put the server behind a gateway if you need those.

**Recommended production baseline**
```bash
MCP_AUTH_TYPE=bearer_jwt  JWKS_URL=...  MCP_JWT_AUDIENCE=mcp-tools
MCP_ADMIN_TOKEN=$(openssl rand -hex 32)
MCP_REQUIRE_SIGNED_TOOLS=true         # or MCP_SANDBOX_TOOLS=true for onboarding
MCP_TOOL_INSTALL_ONLY_BINARY=true
# open only metrics to your scraper's network:
MCP_METRICS_AUTH=none                 # (behind a network ACL) — otherwise keep 'mcp'
```
