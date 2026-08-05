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
