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

- [ ] **H1 — Store not authoritative for roles/permissions.** Roles from JWT claims,
  perms from a hardcoded map in `identity.py`; store `roles` table unused on hot path
  → two sources of truth. (§4, §5, §20.1) _Partially addressed by C1; reconcile the claim fallback._
- [x] **H2 — Grant `match_type` mismatch → tag/all grants are dead code.** Model uses
  `{name,tag,owner,all}`; evaluator handled only `{exact,prefix,glob}`; `scope_type`
  used `"user"` vs model `"principal"`. (§6, §17.6) — `rbac/evaluator.py`, `tenancy/models.py`
  _Fix: `_match_grant` now supports `name` (glob-aware) / `tag` / `owner` / `all` and keeps
  the pattern aliases for back-compat; ownership is resolved once and reused; `scope_type`
  alias handled in `_grant_applies_to` (C2). Legacy `verify`/pattern grants still work._
- [ ] **H3 — Default role `developer` for any signed token** (incl. `tool:onboard`).
  Should floor at `agent_consumer`. (§6, §17.4) — `identity.py:build_principal_from_claims`
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

- [ ] **M1 — Factory is if/elif, not the registry/`module:Factory` pattern; unknown
  backend falls back to sqlite instead of fail-fast.** (§20.2, §20.6) — `tenancy/__init__.py`
- [ ] **M2 — 403 vs 404 existence disclosure** on deny (leaks tool existence + decision
  codes). (§17.7) — `security.py:enforce`
- [ ] **M3 — Weakened JWT validation:** `verify_aud=False` and `HS256` allowed alongside
  `RS256/ES256`. (§9) — `identity.py`
- [ ] **M4 — Seed lock is in-process `asyncio.Lock`, not a backend-level lock;** seeding
  never reconciles existing role perms. (§21.1, §21.5) — `tenancy/seeder.py`
- [ ] **M5 — Hardcoded Supabase issuer default;** seeder binds superadmin by email while
  `resolve_principal` keys on `sub`. (§12) — `tenancy/seeder.py`
- [ ] **M6 — Interface drift:** no `is_empty()`, no `close()`/pool lifecycle, no migration
  method; pagination only on `list_orgs`. (§20.1, §21.11) — `tenancy/base.py`
- [ ] **M7 — Committed runtime artifacts:** `src/data/tenancy.db`, `src/logs/mcp_server.json.log`.
- [ ] **M8 — Unplanned ABAC** reinterprets `trusted_tags`; phase labels don't match §14.
  (§17.6) — `rbac/abac.py`

## Faithful to design (no action)

`derive_principal_id` (§21.10) · `TokenCache` exp-capped TTL (§17.11) · async interface
+ `resolve_principal` signature (§21.2/3) · `models.py` vs §8 · constant-time admin compare ·
ContextVar principal · four backends behind one interface + tests.
