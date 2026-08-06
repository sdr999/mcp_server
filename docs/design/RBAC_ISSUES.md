# RBAC / Multi-Tenancy — Implementation Issues

Trackable checklist derived from [`IMPLEMENTATION_REVIEW.md`](IMPLEMENTATION_REVIEW.md).
Each item maps to a design-doc section (§) and the code location. Check off as
fixed. Severity: 🔴 Critical · 🟠 High · 🟡 Medium.

## 🔴 Critical

- [x] **C1 — Tenant boundary trusts the `X-Tenant-Id` header, not membership.**
  `identity.py` sets `principal.org_id = active_org` unvalidated; `resolve_principal`
  is never called; each backend's `resolve_principal` also did `org_id = active_org or …`.
  → cross-tenant access by spoofing the header. (§9, §17.8)
  _Fix: `select_tenant_context()` helper honors a tenant header only for member orgs;
  all backends route through it; middleware calls `resolve_principal`; anonymous pinned to `default`._
- [x] **C2 — Grant precedence is not deny-override.** Evaluator returned on the first
  matching grant, so an `allow` before a `deny` won. (§17.13)
  _Fix: scan all matching grants, any matching `deny` wins; unknown `scope_type` no longer matches all._

## 🟠 High

- [x] **H1 — Store not authoritative for roles/permissions.** Roles from JWT claims,
  perms from a hardcoded map in `identity.py`; store `roles` table unused on hot path
  → two sources of truth. (§4, §5, §20.1)
  _Fix: one canonical `BUILTIN_ROLE_PERMISSIONS` matrix in `identity.py`;
  `permissions_for_roles()` derives from it; the seeder seeds from the same matrix.
  Store stays runtime-authoritative via resolve_principal (C1); this is the seed +
  RBAC-off fallback, provably in sync (tested)._
- [x] **H2 — Grant `match_type` mismatch → tag/all grants are dead code.** Model uses
  `{name,tag,owner,all}`; evaluator handled only `{exact,prefix,glob}`; `scope_type`
  used `"user"` vs model `"principal"`. (§6, §17.6) — `rbac/evaluator.py`, `tenancy/models.py`
  _Fix: `_match_grant` now supports `name` (glob-aware) / `tag` / `owner` / `all` and keeps
  the pattern aliases for back-compat; ownership is resolved once and reused; `scope_type`
  alias handled in `_grant_applies_to` (C2). Legacy `verify`/pattern grants still work._
- [x] **H3 — Default role `developer` for any signed token** (incl. `tool:onboard`).
  (§6, §17.4) — `identity.py:build_principal_from_claims`
  _Fix: `DEFAULT_ROLE = "agent_consumer"`; a bare signed token no longer inherits
  onboarding/management; unknown roles contribute no permissions._
- [x] **H4 — No shadow mode.** No `MCP_RBAC_MODE=shadow|enforce`; enforcement was
  immediately binding; `shadow_deny` was defined but never produced. (§19)
  _Fix: `MCP_RBAC_MODE` config (+ validation); `enforce()` in shadow mode logs a
  would-deny (WARNING → file), writes a `shadow_deny` audit row, increments
  `mcp_authz_shadow_denials_total`, and returns None (proceeds). Also wired
  `MCP_RBAC_ENABLED` parsing, which was missing so RBAC couldn't be turned on._
- [x] **H5 — Decision cache not invalidated on all writes.** `DecisionCache.invalidate()`
  had no callers on the membership/org-delete paths; TTL defaulted to 300s not 30s.
  (§18.2, §21.4) — `rbac/cache.py`
  _Fix: `_invalidate_rbac_cache()` helper wired into `bind_member` (principal-scoped),
  `delete_org` (org-scoped), and `add_tool_grant` (full clear); TTL default → 30s._

## 🟡 Medium

- [x] **M1 — Factory is if/elif, not the registry/`module:Factory` pattern; unknown
  backend falls back to sqlite instead of fail-fast.** (§20.2, §20.6) — `tenancy/__init__.py`
  _Fix: `register_backend()` registry + `create_tenancy_store()` resolving a
  `module.path:Factory` custom spec; unknown backend now raises `RuntimeError`._
- [x] **M2 — 403 vs 404 existence disclosure** on deny. (§17.7) — `security.py:enforce`
  _Fix: a denied `tool:call`/`tool:manage` returns **404** with the same body as an
  unknown tool; other denials return a generic **403 "forbidden"** (no decision
  label). Real reason is logged server-side only._
- [x] **M3 — Weakened JWT validation.** (§9) — `identity.py`
  _Fix: PyJWKClient fallback drops `HS256` (asymmetric `ES256`/`RS256` only) and
  verifies audience when `MCP_JWT_AUDIENCE` is configured (now on `app.state`)._
- [x] **M4 — Seed lock + role reconcile.** (§21.1, §21.5) — `tenancy/seeder.py`
  _Fix: `MCP_TENANCY_RECONCILE_ROLES` re-syncs drifted built-in role perms on boot;
  seed writes are idempotent create-if-absent. Backend-level distributed lock
  (multi-replica) is documented as deferred (§21.1)._
- [x] **M5 — Hardcoded Supabase issuer + broken superadmin binding.** (§12) — `tenancy/seeder.py`
  _Fix: removed the hardcoded issuer default and the email-keyed superadmin binding
  (it could never match `resolve_principal`, which keys on the JWT `sub`); superadmin
  is granted via the email-claim match in the middleware + the admin-token bootstrap._
- [x] **M6 — Interface drift.** (§20.1, §21.11) — `tenancy/base.py` + 4 backends
  _Fix: added `is_empty()` and `close()` (wired into lifespan shutdown) and
  `limit`/`offset` pagination on `list_workspaces`/`list_org_members`/`list_roles`/
  `list_tool_grants` across all four backends._
- [x] **M7 — Committed runtime artifacts.**
  _Fix: `git rm --cached` `src/data/tenancy.db` + `src/logs/`; added `.gitignore` rules._
- [x] **M8 — ABAC `trusted_tags` reinterpretation.** (§17.6) — `rbac/abac.py`
  _Fix (clarify, no behavior change): documented that ABAC `trusted_tags` is a
  required-attributes gate distinct from §17.6's grant-authoring tag namespace, and
  that the self-grant-escalation vector is closed because grant creation is
  admin-only (MCP_ADMIN_TOKEN)._

## Faithful to design (no action)

`derive_principal_id` (§21.10) · `TokenCache` exp-capped TTL (§17.11) · async interface
+ `resolve_principal` signature (§21.2/3) · `models.py` vs §8 · constant-time admin compare ·
ContextVar principal · four backends behind one interface + tests.
