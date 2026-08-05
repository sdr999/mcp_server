"""Regression tests for the C1 (tenant-header anti-spoofing) and C2
(deny-override grant precedence) fixes. See docs/design/IMPLEMENTATION_REVIEW.md.
"""
from __future__ import annotations

import asyncio

import pytest

from plugins.identity import Principal, derive_principal_id, select_tenant_context
from plugins.tenancy.memory import MemoryTenancyStore
from plugins.tenancy.models import Membership
from plugins.rbac.evaluator import PolicyEvaluator
from plugins.rbac.cache import DecisionCache


# --------------------------------------------------------------------------
# C1 — a tenant header is honored ONLY for orgs the caller is a member of.
# --------------------------------------------------------------------------

def test_select_tenant_context_ignores_spoofed_org():
    m = [Membership(principal_id="p", org_id="acme", role="developer", workspace_id="default")]
    # Member requests their own org -> honored.
    assert select_tenant_context(m, "acme", "default")[0] == "acme"
    # Member spoofs a foreign org -> ignored, pinned to their own membership.
    assert select_tenant_context(m, "victim", "default")[0] == "acme"
    # No header -> auto-select the single membership.
    assert select_tenant_context(m, None, None)[0] == "acme"


def test_select_tenant_context_non_member_pinned_to_default():
    # A caller with no memberships can never assert another tenant via a header.
    assert select_tenant_context([], "victim", "default")[0] == "default"


def test_resolve_principal_does_not_trust_org_header():
    async def _run():
        store = MemoryTenancyStore()
        await store.save_role("developer", ["tool:list", "tool:call"])
        await store.create_org("acme", "Acme")
        await store.create_org("victim", "Victim")
        pid = derive_principal_id("iss", "alice")
        await store.bind_member(pid, org_id="acme", role="developer")

        # Alice is a member of acme only. Spoofing X-Tenant-Id: victim must NOT
        # place her in victim's tenant context.
        p = await store.resolve_principal("iss", "alice", active_org="victim")
        assert p.org_id == "acme"

        # A stranger (no membership) forcing victim -> collapses to default.
        p2 = await store.resolve_principal("iss", "mallory", active_org="victim")
        assert p2.org_id == "default"

    asyncio.run(_run())


def test_cross_tenant_private_tool_denied_after_c1():
    """End-to-end: a member of acme cannot reach victim's private tool by
    spoofing the org header, because their resolved org stays acme."""
    async def _run():
        store = MemoryTenancyStore()
        await store.save_role("developer", ["tool:list", "tool:call"])
        await store.create_org("acme", "Acme")
        await store.create_org("victim", "Victim")
        await store.bind_member(derive_principal_id("iss", "alice"), "acme", "developer")
        # victim owns a private tool
        await store.set_tool_ownership("victim_secret", owner_org="victim", visibility="private")

        ev = PolicyEvaluator(store=store, cache=DecisionCache(ttl_sec=0.0))
        alice = await store.resolve_principal("iss", "alice", active_org="victim")
        res = await ev.evaluate(alice, "tool:call", "victim_secret")
        assert res.allowed is False
        assert res.decision == "DENY_TENANT_BOUNDARY"

    asyncio.run(_run())


# --------------------------------------------------------------------------
# C2 — deny-override: any matching deny beats any allow, regardless of order.
# --------------------------------------------------------------------------

def _member_principal(org="acme"):
    return Principal(
        principal_id="pid",
        issuer="iss",
        subject="bob",
        org_id=org,
        workspace_id="default",
        roles=["developer"],
        permissions={"tool:list", "tool:call"},
    )


def test_deny_overrides_allow_regardless_of_order():
    async def _run():
        store = MemoryTenancyStore()
        # allow the whole github_ prefix, but deny one specific tool.
        await store.add_tool_grant("org", "acme", "allow", "prefix", "github_")
        await store.add_tool_grant("org", "acme", "deny", "exact", "github_secret")

        ev = PolicyEvaluator(store=store, cache=DecisionCache(ttl_sec=0.0))
        p = _member_principal()

        # The allow grant is stored first; a naive first-match would allow it.
        denied = await ev.evaluate(p, "tool:call", "github_secret")
        assert denied.allowed is False
        assert denied.decision == "DENY_EXPLICIT"

        # A non-denied tool under the same allow still passes.
        allowed = await ev.evaluate(p, "tool:call", "github_list")
        assert allowed.allowed is True
        assert allowed.decision == "ALLOW_GRANT"

    asyncio.run(_run())


def test_unknown_scope_type_does_not_match_everyone():
    async def _run():
        store = MemoryTenancyStore()
        # A role-scoped allow for a role the principal does NOT hold.
        await store.add_tool_grant("role", "org_admin", "allow", "exact", "x")
        ev = PolicyEvaluator(store=store, cache=DecisionCache(ttl_sec=0.0))
        p = _member_principal()  # roles = ['developer'], lacks org_admin

        # Must not be granted via the role-scoped rule; falls through to the
        # role-permission path (ALLOW_ROLE) rather than ALLOW_GRANT.
        res = await ev.evaluate(p, "tool:call", "x")
        assert res.decision != "ALLOW_GRANT"

    asyncio.run(_run())


# --------------------------------------------------------------------------
# H2 — grant match_type vocabulary: name | tag | owner | all (+ legacy aliases).
# --------------------------------------------------------------------------

def test_grant_match_types_name_tag_owner_all():
    async def _run():
        store = MemoryTenancyStore()
        # A tool owned by acme, tagged 'finance', visibility private.
        await store.set_tool_ownership(
            "billing", owner_org="acme", visibility="private", tags=["finance"]
        )
        ev = PolicyEvaluator(store=store, cache=DecisionCache(ttl_sec=0.0))
        p = _member_principal(org="acme")

        # 'tag' match — previously dead code (evaluator only knew exact/prefix/glob).
        await store.add_tool_grant("org", "acme", "allow", "tag", "finance")
        assert (await ev.evaluate(p, "tool:call", "billing")).decision == "ALLOW_GRANT"

        # 'owner' match on a fresh store.
        store2 = MemoryTenancyStore()
        await store2.set_tool_ownership("billing", owner_org="acme", visibility="private")
        await store2.add_tool_grant("org", "acme", "allow", "owner", "acme")
        ev2 = PolicyEvaluator(store=store2, cache=DecisionCache(ttl_sec=0.0))
        assert (await ev2.evaluate(p, "tool:call", "billing")).decision == "ALLOW_GRANT"

        # 'name' with a glob, and 'all'.
        store3 = MemoryTenancyStore()
        await store3.set_tool_ownership("github_x", owner_org="acme", visibility="private")
        await store3.add_tool_grant("org", "acme", "allow", "name", "github_*")
        ev3 = PolicyEvaluator(store=store3, cache=DecisionCache(ttl_sec=0.0))
        assert (await ev3.evaluate(p, "tool:call", "github_x")).decision == "ALLOW_GRANT"

        store4 = MemoryTenancyStore()
        await store4.set_tool_ownership("anything", owner_org="acme", visibility="private")
        await store4.add_tool_grant("org", "acme", "allow", "all", "*")
        ev4 = PolicyEvaluator(store=store4, cache=DecisionCache(ttl_sec=0.0))
        assert (await ev4.evaluate(p, "tool:call", "anything")).decision == "ALLOW_GRANT"

    asyncio.run(_run())


def test_legacy_pattern_aliases_still_work():
    async def _run():
        store = MemoryTenancyStore()
        await store.set_tool_ownership("github_x", owner_org="acme", visibility="private")
        await store.add_tool_grant("org", "acme", "allow", "prefix", "github_*")
        ev = PolicyEvaluator(store=store, cache=DecisionCache(ttl_sec=0.0))
        p = _member_principal(org="acme")
        assert (await ev.evaluate(p, "tool:call", "github_x")).decision == "ALLOW_GRANT"

    asyncio.run(_run())


# --------------------------------------------------------------------------
# H4 — shadow vs enforce mode (§19): shadow evaluates but never blocks.
# --------------------------------------------------------------------------

import types

from plugins.security import enforce
from plugins.rbac.evaluator import EvaluationResult


class _DenyingEvaluator:
    def __init__(self):
        self.cache = DecisionCache(ttl_sec=0.0)

    async def evaluate(self, principal, action, resource, context=None):
        return EvaluationResult(allowed=False, decision="DENY_NO_PERMISSION",
                                reason="test-deny", eval_time_ms=0.0)


def _fake_request(mode, principal):
    state = types.SimpleNamespace(
        auth_type="none", rbac_enabled=True, rbac_mode=mode,
        policy_evaluator=_DenyingEvaluator(), tenancy_store=None,
    )
    req = types.SimpleNamespace(
        app=types.SimpleNamespace(state=state),
        url=types.SimpleNamespace(path="/tools/x/call"),
        path_params={"name": "x"},
        headers={},
        state=types.SimpleNamespace(principal=principal),
    )
    return req


def test_shadow_mode_does_not_block_a_would_deny():
    res = asyncio.run(enforce(_fake_request("shadow", _member_principal()), "mcp"))
    assert res is None  # logged as would-deny, request proceeds


def test_enforce_mode_blocks_a_deny():
    res = asyncio.run(enforce(_fake_request("enforce", _member_principal()), "mcp"))
    assert res is not None and res.status_code == 403


# --------------------------------------------------------------------------
# H5 — decision cache is invalidated on tenancy writes (§18.2/§21.4).
# --------------------------------------------------------------------------

def test_cache_invalidation_helper():
    from plugins.routes import _invalidate_rbac_cache

    cache = DecisionCache(ttl_sec=999)
    cache.put("pidA", "acme", "default", "tool:call", "x", "R")
    cache.put("pidB", "acme", "default", "tool:call", "y", "R")
    req = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(
            policy_evaluator=types.SimpleNamespace(cache=cache)))
    )

    # Principal-scoped invalidation (bind_member) drops only that principal.
    _invalidate_rbac_cache(req, principal_id="pidA")
    assert cache.get("pidA", "acme", "default", "tool:call", "x") is None
    assert cache.get("pidB", "acme", "default", "tool:call", "y") == "R"

    # Full clear (grant change) drops everything.
    _invalidate_rbac_cache(req, full=True)
    assert cache.get("pidB", "acme", "default", "tool:call", "y") is None


# --------------------------------------------------------------------------
# H3 — a bare signed token floors at agent_consumer, not developer.
# H1 — one canonical role->permission matrix (identity == seeder), no drift.
# --------------------------------------------------------------------------

def test_default_role_is_least_privilege():
    from plugins.identity import build_principal_from_claims

    p = build_principal_from_claims(issuer="iss", subject="nobody")  # no roles claim
    assert p.roles == ["agent_consumer"]
    # Must NOT inherit onboarding / management from a bare token (H3, §17.4).
    assert "tool:onboard" not in p.permissions
    assert "tool:manage" not in p.permissions
    assert {"tool:list", "tool:call"} <= p.permissions


def test_permissions_derived_from_matrix_and_unknown_role_denied():
    from plugins.identity import build_principal_from_claims, BUILTIN_ROLE_PERMISSIONS

    p = build_principal_from_claims(issuer="iss", subject="a", roles=["org_admin"])
    assert p.permissions == BUILTIN_ROLE_PERMISSIONS["org_admin"]

    # An unknown role contributes nothing (deny-by-default).
    p2 = build_principal_from_claims(issuer="iss", subject="b", roles=["wizard"])
    assert p2.permissions == set()


def test_seeder_and_identity_share_one_matrix():
    from plugins.identity import BUILTIN_ROLE_PERMISSIONS
    from plugins.tenancy.seeder import BUILTIN_ROLES

    # Seeder rows are exactly the identity matrix (sorted lists) -> no drift (H1).
    assert set(BUILTIN_ROLES) == set(BUILTIN_ROLE_PERMISSIONS)
    for role, perms in BUILTIN_ROLE_PERMISSIONS.items():
        assert set(BUILTIN_ROLES[role]) == perms
