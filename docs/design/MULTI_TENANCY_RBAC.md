# Design: Multi-Tenancy & RBAC for the MCP Tool Server

Status: **Proposed** · Branch: `org` · Author: architecture spike · Scope of
this doc: design only (no implementation)

## Decisions baked into this design

| Question | Decision |
|----------|----------|
| Identity source | **Hybrid** — a JWT (`bearer_jwt` mode) proves *who* the caller is (the `subject`); the **local tenancy store** is the source of truth for org/workspace membership, role bindings, and tool grants, joined by `subject`. |
| Isolation depth | **RBAC + logical multi-tenancy** — scoped visibility/calls, per-tenant catalogs, roles, grants, quotas — all **in-process**. Tenant tools are trusted. Hard execution isolation is an explicit **non-goal** here (see §9). |
| Store | **SQLite** via the stdlib `sqlite3` (no new hard dependency), file at `MCP_TENANCY_DB`. |

---

## 1. Problem

Today the server has a **flat, global tool namespace** (`src/tools/`) and **no
concept of identity**. Auth authenticates a request but the identity is
discarded — `security._jwt_ok()` returns only a boolean even though FastMCP's
`verify_token()` already returns an `AccessToken` with `subject`, `scopes`,
`claims`, `client_id`, `resource`. There are no Organizations, Workspaces,
Users, Roles, or Tool Access Scopes. Every caller sees and can call every tool.

We want: **Organizations → Workspaces → Users with Roles (Admin / Developer /
Agent Consumer) → scoped access to Tools**, enforced consistently across the
REST API and (eventually) the MCP protocol.

## 2. Goals / Non-goals

**Goals**
- A request-scoped **Principal** (subject, org, workspace, roles, permissions).
- Org / Workspace tenancy with per-tenant tool visibility & call authorization.
- Roles → permissions, plus fine-grained **tool access scopes** (allow/deny by
  name / tag / namespace).
- Backward compatible: with RBAC disabled (default), behavior is identical to
  today; enabling it is opt-in.
- Auditable with **actor identity** (fixes the current "single shared admin
  token → no per-actor identity" gap in onboarding audit).

**Non-goals (this effort)**
- **Hard multi-tenant execution isolation** (safe to run *untrusted* tenant code
  side by side). Tools still execute in the shared interpreter; see §9 for why
  and the future path.
- Building an internal user database / login UI (identity stays in the IdP).
- Billing/metering beyond simple quotas.

## 3. Prerequisites & readiness

| # | Prerequisite | Status | Plan |
|---|--------------|--------|------|
| 1 | **Principal propagation** — identity on `request.state` | ❌ discarded after auth | Phase 0 (blocker; unblocks all) |
| 2 | **Identity source** | JWT mode exists but claims unused | Hybrid: JWT `subject` + local store |
| 3 | **Persistence** | flat files/env only | SQLite tenancy store (Phase 1) |
| 4 | **Tenant-scoped tool namespace** | flat global `src/tools/` | ownership tags + grant overlay (Phase 3) |
| 5 | **Per-tenant execution isolation** | shared process; optional subprocess sandbox | out of scope (§9) |

**Can we start?** Yes. Phase 0 (principal propagation) is the only hard blocker
and it is small and behavior-preserving. Everything else builds on it.

## 4. Domain model

```
Organization (tenant — top isolation boundary)
 └─ Workspace (team/project sub-partition)
     ├─ Membership: (subject, org, role, workspace?)   ← role binding
     ├─ Tools:  platform-shared  ∪  workspace-private (onboarded)
     ├─ Upstreams (federation), quotas
     └─ Audit (actor = subject)

Role            = platform_superadmin | org_admin(Admin) | developer | agent_consumer
Permission      = "<verb>:<resource>"  (e.g. tool:call, tool:onboard, upstream:manage)
ToolAccessScope = grant(effect: allow|deny, match: name|tag|namespace|all) on a scope
```

### Identity model (Hybrid) — precedence
1. **Authentication (JWT):** `bearer_jwt` verifies the token; we keep the
   `AccessToken`. The `subject` claim is the stable user id. (`api_key` mode maps
   to a configured service principal; the admin token maps to
   `platform_superadmin`.)
2. **Authorization (local store):** role bindings, org/workspace membership, and
   tool grants come from the **tenancy store**, keyed by `subject`. The store is
   authoritative.
3. **Optional claim seeding:** if the JWT carries `org`/`roles` claims
   (`MCP_JWT_ORG_CLAIM`, `MCP_JWT_ROLES_CLAIM`), they may **bootstrap** a
   first-seen subject (JIT provisioning), but an explicit store binding always
   wins. This keeps identity in the IdP while letting ops manage tenancy locally.

## 5. Roles → permissions (default matrix)

| Permission | SuperAdmin | Admin (org) | Developer | Agent Consumer |
|---|:--:|:--:|:--:|:--:|
| `tool:list` (scoped) | ✓ | ✓ | ✓ | ✓ |
| `tool:call` (scoped) | ✓ | ✓ | ✓ | ✓ |
| `tool:onboard` | ✓ | ✓ | ✓ | ✗ |
| `tool:manage` (disable/enable/reload) | ✓ | ✓ | ✓ (own) | ✗ |
| `upstream:read` / `upstream:call` | ✓ | ✓ | ✓ | ✓ |
| `upstream:manage` | ✓ | ✓ | ✗ | ✗ |
| `member:manage` / `role:bind` | ✓ | ✓ (own org) | ✗ | ✗ |
| `org:admin` / `workspace:admin` | ✓ | ✓ (own org) | ✗ | ✗ |
| `platform:admin` (cross-org) | ✓ | ✗ | ✗ | ✗ |

Roles and their permission sets are **data** (seedable/overridable), not
hard-coded, so deployments can add custom roles later.

## 6. Tool access scoping

Tools resolve against a **shared catalog + per-tenant overlay**:
- **Ownership:** every tool has `owner_org`, `owner_workspace?`, and
  `visibility ∈ {private, org, public}`. Platform tools (in `src/tools/`) are
  `public`; onboarded tools default to `private` to the onboarding
  org/workspace (extends the existing per-tool manifest / `*.meta.json`).
- **Grants:** allow/deny rules attached to a scope (`org` / `workspace` / `role`
  / `principal`) matching by `name`, `tag`, `namespace`, or `all`.
- **Decision (deny-by-default when RBAC on):** a tool is visible/callable to a
  principal iff (visibility permits the principal's tenant) **AND** (an `allow`
  grant matches) **AND** (no `deny` grant matches). `deny` beats `allow`.

`/tools` (catalog) and `/tools/{name}/call` filter by this decision; a principal
never sees or calls a tool outside their grants.

## 7. Enforcement architecture

New plugin modules (mirroring the existing single-purpose layout):

| Module | Responsibility |
|--------|----------------|
| `plugins/identity.py` | Middleware: build `Principal` from the credential + tenant headers; attach to `request.state.principal`. |
| `plugins/tenancy.py` | The SQLite store: orgs, workspaces, memberships, role bindings, tool ownership & grants; CRUD + queries. |
| `plugins/rbac.py` | The Policy Decision Point: `require(request, permission, resource=None)`. Wraps/derives from today's `enforce()`. |

**Request flow (RBAC enabled):**
```
request → [ApiKeyMiddleware guards /mcp only]
        → IdentityMiddleware: authenticate → subject
             → resolve active org/workspace (X-Tenant-Id / X-Workspace-Id, validated
               against memberships; single membership auto-selected; superadmin cross-tenant)
             → load roles + permissions + grants from tenancy store
             → request.state.principal = Principal(...)
        → route handler: require(request, "tool:call", resource=tool)  → 401/403 or proceed
        → tenant-scoped catalog/exec filters by principal grants
```

**Mapping onto the existing per-route policies (back-compat):** today's
`enforce(policy)` with `none|mcp|admin` becomes a thin adapter over `require`:
`none`→public, `mcp`→the route's permission (e.g. `tool:call`), `admin`→
`org:admin`/`platform:admin`. When `MCP_RBAC_ENABLED=false` (default),
`require` short-circuits to the current behavior exactly — **zero change** for
existing single-tenant deployments.

## 8. Data model (SQLite)

```sql
organizations(org_id TEXT PK, name TEXT, created_at, settings_json TEXT)
workspaces(workspace_id TEXT PK, org_id TEXT FK, name TEXT, created_at)
principals(subject TEXT PK, display_name TEXT, disabled INT DEFAULT 0, created_at)
memberships(subject TEXT, org_id TEXT, role TEXT, workspace_id TEXT NULL,
            PRIMARY KEY(subject, org_id, workspace_id, role))
roles(role TEXT PK, permissions_json TEXT)                     -- data-driven role→perms
tool_ownership(tool_name TEXT PK, owner_org TEXT, owner_workspace TEXT NULL,
               visibility TEXT CHECK(visibility IN('private','org','public')))
tool_grants(id INTEGER PK, scope_type TEXT, scope_id TEXT, effect TEXT,
            match_type TEXT, match_value TEXT, created_at)
audit(id INTEGER PK, ts, actor_subject TEXT, org_id TEXT, action TEXT,
      resource TEXT, result TEXT, detail TEXT)
```

Single-file, embedded, no new dependency. A JSON-file backend is a drop-in
alternative for tiny deployments; the store interface abstracts it.

## 9. Security considerations

- **In-process isolation limit (critical):** with logical multi-tenancy, tenant
  A's tool and tenant B's tool share the interpreter, env vars, filesystem, and
  installed packages. RBAC controls *who can call what*, **not** what a running
  tool can reach. Treat all tenant tools as **trusted**. Hard isolation (safe
  for *untrusted* tenants) needs per-tenant workers/containers — future Phase 5,
  seeded by the existing `MCP_SANDBOX_TOOLS` subprocess sandbox.
- **Tenant-header spoofing:** `X-Tenant-Id` / `X-Workspace-Id` are *requests*,
  never trusted on their own — always validated against the principal's
  memberships. A non-member selecting an org gets `403`.
- **Token trust:** JWT `subject`/claims are only trusted from a verified token
  (issuer/audience/JWKS as today). Claim-seeded provisioning is gated by config.
- **Fail closed:** RBAC-enabled with no principal → `401`; principal without a
  matching grant → `403`.
- **Secrets:** upstream/tenant secrets keep the existing redaction + `0600`
  storage discipline.

## 10. API surface changes

**New admin/tenancy endpoints** (all `platform:admin` or `org:admin`):
```
POST/GET/DELETE /admin/orgs[/{org}]
POST/GET/DELETE /admin/orgs/{org}/workspaces[/{ws}]
POST/GET/DELETE /admin/orgs/{org}/members            # bind subject → role[/workspace]
POST/GET/DELETE /admin/orgs/{org}/tool-grants        # allow/deny rules
GET             /whoami                               # the caller's resolved Principal
```
**Existing endpoints become tenant-scoped** when RBAC is on: `/tools`,
`/tools/{name}/call`, `/admin/tools/onboard`, `/admin/tools/pending*`,
`/mcp/upstreams*` all resolve against `request.state.principal`. Onboarding
tags new tools with the caller's org/workspace.

**Headers:** `X-Tenant-Id` (active org), `X-Workspace-Id` (active workspace) —
optional; defaulted from membership.

## 11. Config additions

```bash
MCP_RBAC_ENABLED=false           # master switch; false = today's behavior exactly
MCP_TENANCY_DB=data/tenancy.db   # SQLite path (relative to src/)
MCP_DEFAULT_ORG=default          # org used to auto-own existing tools on enable
MCP_TENANT_HEADER=X-Tenant-Id
MCP_WORKSPACE_HEADER=X-Workspace-Id
MCP_JWT_SUBJECT_CLAIM=sub        # hybrid identity mapping
MCP_JWT_ORG_CLAIM=org            # optional JIT-provisioning seed
MCP_JWT_ROLES_CLAIM=roles        # optional JIT-provisioning seed
MCP_RBAC_JIT_PROVISION=false     # allow claim-seeded first-login binding
```

## 12. Backward compatibility & migration

- **Default off.** `MCP_RBAC_ENABLED=false` → identical to current server.
- **On first enable:** create a `default` org + `default` workspace; map the
  existing `MCP_ADMIN_TOKEN` to a `platform_superadmin` service principal; set
  all existing `src/tools/*` to `owner=default`, `visibility=public`. Existing
  single-tenant clients keep working; multi-tenancy is additive.
- The per-route `none|mcp|admin` policies remain valid (adapter over `require`).

## 13. The one technical unknown (spike before Phase 4)

REST enforcement is straightforward (middleware + `require`). But **native MCP
tool calls over `/mcp`** (FastMCP JSON-RPC) need per-tool RBAC applied inside
FastMCP's `list_tools`/`call_tool` path — via a FastMCP middleware/hook or
per-tool permission wrappers. **A short spike must confirm FastMCP's
interception points** before committing Phase 4. Until then, RBAC is enforced on
the REST surface (`/tools`, `/tools/{name}/call`, admin) and the `/mcp` catalog
can be tenant-filtered at registration time as an interim measure.

## 14. Phased rollout

| Phase | Delivers | Risk |
|-------|----------|------|
| **0 — Principal propagation** | Keep `AccessToken` claims → `Principal` on `request.state`; `/whoami`. No behavior change. | Low — unblocks all |
| **1 — Tenancy store & model** | SQLite store; orgs/workspaces/members/roles/grants; admin CRUD; config seeding. | Low |
| **2 — RBAC PDP** | `require(permission)`; adapter maps existing policies; audit gains actor identity. | Med |
| **3 — Tenant-scoped tools** | Ownership tags + grant overlay; `/tools` & call filtered; onboarding owns tools per tenant. | Med |
| **4 — Enforce on `/mcp`** | Per-tool RBAC on the MCP protocol path (after the spike). | **High (unknown)** |
| **5 — Isolation & quotas** *(future / out of current scope)* | Per-tenant sandbox/worker, rate/resource quotas. | High |

## 15. Testing strategy

- **Unit:** store CRUD; role→permission resolution; grant decision (allow/deny
  precedence); tenant-header validation (spoof → 403).
- **Integration (TestClient):** RBAC-off parity (identical to today); RBAC-on
  matrix — Admin/Developer/AgentConsumer against list/call/onboard/manage;
  cross-tenant denial; `/whoami`.
- **Hybrid identity:** mocked JWT subjects joined to store bindings; JIT
  provisioning on/off.
- **Migration:** enable on an existing deployment → default org owns tools,
  admin token → superadmin, existing calls still succeed.

## 16. Open questions

1. **`/mcp` enforcement** — FastMCP hook availability (spike, §13).
2. **Quota model** — per-org rate/concurrency limits: needed in v1 or defer to
   Phase 5?
3. **Custom roles** — ship the 4 built-ins only, or expose role CRUD in v1?
4. **Cross-tenant tool sharing** — allow an org to publish a tool `public` to
   other orgs, or keep `public` = platform-only?
