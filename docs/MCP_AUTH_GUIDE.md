# MCP Authorization Guide — API key & OAuth

How to secure the MCP tool server and how clients authenticate to it. Both modes
are implemented and verified.

| Mode | Server enforces | Client sends |
|------|-----------------|--------------|
| `none` | nothing | nothing |
| `api_key` | a shared secret in a header (constant-time compare) | that header |
| `bearer_jwt` (OAuth) | a JWT access token validated against a JWKS (issuer/audience/scopes) | `Authorization: Bearer <token>` |

- **Resource server** = `agentic-mcp-server` — *validates* the incoming credential.
- **Client** = an MCP client, or the `agentic-configuration-service` when it onboards/
  executes tools — *obtains and sends* the credential (for OAuth it fetches the token).

> [!NOTE]
> For enterprise multi-tenancy, pluggable stores (SQLite, MongoDB), 5-tier RBAC policy evaluation, catalog scoping, and ABAC attribute rules, see the dedicated [Multi-Tenancy & RBAC Architecture Guide](MULTI_TENANCY_RBAC_GUIDE.md).

---


## 1. API key

### Server configuration
```bash
MCP_AUTH_TYPE=api_key
MCP_API_KEY_HEADER=x-api-key      # default: Authorization
MCP_API_KEY_VALUE=secret123       # the shared secret (store securely)
```
The check is constant-time (`hmac.compare_digest`). `/healthz` and `/readyz` are always
exempt so health probes work; every other route requires the header.

### Client usage
```bash
# rejected
curl -s -o /dev/null -w "%{http_code}\n" http://host:8000/status
# 401

# accepted
curl -s -H "x-api-key: secret123" http://host:8000/status
# {"ready":true,"auth":"api_key",...}
```
MCP (SSE) client:
```python
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async with sse_client("http://host:8000/sse", headers={"x-api-key": "secret123"}) as (r, w):
    async with ClientSession(r, w) as s:
        await s.initialize()
        await s.list_tools()
```

**Verified:** `/healthz`→200 (no key); `/status` no key→401, wrong key→401, correct key→200.

---

## 2. OAuth (`bearer_jwt`)

The server acts as an OAuth **resource server**: it does not issue tokens; it validates
the JWT access token your Identity Provider (Cognito, Auth0, Entra, …) issued, by
fetching the IdP's public keys from its JWKS endpoint.

### Server configuration
```bash
MCP_AUTH_TYPE=bearer_jwt
JWKS_URL=https://<idp>/.well-known/jwks.json     # required
# Hardening — bind the token so tokens for other services are rejected:
MCP_JWT_ISSUER=https://<idp>/                     # expected `iss`
MCP_JWT_AUDIENCE=mcp-tools                         # expected `aud`  (set this!)
MCP_JWT_REQUIRED_SCOPES=tools.invoke               # comma-separated, optional
```
Validation performed by FastMCP's `JWTVerifier` (RS256): signature via JWKS, expiry,
and — when configured — issuer, audience, and required scopes. If `MCP_JWT_AUDIENCE`
is unset the server logs a warning, because it would then accept any token that IdP
minted for *any* service.

Only the MCP protocol endpoints (`/sse`, `/messages/`) are JWT-protected; `/healthz`
and `/readyz` stay open for probes.

### Client usage — obtain a token, then call
```bash
# 1. Get an access token from your IdP (client_credentials example)
TOKEN=$(curl -s -X POST "$IDP_TOKEN_URL" \
  -d grant_type=client_credentials \
  -d client_id=$CLIENT_ID -d client_secret=$CLIENT_SECRET \
  -d scope=tools.invoke | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Call the MCP server with it
curl -N -H "Authorization: Bearer $TOKEN" http://host:8000/sse
```
```python
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async with sse_client("http://host:8000/sse",
                      headers={"Authorization": f"Bearer {TOKEN}"}) as (r, w):
    async with ClientSession(r, w) as s:
        await s.initialize()
        await s.list_tools()
```

**Verified:** server boots with `auth=bearer_jwt`; `/sse` returns **401** with no token
and with an invalid token. A token signed by the configured IdP with a matching
audience is accepted.

---

## 3. Onboarding / executing tools through the config service

When `agentic-configuration-service` connects to a secured MCP server (to onboard its
tools or execute one), it is the **client** and carries an `auth_config` describing how
to authenticate. It resolves that into headers (`utils/mcp_auth_resolver.py`).

`auth_config` (McpAuthConfig) shapes:
```jsonc
// api_key — one or more header pairs injected verbatim
{ "auth_type": "api_key",
  "api_keys": [{ "name": "x-api-key", "value": "secret123" }] }

// oauth — client_credentials; the service fetches, caches, and refreshes the token
{ "auth_type": "oauth",
  "token_url": "https://<idp>/oauth/token",
  "client_id": "…", "client_secret": "…",
  "scope": "tools.invoke",
  "jwks_url": "https://<idp>/.well-known/jwks.json" }   // used when it deploys a server
```
- `api_key` → the service sends the configured header on every MCP call.
- `oauth` → the service performs the `client_credentials` grant, caches the token
  (30 s safety buffer, auto-refresh), and sends `Authorization: Bearer <token>`.
- Onboarding request accepts `auth_config` inline; it is stored (secrets encrypted at
  rest / redacted in API responses) and reused for later tool execution.

Example onboard call with OAuth:
```bash
curl -X POST http://config-service/tools/onboard_mcp_tools \
  -H "Authorization: Bearer <caller-token>" -H "Content-Type: application/json" \
  -d '{
        "mcp_url": "http://mcp-host:8000/sse",
        "mcp_name": "billing-tools",
        "auth_config": { "auth_type": "oauth", "token_url": "...",
                         "client_id": "...", "client_secret": "...", "scope": "tools.invoke" }
      }'
```

When the config service **deploys** a new MCP server (`create_mcp_server`), it injects
the matching env into the target so the two sides agree:
`api_key` → `MCP_AUTH_TYPE=api_key` + `MCP_API_KEY_HEADER/VALUE`;
`oauth` → `MCP_AUTH_TYPE=bearer_jwt` + `JWKS_URL`.

---

## 4. Which endpoints require what

| Endpoint | `none` | `api_key` | `bearer_jwt` |
|----------|--------|-----------|--------------|
| `/healthz`, `/readyz` | open | open (exempt) | open (exempt) |
| `/sse`, `/messages/` | open | api key | **JWT** |
| `/status`, `/tools`, `/metrics` | open | api key | **JWT** |
| `/admin/*` | `MCP_ADMIN_TOKEN` | `MCP_ADMIN_TOKEN` | `MCP_ADMIN_TOKEN` |

In `bearer_jwt` mode `/status`, `/tools`, and `/metrics` are validated with the same
`JWTVerifier` as `/sse` (issuer/audience/scope). `/healthz` and `/readyz` are always
exempt so probes work. Admin endpoints are always gated by `MCP_ADMIN_TOKEN`
independent of the MCP auth mode (disabled with 503 if unset). Prometheus scrapers must
therefore send a valid token in `api_key`/`bearer_jwt` modes.

---

## 5. Quick recipes

```bash
# No auth (local/dev)
MCP_AUTH_TYPE=none

# API key
MCP_AUTH_TYPE=api_key MCP_API_KEY_HEADER=x-api-key MCP_API_KEY_VALUE=$SECRET

# OAuth / JWT (resource server)
MCP_AUTH_TYPE=bearer_jwt \
JWKS_URL=https://<idp>/.well-known/jwks.json \
MCP_JWT_ISSUER=https://<idp>/ MCP_JWT_AUDIENCE=mcp-tools MCP_JWT_REQUIRED_SCOPES=tools.invoke
```
