# Design: Multi-Tenancy & RBAC for the MCP Tool Server

Status: **Proposed (revised after SDE5 review — see §17–§19)** · Branch: `org`
· Scope of this doc: design only (no implementation)

> **Review note:** §§1–16 are the original proposal. §17 (corner cases), §18
> (cross-cutting concerns), §19 (safe rollout), and §20 (pluggable store) are the
> review layer and, where they conflict with an earlier section, **they win** — the
> most important being: the principal key is `(issuer, subject)` not `subject`
> (§17.1); onboarded tool names are **tenant-qualified** to survive the flat FastMCP
> registry (§17.2); and the tenancy store is a **pluggable, env-selected backend**
> (SQLite is only the *default*), following the repo's plugin pattern, with
> first-start seeding (§20).

## Decisions baked into this design

| Question | Decision |
|----------|----------|
| Identity source | **Hybrid** — a JWT (`bearer_jwt` mode) proves *who* the caller is (the `subject`); the **local tenancy store** is the source of truth for org/workspace membership, role bindings, and tool grants, joined by `subject`. |
| Isolation depth | **RBAC + logical multi-tenancy** — scoped visibility/calls, per-tenant catalogs, roles, grants, quotas — all **in-process**. Tenant tools are trusted. Hard execution isolation is an explicit **non-goal** here (see §9). |
| Store | **Pluggable, plug-and-play** — a `TenancyStore` interface with interchangeable backends selected by `MCP_TENANCY_STORE` (`memory` \| `json` \| `sqlite` \| `postgres` \| custom), mirroring the existing `plugins/` pattern. **SQLite is the default** (stdlib `sqlite3`, no new hard dependency); nothing above the interface knows which backend is live. On first start the store **self-seeds** roles/default org if empty (§20). |

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
| 3 | **Persistence** | flat files/env only | Pluggable `TenancyStore` (backend via `MCP_TENANCY_STORE`; SQLite default) with first-start seeding (Phase 1, §20) |
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
| `plugins/tenancy/` | **The pluggable store package** (§20): the `TenancyStore` interface, a backend registry + factory (`create_store(ctx)`), the built-in backends (`memory`/`json`/`sqlite`/`postgres`), and the first-start seeder. Exposes orgs, workspaces, memberships, role bindings, tool ownership & grants via CRUD + queries — backend-agnostic. |
| `plugins/rbac.py` | The Policy Decision Point: `require(request, permission, resource=None)`. Wraps/derives from today's `enforce()`. |

> The store is the one component with real backend variability, so it graduates
> from a single `tenancy.py` module to a small `plugins/tenancy/` package. The PDP
> (`rbac.py`) and identity middleware depend only on the `TenancyStore` interface —
> never on a concrete backend — so swapping storage is a config change, not a code
> change (§20).

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

## 8. Data model (reference schema)

The entities below are the **logical model** the `TenancyStore` interface exposes.
The SQL is the concrete shape for the relational backends (SQLite / Postgres); the
`json`/`memory` backends hold the same entities as nested dicts. No caller sees SQL
— everything goes through the interface (§20).

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

**Backend selection is config, not code.** SQLite (single-file, embedded, no new
dependency) is the **default** and suits single-node deployments; a multi-replica
deployment (e.g. stateless streamable-HTTP) selects `postgres`; `json`/`memory`
suit dev and tests. All four implement the same `TenancyStore` interface behind
`create_store(ctx)`, chosen by `MCP_TENANCY_STORE` — see §20 for the interface,
registry, and first-start seeding.

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

# --- Pluggable tenancy store (§20) -----------------------------------------
MCP_TENANCY_STORE=sqlite         # memory | json | sqlite | postgres | <dotted.path:Factory>
MCP_TENANCY_DB=data/tenancy.db   # sqlite: file path (relative to src/); json: file path
MCP_TENANCY_DSN=                 # postgres: connection string (required for that backend)
MCP_TENANCY_SEED=true            # on first start, if store is empty seed roles + default org (§20)
MCP_TENANCY_SEED_FILE=           # optional path to a seed doc overriding the built-in defaults

MCP_DEFAULT_ORG=default          # org used to auto-own existing tools on enable / seed
MCP_TENANT_HEADER=X-Tenant-Id
MCP_WORKSPACE_HEADER=X-Workspace-Id
MCP_JWT_SUBJECT_CLAIM=sub        # hybrid identity mapping
MCP_JWT_ORG_CLAIM=org            # optional JIT-provisioning seed
MCP_JWT_ROLES_CLAIM=roles        # optional JIT-provisioning seed
MCP_RBAC_JIT_PROVISION=false     # allow claim-seeded first-login binding
MCP_RBAC_MODE=enforce            # shadow | enforce  (shadow = log decisions, don't block, §19)
MCP_RBAC_CACHE_TTL_SEC=30        # principal/permission cache TTL (§18.2)
MCP_DEFAULT_MULTI_ORG=deny       # >1 membership & no tenant header → deny | pick-newest (§17.8)
# API keys become identities when RBAC is on: map named keys → principals
MCP_API_KEYS_FILE=config/api_keys.json   # {"<key>": {"subject": "...", "org": "..."}} (§17.3)
```

`MCP_TENANCY_STORE` replaces the earlier `MCP_TENANCY_DB_BACKEND` name; it also
accepts a `module.path:Factory` string so a deployment can register a custom
backend (Redis, DynamoDB, a hosted API) **without patching the server** (§20).

## 12. Backward compatibility & migration

- **Default off.** `MCP_RBAC_ENABLED=false` → identical to current server.
- **On first enable:** the store's **first-start seeder** (§20) runs — if the
  store is empty it creates the built-in roles (one row each), a `default` org +
  `default` workspace, maps the existing `MCP_ADMIN_TOKEN` to a
  `platform_superadmin` service principal, and sets all existing `src/tools/*` to
  `owner=default`, `visibility=public`. Existing single-tenant clients keep
  working; multi-tenancy is additive. Seeding is idempotent and backend-agnostic.
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
| **1 — Tenancy store & model** | `TenancyStore` interface + backend registry/factory; `memory`+`json`+`sqlite` backends (Postgres stub); orgs/workspaces/members/roles/grants; admin CRUD; **first-start seeding** (§20). | Low |
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
  transport otherwise enables). This is exactly why the store is pluggable: the
  `TenancyStore` interface ships **SQLite (default, single-node)** and **Postgres
  (multi-node)** backends, picked via `MCP_TENANCY_STORE` (§20). Call the
  single-node caveat out in ops docs.
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
- The **`TenancyStore` interface + backend registry (§20)** is now **core to
  Phase 1**, not an optional sub-task; the Postgres backend can lag as a stub and
  land when multi-replica is a near-term requirement, since it's just one more
  registered backend behind the same interface.

---

## 20. Pluggable tenancy store (plug-and-play)

The store must **not** hard-code SQLite. It follows the same
strategy/registry/factory shape the rest of `plugins/` already uses (a concrete
implementation chosen from env, resolved once at startup, consumed only through
an interface). SQLite is merely the registered **default**.

### 20.1 The interface

`plugins/tenancy/base.py` defines one `Protocol` that every backend implements.
Nothing above it (the PDP, identity middleware, admin routes) references SQL or a
concrete class:

```python
class TenancyStore(Protocol):
    # lifecycle
    def init_schema(self) -> None: ...            # create tables/indexes/keyspace; idempotent
    def schema_version(self) -> int: ...          # for migrations (§18.3)
    def is_empty(self) -> bool: ...               # drives first-start seeding (§20.4)
    def close(self) -> None: ...

    # roles (data-driven, §5)
    def upsert_role(self, role: str, permissions: list[str]) -> None: ...
    def get_role(self, role: str) -> Role | None: ...
    def list_roles(self) -> list[Role]: ...

    # orgs / workspaces
    def create_org(self, org_id: str, name: str, status: str = "active") -> None: ...
    def get_org(self, org_id: str) -> Org | None: ...
    def create_workspace(self, org_id: str, ws_id: str, name: str) -> None: ...

    # principals & membership  (keyed on principal_id = f(issuer, subject), §17.1)
    def upsert_principal(self, issuer: str, subject: str, kind: str = "user") -> str: ...
    def bind_role(self, principal_id: str, org_id: str, role: str,
                  workspace_id: str | None = None) -> None: ...
    def memberships_for(self, principal_id: str) -> list[Membership]: ...

    # tools & grants
    def set_tool_ownership(self, tool_name: str, owner_org: str, *,
                           owner_workspace: str | None, created_by: str,
                           visibility: str, tags: list[str]) -> None: ...
    def add_grant(self, scope_type: str, scope_id: str, effect: str,
                  match_type: str, match_value: str) -> None: ...
    def grants_for(self, principal_id: str, org_id: str,
                   workspace_id: str | None) -> list[Grant]: ...

    # audit
    def record_audit(self, actor_principal: str, action: str, resource: str,
                     decision: str, detail: str = "") -> None: ...
```

The interface is deliberately **coarse** — it exposes the operations the PDP and
admin routes need, not raw rows — so a non-SQL backend (Redis, DynamoDB, a hosted
API) can implement it without pretending to be a relational DB. Return types are
small dataclasses (`Role`, `Org`, `Membership`, `Grant`, …), never driver cursors.

### 20.2 The registry + factory

`plugins/tenancy/__init__.py` holds a name → constructor registry and a single
factory. This mirrors how the server already resolves a strategy from config:

```python
_BACKENDS: dict[str, Callable[[AppContext], TenancyStore]] = {}

def register_backend(name: str, ctor: Callable[[AppContext], TenancyStore]) -> None:
    _BACKENDS[name.lower()] = ctor

def create_store(ctx: AppContext) -> TenancyStore:
    spec = ctx.tenancy_store            # from MCP_TENANCY_STORE
    if ":" in spec:                     # "package.module:Factory" → custom backend
        store = _load_dotted(spec)(ctx)
    else:
        try:
            store = _BACKENDS[spec.lower()](ctx)
        except KeyError:
            raise ConfigError(f"unknown MCP_TENANCY_STORE={spec!r}; "
                              f"known: {sorted(_BACKENDS)}")
    store.init_schema()
    maybe_seed(ctx, store)              # §20.4
    return store

# built-ins register themselves on import
register_backend("memory",   lambda ctx: MemoryStore())
register_backend("json",     lambda ctx: JsonStore(ctx.tenancy_db))
register_backend("sqlite",   lambda ctx: SqliteStore(ctx.tenancy_db))
register_backend("postgres", lambda ctx: PostgresStore(ctx.tenancy_dsn))
```

`create_store(ctx)` is called once during app lifespan (like `UpstreamRegistry`
today) and the resulting instance is stashed on `AppContext`/`app.state` for the
PDP and routes. **Swapping storage is a one-line env change**; adding a backend is
a `register_backend` call — no edits to any consumer.

### 20.3 Built-in backends

| Backend (`MCP_TENANCY_STORE`) | Module | Use case | Dependency |
|---|---|---|---|
| `memory` | `tenancy/memory.py` | tests, ephemeral dev; not persisted | none |
| `json` | `tenancy/json_store.py` | single-tenant / small; human-readable file, atomic `0600` writes (reuses the `upstreams.json` discipline) | none |
| `sqlite` *(default)* | `tenancy/sqlite_store.py` | single-node production | stdlib `sqlite3` |
| `postgres` | `tenancy/postgres_store.py` | multi-replica / HA | `psycopg` (soft import; only if selected) |
| custom | `module.path:Factory` | Redis/DynamoDB/hosted API | supplied by the deployment |

The Postgres dependency stays **soft** — imported only when that backend is
selected — so the default install adds nothing (consistent with the "no new hard
dependency" rule and the existing soft-import pattern for the agentic framework).

### 20.4 First-start seeding

On startup, after `init_schema()`, `maybe_seed(ctx, store)` runs — **backend
agnostic**, driven entirely through the interface:

```python
def maybe_seed(ctx, store):
    if not ctx.tenancy_seed or not store.is_empty():
        return                                   # idempotent: only seed a fresh store
    seed = load_seed(ctx.tenancy_seed_file) or DEFAULT_SEED
    for role, perms in seed["roles"].items():    # one row per built-in role (§5)
        store.upsert_role(role, perms)
    store.create_org(ctx.default_org, ctx.default_org)      # 'default' org …
    store.create_workspace(ctx.default_org, "default", "default")   # … + workspace
    if ctx.admin_token:                          # bootstrap superadmin (§17.15)
        pid = store.upsert_principal(issuer="local", subject="admin-token",
                                     kind="service")
        store.bind_role(pid, ctx.default_org, "platform_superadmin")
    store.record_audit("system", "seed", "tenancy", "seeded", detail=str(list(seed["roles"])))
```

`DEFAULT_SEED` ships **one entry per built-in role** from the §5 matrix
(`platform_superadmin`, `org_admin`, `developer`, `agent_consumer`) with their
default permission sets. Properties:

- **Idempotent & safe:** guarded by `is_empty()` — a restart, or enabling on an
  existing store, never re-seeds or clobbers operator changes.
- **Overridable:** `MCP_TENANCY_SEED_FILE` points at a JSON/YAML doc to replace
  `DEFAULT_SEED` (custom roles, extra orgs) without touching code.
- **Disable-able:** `MCP_TENANCY_SEED=false` for deployments that provision the
  store out-of-band (e.g. Terraform/migrations against Postgres).
- **Bootstraps the chicken-and-egg admin (§17.15):** the first
  `platform_superadmin` binding comes from seeding, not from an API call.

### 20.5 Contract test (one suite, every backend)

Because all backends share the interface, a **single parametrized test suite**
runs against every registered backend (`memory`/`json`/`sqlite`, and `postgres`
in CI when a DSN is present). It asserts identical semantics — grant deny-override
(§17.13), workspace-scoped resolution (§17.12), `is_empty()`/seed idempotency,
`(issuer,subject)` uniqueness (§17.1). This is what makes the store genuinely
plug-and-play: correctness is defined by the interface, not by any one backend.

### 20.6 Config validation (extends §18.6)

`validate_context` rejects: an unknown `MCP_TENANCY_STORE`; `postgres` without
`MCP_TENANCY_DSN`; `sqlite`/`json` with an unwritable path; a `module:Factory`
string that fails to import or doesn't satisfy the `TenancyStore` protocol; and
`MCP_RBAC_ENABLED=true` with `MCP_AUTH_TYPE=none` (no identity to bind). Fail fast
at startup, never mid-request.
