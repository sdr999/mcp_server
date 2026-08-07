# Action Log - Multi-Tenancy & RBAC Implementation

## [2026-08-06] Typed FastAPI routes — federation batch

Converted the body-carrying federation endpoints to typed FastAPI:
- `POST /mcp/upstreams/{server}/tools/{name}/call` (UpstreamToolCallRequest) —
  reuses `enforce(upstream_auth)`; 404 unknown upstream, 502 UpstreamError.
- `POST /admin/mcp/upstreams` (UpstreamAddRequest) — admin-gated; 403 when
  runtime changes disabled; registers the upstream and returns 201.
- The no-body list/tools/remove routes stay plain (still in /docs).
- Full suite: **212 passed** (pre-existing telemetry failure unchanged).

---

## [2026-08-06] Typed FastAPI routes — onboarding batch

Converted the body-carrying onboarding endpoints to typed FastAPI path
operations (request validation + documented schema):
- `POST /admin/tools/onboard` (OnboardRequest), `POST
  /admin/tools/validate_source` (ValidateSourceRequest), `POST
  /admin/tools/onboard/accept_proposal` (AcceptProposalRequest).
- All error semantics preserved exactly: onboarding-disabled 503, oversized
  source/body 413, too-many-requirements 400, name conflict 409, validation
  ValueError 400, success 201 (installed) / 202 (pending). Reuses `enforce`,
  `notify_tools_changed`, and the onboarding manager.
- The no-body pending/approve/reject/revert/auto_patch routes stay as plain
  wrapped routes (nothing to validate); still listed in /docs.
- Full suite: **212 passed** (pre-existing telemetry failure unchanged).

---

## [2026-08-06] Typed FastAPI routes for admin/RBAC + tool-call (first batch)

Converted the highest-value endpoints from plain Starlette handlers to typed
FastAPI path operations, so they gain **request validation** and a **documented
OpenAPI schema** (real /docs value, not just endpoint listing).

- New `plugins/api_models.py` — Pydantic models (OrgCreate/OrgOut, Workspace*,
  MemberBind/MemberOut, ToolGrantCreate/ToolGrantOut, ToolCallRequest/Result).
- New `plugins/api_routes.py` — an `APIRouter` with typed operations for
  `/admin/orgs*` (orgs, workspaces, members, tool-grants) and `POST
  /tools/{name}/call`. They **reuse** `enforce` (auth+RBAC), the cache
  invalidation helper, and `_serialize_tool_result`, so status codes and response
  bodies match the original handlers exactly.
- `app.py` includes the router and skips the plain equivalents (via
  `TYPED_PATHS`) so nothing double-registers.
- Result: `/openapi.json` now carries request-body schemas + component models
  (e.g. `OrgCreate`), and invalid bodies return **422** with field detail.
  Behavior note: FastAPI validates the body before the endpoint's auth check, so
  a malformed body can yield 422 before 401 — acceptable since the schema is
  already public via auto-docs. Valid-body + missing-auth still returns 401.
- Full suite: **212 passed** (same pre-existing telemetry failure).

---

## [2026-08-06] Migrate the web layer from Starlette to FastAPI (branch `fastapi-mcp`)

Replaced the Starlette top-level app with **FastAPI** (wrapper approach; FastAPI
is the server, `build_app` updated in place). Branched from latest `main`.

### Design
- The top-level app is now `FastAPI(...)`. The FastMCP protocol app
  (`mcp.http_app(...)`) is built as a **sub-app and mounted at "/"** (added last
  so explicit routes + auto-docs win), preserving `/mcp` (streamable HTTP) and
  `/sse` + `/messages` (SSE). FastMCP can only emit a Starlette ASGI app, so it is
  mounted, not rewritten.
- The FastMCP **session-manager lifespan** is entered explicitly inside our
  lifespan (`mcp_app.router.lifespan_context`), because Starlette does not run a
  mounted sub-app's lifespan automatically. The background tool load/reload loop,
  tenancy init/seed, and shutdown `close()` are unchanged.
- Existing Starlette-style handlers (`async def h(request)`) and all middleware
  are **reused as-is**. A helper `_as_request_endpoint()` wraps each handler so
  FastAPI injects the `Request` (via annotation) and lists the route in the
  generated schema, instead of mistaking `request` for a query param.
- **Auto docs:** FastAPI serves Swagger UI at `/docs`, ReDoc at `/redoc`, and the
  generated schema at `/openapi.json`. The hand-built docs routes are skipped;
  `/swagger` now redirects to `/docs` and `/openapi.yaml` is serialized from the
  generated schema (both kept for back-compat).

### Dependencies
- The pinned `fastapi~=0.109.0` (+ `starlette~=0.35`) was **incompatible** with
  the FastMCP stack (FastMCP/sse-starlette need Starlette >=1.3, which old FastAPI
  forbids). Bumped `requirements.txt` to `fastapi>=0.141,<1.0`, `starlette>=1.3`,
  `uvicorn[standard]~=0.51`. Verified the full stack imports and runs together.

### Tests
- `test_main_server`: `_paths()` now recurses into mounted sub-apps so the
  protocol endpoints (`/mcp`, `/sse`, `/messages`) are visible.
- `test_swagger_docs`: assert FastAPI-generated schema (OpenAPI 3.1.x) and the
  generated `/openapi.yaml`; `/docs` + `/swagger` still return Swagger UI.
- Full suite: **212 passed**. (The single `test_telemetry_bootstrap_lifecycle`
  failure is pre-existing on `main` — an OTel/env issue — and unrelated to this
  migration; confirmed by running it with these changes stashed.)

---


## [2026-08-05] Staff Review of the Implementation + Full Findings Remediation

Reviewed the merged Phase 1–3 implementation against the design doc
(`docs/design/MULTI_TENANCY_RBAC.md`) and fixed every finding. Review artifacts:
`docs/design/IMPLEMENTATION_REVIEW.md` (narrative) and
`docs/design/RBAC_ISSUES.md` (trackable checklist). New regression tests in
`src/tests/test_plugins_rbac_c1c2.py` (14 cases). Full suite: **189 passed**
with no env vars required.

### 🔴 Critical
- **C1 — Tenant-header anti-spoofing.** Tenant isolation was enforced against the
  self-asserted `X-Tenant-Id` header, not store membership (`resolve_principal`
  was never called, and itself trusted the header). Added
  `identity.select_tenant_context()` (honors a tenant header only for member
  orgs; non-members → default org); routed all four backends' `resolve_principal`
  through it; `IdentityMiddleware` now overlays store-resolved org/roles/perms
  from the verified `(issuer, subject)` when RBAC is on; anonymous pinned to
  `default`. Store-failure now logged at WARNING (reaches the file handler).
- **C2 — Deny-override grant precedence.** Evaluator returned on the first
  matching grant; now scans all matching grants and any `deny` wins.
  `_grant_applies_to()` also stops an unknown `scope_type` from matching everyone
  and handles `role`/`principal` scopes.

### 🟠 High
- **H1 — One role→permission source of truth.** Added the canonical
  `BUILTIN_ROLE_PERMISSIONS` matrix in `identity.py`; `permissions_for_roles()`
  derives from it; the seeder seeds from the same matrix (no drift; asserted by
  test). Store stays runtime-authoritative via `resolve_principal`.
- **H2 — Grant `match_type` vocabulary.** Evaluator now supports
  `name`/`tag`/`owner`/`all` (tag/owner/all were dead code) with legacy
  `exact`/`prefix`/`glob` aliases; ownership resolved once and reused.
- **H3 — Least-privilege default role.** `DEFAULT_ROLE = "agent_consumer"`; a bare
  signed token no longer inherits `tool:onboard`/`tool:manage`; unknown roles get
  no permissions.
- **H4 — Shadow mode.** `MCP_RBAC_MODE=shadow|enforce` (+ validation). Shadow logs
  a would-deny (WARNING → file), writes a `shadow_deny` audit row, increments
  `mcp_authz_shadow_denials_total`, and proceeds. Also wired the missing
  `MCP_RBAC_ENABLED` / `MCP_RBAC_MODE` env parsing.
- **H5 — Cache invalidation on writes.** `_invalidate_rbac_cache()` wired into
  `bind_member` (principal-scoped), `delete_org` (org-scoped), `add_tool_grant`
  (full clear); decision-cache TTL default 300s → 30s.

### 🟡 Medium
- **M1** backend registry: `register_backend()` + `module.path:Factory` custom
  specs; unknown `MCP_TENANCY_STORE` fails fast instead of falling back to sqlite.
- **M2** existence non-disclosure: denied `tool:call`/`tool:manage` → 404 (unknown-
  tool body); other denials → generic 403; reason logged server-side only.
- **M3** JWT hardening: PyJWKClient fallback drops HS256 (ES256/RS256 only) and
  verifies audience when `MCP_JWT_AUDIENCE` is set (now on `app.state`).
- **M4** `MCP_TENANCY_RECONCILE_ROLES` re-syncs drifted built-in role perms on
  boot; seed-lock scope documented (backend-level lock deferred, §21.1).
- **M5** removed the hardcoded Supabase issuer default and the email-keyed
  superadmin binding (could never match `resolve_principal`, which keys on `sub`);
  superadmin via email-claim match + admin-token bootstrap.
- **M6** interface: `is_empty()`, `close()` (wired into lifespan shutdown), and
  `limit`/`offset` pagination on the four `list_*` methods across all backends.
- **M7** untracked runtime artifacts (`src/data/*.db`, `src/logs/`) + `.gitignore`.
- **M8** documented that ABAC `trusted_tags` is a required-attributes gate (grant
  creation is admin-only, so the §17.6 self-grant vector is closed).

### CI / test-environment fixes
- **fastapi hard-dependency removed** — `plugins/auth_service.py` now imports
  `HTTPException`/`status` from Starlette (same interface), so
  `tests/test_plugins_identity.py` collects without fastapi installed.
- **`src/tests/conftest.py`** sets `MCP_ADMIN_TOKEN` at collection time (via
  `setdefault`) so the admin/tenancy REST tests run without a hand-set env var.
- Updated `test_whoami_*` to assert the C1-secure behavior (anonymous ignores
  tenant headers) instead of the old header-echo.

---

## [2026-08-05] Documentation & Sample Payloads Guide Created

### Summary of Documentation Changes
1. **Dedicated Architecture Guide (`docs/MULTI_TENANCY_RBAC_GUIDE.md`)**:
   - Created comprehensive technical documentation containing:
     - Component structure and module references (`src/plugins/tenancy/*`, `src/plugins/rbac/*`).
     - Architectural diagrams and 5-tier evaluation precedence details.
     - Complete REST API Sample Payloads (Request & Response JSON) for:
       - Auth Signup/Signin (`POST /auth/signup`, `POST /auth/signin`)
       - WhoAmI Identity Inspection (`GET /whoami`)
       - Organization Management (`POST /admin/orgs`, `GET /admin/orgs`, `DELETE /admin/orgs/{org}`)
       - Workspace Management (`POST /admin/orgs/{org}/workspaces`, `GET /admin/orgs/{org}/workspaces`)
       - Member Role Binding (`POST /admin/orgs/{org}/members`, `GET /admin/orgs/{org}/members`)
       - Dynamic Tool Grants (`POST /admin/orgs/{org}/tool-grants`, `GET /admin/orgs/{org}/tool-grants`)
       - Tenant Catalog Scoping (`GET /tools`)
     - Code Walkthrough snippets (`PolicyEvaluator` logic and MongoDB Motor async pool).
2. **Environment Configuration Templates**:
   - Created root [`.env.example`](file:///d:/python/mcp_server/.env.example) and [`src/config/.env.example`](file:///d:/python/mcp_server/src/config/.env.example).
3. **Documentation Index**:
   - Updated [`docs/README.md`](file:///d:/python/mcp_server/docs/README.md) and [`docs/MCP_AUTH_GUIDE.md`](file:///d:/python/mcp_server/docs/MCP_AUTH_GUIDE.md) to cross-reference the new guide.

---

## [2026-08-05] Phase 5 Implementation Complete: Production Hardening, Audit Trail & Metrics

### Summary of Phase 5 Changes
1. `AsyncAuditLogger` non-blocking background queue worker writing to `logs/audit.log` (JSONL) & DB.
2. Prometheus security metrics `mcp_authz_evaluations_total` and `mcp_authz_denials_total` at `GET /metrics`.
3. OpenAPI Specification updates in `openapi/openapi.yaml`.
4. Automated Test Suite (173/173 passing).

---

## [2026-08-05] Phase 4 Implementation Complete: Dynamic Tool Grants & ABAC Rules

### Summary of Phase 4 Changes
1. `ABACEvaluator` & `ABACResult` (`src/plugins/rbac/abac.py`).
2. Policy engine integration in `src/plugins/rbac/evaluator.py`.
3. Admin REST API Tool Grants in `src/plugins/routes.py`.

---

## [2026-08-05] Phase 3 Implementation Complete: Tenant & Workspace Catalog Scoping

### Summary of Phase 3 Changes
1. Tenant catalog scoping (`src/plugins/tenancy/scoping.py`).
2. REST API route integration (`src/plugins/routes.py`).

---

## [2026-08-05] Phase 2 Implementation Complete: RBAC Policy Engine & Hierarchical Evaluation

### Summary of Phase 2 Changes
1. 5-tier policy evaluation engine (`src/plugins/rbac/evaluator.py`).
2. L1 decision cache (`src/plugins/rbac/cache.py`).

---

## [2026-08-05] Phase 1 Implementation Complete: Pluggable Tenancy Store (SQLite + MongoDB + Memory + JSON)

### Reference Integration from `D:\pyhton\pj\hire-pilot`
- Motor async connection pooling and unique compound index setup.

---

## [2026-08-05] Phase 0 Implementation Complete
- Core Identity & Supabase JWT Integration.

---

## [2026-08-06] Final Audit, Environment Template & Documentation Synchronization

### Summary of Actions
1. **Remediation & Security Verification**:
   - Conducted deep architectural review of commits `ff6ae03..c380cf1` covering C1 (Tenant Header Anti-Spoofing), C2 (Deny-Override Grants), H1-H5 (Role Matrix, Vocabulary Sync, Shadow Mode, Cache Invalidation), and M1-M8.
   - Executed full test suite (`pytest src/tests`): **189 / 189 tests passed** (100% pass rate).

2. **Environment Configuration Templates**:
   - Created root [`.env.example`](file:///d:/python/mcp_server/.env.example) and [`src/config/.env.example`](file:///d:/python/mcp_server/src/config/.env.example) with all configuration variables across Phases 0-5.
   - Synchronized active runtime environment [`src/config/.env`](file:///d:/python/mcp_server/src/config/.env).

3. **Enterprise Documentation Guide**:
   - Created [`docs/MULTI_TENANCY_RBAC_GUIDE.md`](file:///d:/python/mcp_server/docs/MULTI_TENANCY_RBAC_GUIDE.md) containing component maps, 5-tier evaluation flow diagrams, code walkthroughs, and sample HTTP payloads (Request/Response JSON for Auth, Admin CRUD, Tool Grants, and Scoped Catalog).
   - Cross-referenced in [`docs/README.md`](file:///d:/python/mcp_server/docs/README.md) and [`docs/MCP_AUTH_GUIDE.md`](file:///d:/python/mcp_server/docs/MCP_AUTH_GUIDE.md).

4. **Swagger UI Tag Order Update**:
   - Reordered tags in [`openapi/openapi.yaml`](file:///d:/python/mcp_server/openapi/openapi.yaml) to place `Authentication & Identity` at the top of Swagger UI.

5. **Admin Route Authorization Dual-Mode Support**:
   - Updated `admin_denied` in [`src/plugins/security.py`](file:///d:/python/mcp_server/src/plugins/security.py) and [`src/plugins/routes.py`](file:///d:/python/mcp_server/src/plugins/routes.py) so that `/admin/*` endpoints authorize either static `MCP_ADMIN_TOKEN` (`mysecretadmin`) OR a verified Supabase JWT Bearer token possessing `platform_superadmin` / `platform:admin` / `org:admin` permissions.
   - Directly checks `request.state.principal` attached by `IdentityMiddleware` for zero-latency JWT validation.

6. **Swagger UI Security Schemes & Secured Lock Icon Alignment**:
   - Added explicit `security:` requirements (`AdminTokenAuth` & `BearerAuth`) to `/admin/orgs` (GET/POST) in [`openapi/openapi.yaml`](file:///d:/python/mcp_server/openapi/openapi.yaml).
   - Added `/mcp` FastMCP Streamable Endpoint with `GET`, `POST`, and `DELETE` operations secured with `BearerAuth` & `ApiKeyAuth` requirements in [`openapi/openapi.yaml`](file:///d:/python/mcp_server/openapi/openapi.yaml) and [`src/plugins/routes.py`](file:///d:/python/mcp_server/src/plugins/routes.py).
   - Filtered duplicate `HEAD` methods out of OpenAPI auto-discovery in [`src/plugins/routes.py`](file:///d:/python/mcp_server/src/plugins/routes.py) for a clean Swagger UI.
   - Updated `_jwt_ok` fast-path in [`src/plugins/security.py`](file:///d:/python/mcp_server/src/plugins/security.py) to immediately recognize principal objects resolved by `IdentityMiddleware`.
   - Updated Federation endpoints (`/mcp/upstreams`, `/admin/mcp/upstreams`) to require `BearerAuth`, `AdminTokenAuth`, and `ApiKeyAuth`, removing unauthenticated `- {}` overrides.
7. **Standalone Package Creation, Multi-Framework Usage & Wheel Build**:
   - Packaged the Multi-Tenancy RBAC authorization framework as a standalone Python package in [`packages/mcp_tenancy_rbac/`](file:///d:/python/mcp_server/packages/mcp_tenancy_rbac/).
   - Built standalone Wheel binary distribution [`packages/mcp_tenancy_rbac/dist/mcp_tenancy_rbac-1.0.0-py3-none-any.whl`](file:///d:/python/mcp_server/packages/mcp_tenancy_rbac/dist/mcp_tenancy_rbac-1.0.0-py3-none-any.whl) (38.6 KB) and Source Tarball [`packages/mcp_tenancy_rbac/dist/mcp_tenancy_rbac-1.0.0.tar.gz`](file:///d:/python/mcp_server/packages/mcp_tenancy_rbac/dist/mcp_tenancy_rbac-1.0.0.tar.gz) (30.6 KB).
   - Created comprehensive multi-framework usage guide in [`docs/PACKAGE_USAGE_GUIDE.md`](file:///d:/python/mcp_server/docs/PACKAGE_USAGE_GUIDE.md) featuring explicit production-ready integration examples for FastAPI, gRPC/Background Workers, Flask/Django, and FastMCP.
   - Installed in editable mode (`pip install -e ./packages/mcp_tenancy_rbac`) and verified 100% test pass rate (190/190 passing).











