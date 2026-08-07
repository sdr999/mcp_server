# API Reference (usage · implementation · tests)

A per-endpoint reference for the HTTP API. Each entry gives a copy-paste `curl`
example, the **Pydantic request model**, the **function that implements it**, and
the **test(s) that cover it**, so you can jump from behavior → code → proof.

The server is a **FastAPI** app, so the live, always-in-sync docs are also at:

- **Swagger UI:** `GET /docs`  ·  **ReDoc:** `GET /redoc`
- **OpenAPI schema:** `GET /openapi.json` (or `/openapi.yaml`)

Request/response models live in [`src/plugins/api_models.py`](../src/plugins/api_models.py);
the typed routes in [`src/plugins/api_routes.py`](../src/plugins/api_routes.py).

## Conventions

```bash
BASE=http://localhost:8000
# Admin endpoints require the admin token (server started with MCP_ADMIN_TOKEN):
ADM=(-H "Authorization: Bearer $MCP_ADMIN_TOKEN" -H "Content-Type: application/json")
# Multi-tenancy (when MCP_RBAC_ENABLED=true): select the active tenant/workspace.
TEN=(-H "X-Tenant-Id: acme" -H "X-Workspace-Id: default")
```

Auth model: `MCP_AUTH_TYPE` = `none` | `api_key` | `bearer_jwt`; the admin API is
independently gated by `MCP_ADMIN_TOKEN` (disabled → `503`). Per-route policies
(`none`/`mcp`/`admin`) and RBAC are applied in
[`security.enforce`](../src/plugins/security.py). Invalid request bodies return
**422** (FastAPI validation) with field detail.

---

## Tools — execution

### `POST /tools/{name}/call`
Execute a registered tool. MCP `tools/call` semantics: a tool that raises is
reported **in-band** (`200` with `is_error: true`); unknown/disabled → `404`;
malformed arguments → `400`; unauthenticated → `401`.

- **Body:** `ToolCallRequest` `{ "arguments": { ... } }`
- **Implements:** `api_routes.py::call_tool`
- **Tested by:** `tests/test_main_server.py::test_tool_call_executes_and_returns_result`,
  `::test_tool_call_unknown_tool_is_404`, `::test_tool_call_bad_arguments_is_400`,
  `::test_tool_call_tool_raises_is_reported_in_band`,
  `::test_tool_call_requires_mcp_credential_in_api_key_mode`

```bash
curl -X POST "$BASE/tools/weather/call" -H "Content-Type: application/json" \
  -d '{"arguments": {"city": "Paris"}}'
# {"tool":"weather","is_error":false,"structured_content":{"result":"Paris: 69.8F"},"content":[...]}
```

---

## Admin — tenancy & RBAC

All require the admin token. Bodies validated by Pydantic; see
[`api_models.py`](../src/plugins/api_models.py).

### `POST /admin/orgs` · `GET /admin/orgs` · `DELETE /admin/orgs/{org}`
Create / list / delete organizations.

- **Body (create):** `OrgCreate` `{ "org_id", "name", "settings"? }` → `OrgOut`
- **Query (list):** `limit` (100), `offset` (0)
- **Implements:** `api_routes.py::create_org`, `::list_orgs`, `::delete_org`
- **Tested by:** `tests/test_plugins_tenancy.py::test_admin_tenancy_rest_api_crud`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/orgs" -d '{"org_id":"acme","name":"Acme Corp"}'
# 201 {"org_id":"acme","name":"Acme Corp","status":"active","created_at":...}
curl "${ADM[@]:0:2}" "$BASE/admin/orgs"                       # 200 [ {...} ]
curl "${ADM[@]:0:2}" -X DELETE "$BASE/admin/orgs/acme"        # 200 {"message":"...deleted..."}
```

### `POST /admin/orgs/{org}/workspaces` · `GET …/workspaces`
Create / list workspaces within an org.

- **Body:** `WorkspaceCreate` `{ "workspace_id", "name" }` → `WorkspaceOut`
- **Implements:** `api_routes.py::create_workspace`, `::list_workspaces`
- **Tested by:** `tests/test_plugins_tenancy.py::test_admin_tenancy_rest_api_crud`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/orgs/acme/workspaces" \
  -d '{"workspace_id":"prod","name":"Production"}'      # 201
```

### `POST /admin/orgs/{org}/members` · `GET …/members`
Bind a principal to a role (optionally scoped to a workspace) / list members.
A role change busts the RBAC decision cache for that principal.

- **Body:** `MemberBind` `{ "principal_id" | "subject", "role", "workspace_id"? }` → `MemberOut`
- **Implements:** `api_routes.py::bind_member`, `::list_members`
- **Tested by:** `tests/test_plugins_tenancy.py::test_admin_tenancy_rest_api_crud`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/orgs/acme/members" \
  -d '{"principal_id":"pid_alice","role":"org_admin","workspace_id":"prod"}'   # 201
```

### `POST /admin/orgs/{org}/tool-grants` · `GET …/tool-grants`
Add / list allow-or-deny tool access grants. `match_type` accepts the model
vocabulary `name` | `tag` | `owner` | `all` (plus legacy `exact`/`prefix`/`glob`);
precedence is **deny-override**. Adding a grant clears the decision cache.

- **Body:** `ToolGrantCreate` `{ "scope_type", "scope_id"?, "effect", "match_type", "match_value" }` → `ToolGrantOut`
- **Implements:** `api_routes.py::add_tool_grant`, `::list_tool_grants`
- **Tested by:** `tests/test_plugins_abac.py::test_admin_tool_grants_rest_api`;
  precedence/vocabulary in `tests/test_plugins_rbac_c1c2.py::test_deny_overrides_allow_regardless_of_order`,
  `::test_grant_match_types_name_tag_owner_all`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/orgs/acme/tool-grants" \
  -d '{"scope_type":"org","scope_id":"acme","effect":"allow","match_type":"tag","match_value":"finance"}'
```

---

## Admin — tool onboarding

### `POST /admin/tools/onboard`
Onboard a tool from source + pip requirements. Returns `201` (installed) or
`202` (held pending review). Errors: onboarding disabled → `503`; oversized
source/body → `413`; too many requirements → `400`; name conflict without
`overwrite` → `409`; validation failure → `400`.

- **Body:** `OnboardRequest` `{ "name", "source", "requirements"?, "overwrite"?, "auto_heal"? }`
- **Implements:** `api_routes.py::onboard_tool`
- **Tested by:** `tests/test_main_server.py::test_onboard_low_risk_tool_loads_immediately`,
  `::test_onboard_requires_admin_token`, `::test_onboard_rejects_bad_name_and_syntax_error`,
  `::test_onboard_disabled_returns_503`, `::test_onboard_oversized_source_rejected`,
  `::test_onboard_too_many_requirements_rejected`, `::test_onboard_duplicate_conflict_then_overwrite`;
  `tests/test_swagger_docs.py::test_onboard_calls_validation_internally`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/tools/onboard" -d '{
  "name":"reverse",
  "source":"from tools_sdk import tool\n@tool()\ndef reverse(text: str) -> str:\n    return text[::-1]\n"
}'   # 201 (or 202 if held pending)
```

### `POST /admin/tools/validate_source`
Dry-run: syntax + dependency check and autofix hints, without installing.

- **Body:** `ValidateSourceRequest` `{ "source", "requirements"?, "name"? }`
- **Implements:** `api_routes.py::validate_source`
- **Tested by:** `tests/test_swagger_docs.py::test_validate_source_endpoint`,
  `tests/test_auto_healer.py`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/tools/validate_source" \
  -d '{"source":"from tools_sdk import tool\n@tool()\ndef ping() -> str:\n    return \"pong\"\n"}'
# 200 {"syntax_ok":true,"tools_found":["ping"], ...}
```

### `POST /admin/tools/onboard/accept_proposal`
Accept a dry-run proposal and onboard immediately (`overwrite` defaults true).

- **Body:** `AcceptProposalRequest` `{ "name", "source", "requirements"? , "overwrite"? }`
- **Implements:** `api_routes.py::accept_proposal`
- **Tested by:** `tests/test_advanced_auto_healer.py::test_one_click_accept_proposal_and_auto_patch_endpoints`

### Pending review (no request body — plain routes)
`GET /admin/tools/pending`, `GET /admin/tools/pending/{name}`,
`POST /admin/tools/pending/{name}/approve`, `.../reject`.

- **Implements:** `routes.py::_admin_tools_pending_list` / `_admin_tools_pending_detail`
  / `_admin_tools_pending_approve` / `_admin_tools_pending_reject`
- **Tested by:** `tests/test_main_server.py::test_onboard_high_risk_dependency_is_held_pending_then_can_be_approved`,
  `::test_onboard_pending_approve_unknown_is_404`

---

## Federation — remote MCP upstreams

### `POST /mcp/upstreams/{server}/tools/{name}/call`
Call a tool on a remote MCP upstream. Unknown upstream → `404`; upstream/transport
error → `502`.

- **Body:** `UpstreamToolCallRequest` `{ "arguments": { ... } }`
- **Implements:** `api_routes.py::call_upstream_tool`
- **Tested by:** `tests/test_main_server.py::test_upstream_list_tools_and_call`

```bash
curl -X POST "$BASE/mcp/upstreams/billing/tools/invoice_lookup/call" \
  -H "Content-Type: application/json" -d '{"arguments":{"id":"INV-42"}}'
```

### `POST /admin/mcp/upstreams`
Register a remote upstream at runtime (admin). Disabled at runtime → `403`.

- **Body:** `UpstreamAddRequest` `{ "name", "url", "token"?, "api_key"?, "header_name"?, "auth_type"?, "headers"?, "token_url"?, "client_id"?, "client_secret"? }`
- **Implements:** `api_routes.py::add_upstream`
- **Tested by:** `tests/test_main_server.py::test_admin_upstream_add_and_remove`,
  `tests/test_upstreams_poc_security.py::test_admin_upstream_api_integration`

```bash
curl "${ADM[@]}" -X POST "$BASE/admin/mcp/upstreams" \
  -d '{"name":"search","url":"http://search:8000/sse"}'   # 201
```

### List / remove (no request body — plain routes)
`GET /mcp/upstreams`, `GET /mcp/upstreams/{server}/tools`,
`POST /admin/mcp/upstreams/{server}/remove`.

- **Implements:** `routes.py::_upstreams_list` / `_upstream_tools` / `_admin_upstream_remove`
- **Tested by:** `tests/test_main_server.py::test_upstream_list_tools_and_call`,
  `::test_admin_upstream_add_and_remove`

---

## Core — health, readiness, catalog, status, identity

Plain routes (no request body); documented in the schema, covered by tests.

| Endpoint | Purpose | Implements | Tested by |
|---|---|---|---|
| `GET /healthz` | Liveness (`{"status":"ok"}`) | `routes.py::_health` | `tests/test_main_server.py`, `tests/test_observability.py` |
| `GET /readyz` | Readiness (`{"ready":true}` after initial load) | `routes.py::_readyz` | `tests/test_main_server.py` |
| `GET /status` | Server stats + active transport | `routes.py::_status` | `tests/test_main_server.py::test_read_auth_none_opens_status_in_api_key_mode` |
| `GET /tools` | Tool catalog (RBAC-filtered when enabled) | `routes.py::_tools_catalog` | `tests/test_plugins_tenant_scoping.py`, `tests/test_main_server.py` |
| `GET /whoami` | Caller's resolved Principal | `routes.py::_whoami` | `tests/test_plugins_identity.py::test_whoami_anonymous_ignores_tenant_headers` |
| `GET /metrics` | Prometheus metrics | `routes.py` (metrics) | `tests/test_main_server.py::test_onboarding_metrics_exposed` |

MCP protocol endpoint: `POST /mcp` (streamable HTTP) or `/sse` + `/messages`
(legacy SSE) — served by the mounted FastMCP app; connect with any MCP client.

---

## How to run the tests referenced here

```bash
cd src
# The admin/tenancy tests need an admin token; tests/conftest.py sets a default.
python -m pytest tests/ -q
# A single endpoint's coverage, e.g. the tool-grants API:
python -m pytest tests/test_plugins_abac.py::test_admin_tool_grants_rest_api -q
```
