# Implementation Review: Multi-Tenancy & RBAC vs. the Design Doc

Status: **Review of the merged Phase 1–3 implementation** · Branch: `org`
· Reviews the code under `src/plugins/{identity,security}.py`,
`src/plugins/tenancy/*`, `src/plugins/rbac/*` against
[`MULTI_TENANCY_RBAC.md`](MULTI_TENANCY_RBAC.md).

> Section references (§) point at the design doc. File references are
> `path:line`. Findings are ranked by severity; the two **Critical** items break
> the core tenant-isolation guarantee and are treated as blockers.

## Verdict

A substantial, real landing: the pluggable store with four backends
(`memory`/`json`/`sqlite`/`mongodb`), the first-start seeder, identity
propagation, a policy evaluator, a decision cache, catalog scoping, and per-layer
tests are all present and broadly match the intended shape. Several pieces are
faithful to the doc (see the last section). But the authorization path departs
from the **hybrid, store-authoritative** decision (§4) in ways that let a caller
cross tenant boundaries, and grant precedence is not deny-override.

## Critical

### C1 — Tenant isolation is enforced against a self-asserted header, not membership
`IdentityMiddleware` assigns the principal's org straight from the (charset-only
sanitized) `X-Tenant-Id` header — `identity.py` `principal.org_id = active_org` —
and the evaluator's tenant-boundary check compares tool ownership against that
header-derived org (`rbac/evaluator.py`, `ownership.owner_org != principal.org_id`).
A caller can therefore set `X-Tenant-Id: <victim-org>` and pass the boundary for
that org's private tools. This is exactly the spoofing attack §9 and §17.8 said
to prevent by **always validating the requested org against the principal's store
memberships**. The designed fix — `resolve_principal(issuer, subject, active_org,
active_ws)` — exists in the interface and all four backends but was **never
called** (0 call sites); worse, each backend's `resolve_principal` itself did
`org_id = active_org or …`, trusting the header too.

**Fix (this change):** a shared `select_tenant_context()` (in `identity.py`) that
honors a tenant header only when the caller has a membership in that org, and
collapses non-members to the default (public) org; every backend's
`resolve_principal` now routes org/workspace selection through it, and
`IdentityMiddleware` calls `resolve_principal` so roles/permissions/org come from
validated memberships when RBAC is enabled. Anonymous callers are pinned to the
`default` org regardless of header.

### C2 — Grant precedence is not deny-override (§17.13)
`rbac/evaluator.py` returned on the **first** matching grant, so an `allow`
ordered before a matching `deny` wins — precedence depends on the row order
`list_tool_grants()` happens to return. The doc requires: any matching `deny` at
any scope wins over any `allow`.

**Fix (this change):** the evaluator now scans **all** matching grants, and a
single matching `deny` denies regardless of any `allow`. Scope filtering also no
longer lets an unrecognized `scope_type` match every principal.

## High (not yet fixed)

- **H1 — Store is not authoritative for roles/permissions (§4/§20.1).** Roles come
  from JWT claims and permissions from a hardcoded map in `identity.py`
  (`build_principal_from_claims`); the store's `roles` table (seeded from
  `BUILTIN_ROLES`) was unused on the hot path → two sources of truth that drift.
  *Partially addressed by C1* (the middleware now overlays store-resolved
  roles/permissions when RBAC is on); the hardcoded claim map remains as the
  RBAC-off / fallback path and should be reconciled.
- **H2 — Grant `match_type` mismatch makes tag/all grants dead code.** Model/design
  use `{name, tag, owner, all}` (`tenancy/models.py`); the evaluator only handles
  `{exact, prefix, glob}`. Grants created per the model never match. `scope_type`
  also uses `"user"` in the evaluator vs `"principal"` in the model.
- **H3 — Default role is `developer` for any signed token** (`identity.py`),
  including `tool:onboard`/`tool:manage`. Violates deny-by-default (§6) and §17.4
  (Developer onboarding should default off under RBAC). Should floor at
  `agent_consumer`. *Mitigated where C1 applies* (store roles win when RBAC on),
  but the claim fallback still over-grants.
- **H4 — No shadow mode (§19).** No `MCP_RBAC_MODE=shadow|enforce`; enforcement is
  immediately binding. The `AuditEntry.decision` enum reserves `shadow_deny` but
  nothing produces it.
- **H5 — Cache never invalidated on writes (§18.2/§21.4).**
  `DecisionCache.invalidate()` has 0 callers; grant/membership/role changes take
  up to the TTL to apply, and the TTL defaults to 300s, not the design's 30s.

## Medium (not yet fixed)

- **M1 — Factory isn't the registry pattern (§20.2).** `create_tenancy_store` is an
  if/elif chain; no `register_backend`, no `module:Factory` hook, and an unknown
  backend falls back to sqlite with a warning instead of the §20.6 fail-fast.
- **M2 — 403-vs-404 disclosure (§17.7).** `enforce` returns 403 + reason + internal
  decision code on deny, confirming tool existence.
- **M3 — Weakened JWT validation.** The PyJWKClient fallback sets
  `verify_aud: False` and allows `HS256` alongside `RS256/ES256` (`identity.py`).
- **M4 — Seed lock is in-process only** (`asyncio.Lock`), not the backend-level
  lock §21.1 wants for multi-replica; seeding also never reconciles an existing
  role's permissions (§21.5).
- **M5 — Hardcoded Supabase issuer default** in `tenancy/seeder.py` bakes one
  deployment's IdP into the code. (Also: the seeder binds the superadmin by
  email-as-subject, while `resolve_principal` keys on the JWT `sub` — these won't
  match unless `sub == email`.)
- **M6 — Interface drift (§20.1/§21.11):** no `is_empty()`, no `close()`/pool
  lifecycle, no exposed migration method; pagination only on `list_orgs`.
- **M7 — Committed runtime artifacts:** `src/data/tenancy.db` and
  `src/logs/mcp_server.json.log`.
- **M8 — Unplanned scope:** ABAC (`rbac/abac.py`) isn't in the design and
  reinterprets `trusted_tags` (§17.6). Code phase labels don't match §14.

## Faithful to the design (credit)

- `derive_principal_id` is the §21.10 canonical-JSON sha256.
- `TokenCache` hashes tokens and caps TTL at `exp` (§17.11).
- The store interface is genuinely `async` with the `resolve_principal` signature
  (§21.2/§21.3).
- `models.py` matches §8 (org `status`, `trusted_tags`, audit `decision`).
- Constant-time admin-token compare; ContextVar principal with leak-free reset.
- All four backends implement one interface, with per-layer tests.

## Recommended order

1. **C1, C2** — blockers (this change).
2. **H2** (grant matching) — tenant grants silently don't work until fixed.
3. **H4** (shadow mode) + **H5** (cache invalidation) — safe rollout + correctness.
4. **H1/H3** reconciliation, then the Medium cleanups.
