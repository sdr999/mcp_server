# Design: Multi-Tenancy & RBAC for the MCP Tool Server

Status: **Proposed (revised after SDE5 review — see §17–§19)** · Branch: `org`
· Scope of this doc: design only (no implementation)

> **Review note:** §§1–16 are the original proposal. §17 (corner cases), §18
> (cross-cutting concerns), and §19 (safe rollout) are the review layer and, where
> they conflict with an earlier section, **they win** — the most important being:
> the principal key is `(issuer, subject)` not `subject` (§17.1); onboarded tool
> names are **tenant-qualified** to survive the flat FastMCP registry (§17.2);
> and SQLite is single-instance so multi-replica deployments need Postgres (§18.1).

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

> **Name collision is a first-class problem, not a footnote (see §17.2).** The
> FastMCP registry is a **single global namespace** — two orgs cannot both
> register a tool literally named `weather`. Onboarded tools are therefore
> stored under a **tenant-qualified name** (`org__[workspace__]name`); the caller
> uses the short name and the router resolves it within their active tenant.
> Platform (`src/tools/`) tools keep their bare names and are `public`.

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
schema_meta(version INTEGER)                                   -- migrations (§18.3)

organizations(org_id TEXT PK, name TEXT, status TEXT DEFAULT 'active'  -- active|suspended|deleting
              CHECK(status IN('active','suspended','deleting')), created_at, settings_json TEXT)
workspaces(workspace_id TEXT PK, org_id TEXT FK, name TEXT, created_at,
           UNIQUE(org_id, name))

-- Principal key is (issuer, subject) — 'sub' is only unique per IdP (§17.1).
principals(principal_id TEXT PK,                               -- e.g. sha256(issuer|subject)
           issuer TEXT, subject TEXT, kind TEXT DEFAULT 'user' -- user|service|agent
           , display_name TEXT, disabled INT DEFAULT 0, created_at,
           UNIQUE(issuer, subject))

memberships(principal_id TEXT, org_id TEXT, role TEXT, workspace_id TEXT NULL,
            PRIMARY KEY(principal_id, org_id, workspace_id, role))
roles(role TEXT PK, permissions_json TEXT)                     -- data-driven role→perms

tool_ownership(tool_name TEXT PK,                              -- tenant-qualified name (§17.2)
               owner_org TEXT, owner_workspace TEXT NULL, created_by TEXT,  -- principal_id
               visibility TEXT CHECK(visibility IN('private','org','public')),
               tags_json TEXT, trusted_tags_json TEXT)         -- who may grant by tag (§17.6)
tool_grants(id INTEGER PK, scope_type TEXT, scope_id TEXT, effect TEXT,       -- allow|deny
            match_type TEXT, match_value TEXT, created_at)      -- name|tag|owner|all
upstream_ownership(upstream_name TEXT PK, owner_org TEXT, visibility TEXT)   -- §17.9

audit(id INTEGER PK, ts, actor_principal TEXT, issuer TEXT, org_id TEXT,
      action TEXT, resource TEXT, decision TEXT, detail TEXT)   -- log allows AND denies
```

Single-file, embedded, no new dependency. **Caveat:** SQLite is single-writer /
single-instance — a multi-replica deployment (e.g. stateless streamable-HTTP,
doc "transport") needs Postgres. The store is an interface with SQLite and
Postgres backends; a JSON-file backend suits single-tenant/dev (§18.1).

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
- **Onboarding is effectively platform-power (§17.4).** Onboarding runs arbitrary
  Python in the shared process, so a Developer who can `tool:onboard` can read
  *any* tenant's data/secrets/files. Under logical multi-tenancy this means
  `tool:onboard` must be treated as a **trusted, org-admin-level** capability in
  multi-tenant deployments — not a routine Developer right. Default the Developer
  onboarding grant **off** when `MCP_RBAC_ENABLED=true`.
- **Existence disclosure (§17.7):** return **404**, not 403, for a tool the
  caller may not see, so error codes don't confirm another tenant's tools exist.
- **Inbound tenant headers:** `X-Tenant-Id`/`X-Workspace-Id` must be **stripped
  at the trusted edge** and only accepted from the app itself; always
  re-validated against membership regardless.

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
MCP_RBAC_MODE=enforce            # shadow | enforce  (shadow = log decisions, don't block, §19)
MCP_RBAC_CACHE_TTL_SEC=30        # principal/permission cache TTL (§18.2)
MCP_TENANCY_DB_BACKEND=sqlite    # sqlite | postgres | json  (§18.1)
MCP_DEFAULT_MULTI_ORG=deny       # >1 membership & no tenant header → deny | pick-newest (§17.8)
# API keys become identities when RBAC is on: map named keys → principals
MCP_API_KEYS_FILE=config/api_keys.json   # {"<key>": {"subject": "...", "org": "..."}} (§17.3)
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
   Phase 5? (§18.4 argues *at least basic* quotas are v1.)
3. **Custom roles** — ship the 4 built-ins only, or expose role CRUD in v1?
4. **Cross-tenant tool sharing** — allow an org to publish a tool `public` to
   other orgs, or keep `public` = platform-only?
5. **Onboarding in multi-tenant** — is `tool:onboard` allowed for tenant
   Developers at all, given §17.4? (Recommend: admin-only until Phase 5.)

---

## 17. Corner cases & edge conditions (SDE5 review)

Each item is a real gap in §§1–16; the fix is authoritative.

### Identity
- **17.1 `subject` is not globally unique.** `sub` is unique only *per issuer*.
  With >1 IdP (or IdP re-provisioning), two people can share a `sub`. **Fix:**
  the principal key is `(issuer, subject)` → a derived `principal_id`
  (schema §8). All memberships/grants/audit key on `principal_id`.
- **17.2 Tool name collision across tenants** *(the sharpest one)*. The FastMCP
  registry is one global namespace; two tenants can't both hold `weather`.
  **Fix:** onboarded tools are stored **tenant-qualified** (`org__ws__name`);
  the caller uses the short name, resolved within their active tenant. Platform
  tools stay bare + `public`. This also affects `/admin/reload`, `disable`,
  `enable`, and the loader's first-wins policy — all become tenant-aware.
- **17.3 `api_key` mode has no per-user identity.** A single shared key = one
  principal, so RBAC can't distinguish callers. **Fix:** support **named API
  keys → principals** (`MCP_API_KEYS_FILE`); document that fine-grained RBAC
  needs JWT. A lone shared key maps to one service principal.
- **17.8 Ambiguous active org.** A principal in ≥2 orgs with no `X-Tenant-Id`
  is undefined in §4. **Fix:** `MCP_DEFAULT_MULTI_ORG` = `deny` (return `409
  tenant-required`) or `pick-newest`. Single membership auto-selects.
- **17.10 Machine/agent identity (M2M).** OAuth `client_credentials` tokens have
  no human `sub`; use `client_id` as the subject with `kind='service'`. "Agent
  Consumer" is typically an M2M principal.
- **17.11 Token revocation / role change latency.** A cached principal can
  outlive a revoked token or a removed role. **Fix:** short cache TTL (§18.2) +
  cache-bust on membership/grant writes; never cache across the JWT `exp`.

### Authorization
- **17.4 Onboarding = privilege escalation** (see §9). `tool:onboard` runs
  arbitrary in-process code → cross-tenant read. Treat as admin-level; default
  Developer onboarding **off** under RBAC.
- **17.5 `tool:manage (own)` needs tool ownership by principal.** "Own" = tools
  the principal created → `tool_ownership.created_by` (schema §8), not just same
  org.
- **17.6 Tag-based grants + user-set tags = escalation.** A `tag:finance allow`
  grant auto-applies to any future tool tagged `finance`; if a Developer can tag
  their own onboarded tool `finance`, they self-grant. **Fix:** only admins set
  tags used in grants (`trusted_tags`), or tag-grants require an admin-owned tag
  namespace.
- **17.7 403-vs-404 existence disclosure** — return 404 for not-visible tools
  (see §9).
- **17.12 Workspace-scoped permission resolution.** Effective permissions =
  union of role perms for the principal's bindings **matching the active
  workspace** ∪ org-level (workspace-null) bindings. An org_admin is org-wide; a
  Developer bound to W1 gets nothing in W2. Make the resolution algorithm
  explicit and test it.
- **17.13 Grant precedence is deny-override.** Any matching `deny` at *any*
  scope (principal/role/workspace/org) denies, regardless of a more-specific
  `allow`. Simple and safe; documented so no one expects "most-specific wins".

### Tenancy / data
- **17.9 Upstreams (federation) have no tenancy.** `/mcp/upstreams*` and
  `upstreams.json` are global today. **Fix:** `upstream_ownership(owner_org,
  visibility)`; a tenant only sees/calls upstreams owned-by or shared-to their
  org; upstream secrets are per-tenant. Otherwise multi-tenancy leaks remote
  credentials/targets across orgs.
- **17.14 Org lifecycle.** Suspending/deleting an org must block its members and
  cascade (workspaces, memberships, grants, tool ownership). **Fix:** `status`
  column (§8) + soft-delete + a cascade/GC job. Suspended org → all members 403.
- **17.15 Superadmin bootstrap (chicken-and-egg).** The first org_admin can't be
  created by an org_admin. **Fix:** the `MCP_ADMIN_TOKEN` → `platform_superadmin`
  mapping is the bootstrap path; document it and the "create first org + bind
  first admin" runbook.

## 18. Cross-cutting concerns

- **18.1 Horizontal scaling vs SQLite.** SQLite is single-file/single-writer, so
  it **breaks multi-replica** deployments (which the stateless streamable-HTTP
  transport otherwise enables). Ship a `Store` interface with **SQLite (default,
  single-node)** and **Postgres (multi-node)** backends; pick via
  `MCP_TENANCY_DB_BACKEND`. Call this out in ops docs.
- **18.2 Performance / caching.** An RBAC decision per request must not hit the
  DB every time. Cache `principal → {roles, permissions, grants}` with a short
  TTL (`MCP_RBAC_CACHE_TTL_SEC`, default 30s) and invalidate on writes. Bound the
  grant-evaluation cost (compile grants into a matcher per principal).
- **18.3 Schema migrations.** A `schema_meta(version)` table + ordered
  migrations; the store refuses to start on an unknown/newer version. Needed
  from day one so Phase 1→3 schema growth is safe.
- **18.4 Noisy-neighbor / quotas.** Logical multi-tenancy shares one process, so
  one tenant's agent can starve others (CPU, connections, pip installs). At
  least **basic per-org concurrency + rate limits are v1**, not Phase 5 — a token
  bucket keyed by `org_id` on `tool:call`/onboard. Full resource isolation stays
  Phase 5.
- **18.5 Tenant-labeled observability.** `/metrics` and the audit log gain an
  `org` label/field (cardinality bounded by #orgs). Enables per-tenant usage,
  error rates, and abuse detection. Audit records **denials** too (a security
  signal), keyed on `principal_id`.
- **18.6 Config validation.** `validate_context` must reject contradictions:
  `MCP_RBAC_ENABLED=true` with `MCP_AUTH_TYPE=none` (no identity to bind), or an
  unwritable `MCP_TENANCY_DB`, or `postgres` backend without a DSN.

## 19. Safe rollout — shadow → enforce

Flipping deny-by-default on a live deployment is high-risk. Add
`MCP_RBAC_MODE`:
- **`shadow`** — resolve the principal and evaluate every decision, but **do not
  block**; log `would-deny` with the principal, permission, and resource. Run
  here until the logs are clean and grants are seeded correctly.
- **`enforce`** — decisions are binding.

Rollout: enable RBAC in `shadow` → seed orgs/grants from the shadow logs →
switch to `enforce`. This makes the migration observable and reversible, and is
the single most important operational safeguard for a permissions change.

### Revised phase notes
- Add **shadow mode** to **Phase 2** (ship the PDP in shadow first).
- Add **upstream tenancy (§17.9)** and **basic quotas (§18.4)** to **Phase 3**.
- Add the **`Store` interface + Postgres backend (§18.1)** as a Phase 1
  sub-task if multi-replica is a near-term requirement.
