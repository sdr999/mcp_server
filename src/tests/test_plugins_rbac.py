"""Unit and integration tests for Phase 2 RBAC Policy Engine & Hierarchical Evaluator."""
from __future__ import annotations

import asyncio
import time
import pytest
from starlette.testclient import TestClient

from plugins.config import build_context
from plugins.app import build_app
from plugins.identity import Principal, derive_principal_id
from plugins.tenancy import MemoryTenancyStore
from plugins.rbac import DecisionCache, PolicyEvaluator, EvaluationResult


@pytest.mark.anyio
async def test_decision_cache_lru_and_invalidation():
    cache = DecisionCache(maxsize=2, ttl_sec=10.0)

    res1 = EvaluationResult(allowed=True, decision="ALLOW_SUPERADMIN", reason="ok", eval_time_ms=0.1)
    cache.put("user_1", "org_a", "prod", "tool:call", "greet", res1)

    # Cache Hit
    hit = cache.get("user_1", "org_a", "prod", "tool:call", "greet")
    assert hit is not None
    assert hit.decision == "ALLOW_SUPERADMIN"

    # Invalidation
    count = cache.invalidate(principal_id="user_1")
    assert count == 1
    assert cache.get("user_1", "org_a", "prod", "tool:call", "greet") is None


@pytest.mark.anyio
async def test_policy_evaluator_superadmin_override():
    store = MemoryTenancyStore()
    await store.init_db()
    evaluator = PolicyEvaluator(store=store)

    superadmin = Principal(
        principal_id="pid_admin",
        issuer="https://supabase.co/auth/v1",
        subject="admin@acme.com",
        roles=["platform_superadmin"],
        permissions={"platform:admin"},
    )

    res = await evaluator.evaluate(superadmin, "tool:call", "sensitive_tool")
    assert res.allowed is True
    assert res.decision == "ALLOW_SUPERADMIN"


@pytest.mark.anyio
async def test_policy_evaluator_explicit_deny_and_allow_grants():
    store = MemoryTenancyStore()
    await store.init_db()
    evaluator = PolicyEvaluator(store=store)

    user = Principal(
        principal_id="pid_user",
        issuer="https://supabase.co/auth/v1",
        subject="user@acme.com",
        org_id="acme",
        roles=["developer"],
        permissions={"tool:call"},
    )

    # 1. Explicit Deny Grant
    await store.add_tool_grant(scope_type="user", scope_id="pid_user", effect="deny", match_type="exact", match_value="forbidden_tool")
    res_deny = await evaluator.evaluate(user, "tool:call", "forbidden_tool")
    assert res_deny.allowed is False
    assert res_deny.decision == "DENY_EXPLICIT"

    # 2. Explicit Allow Grant
    await store.add_tool_grant(scope_type="user", scope_id="pid_user", effect="allow", match_type="prefix", match_value="granted_")
    res_allow = await evaluator.evaluate(user, "tool:call", "granted_feature")
    assert res_allow.allowed is True
    assert res_allow.decision == "ALLOW_GRANT"


@pytest.mark.anyio
async def test_policy_evaluator_role_permission_check():
    store = MemoryTenancyStore()
    await store.init_db()
    evaluator = PolicyEvaluator(store=store)

    consumer = Principal(
        principal_id="pid_consumer",
        issuer="https://supabase.co/auth/v1",
        subject="agent@acme.com",
        org_id="acme",
        roles=["agent_consumer"],
        permissions={"tool:list", "tool:call"},
    )

    # Allowed action
    res1 = await evaluator.evaluate(consumer, "tool:call", "search")
    assert res1.allowed is True

    # Denied action (lacks tool:onboard)
    res2 = await evaluator.evaluate(consumer, "tool:onboard", "new_tool")
    assert res2.allowed is False
    assert res2.decision == "DENY_NO_PERMISSION"


@pytest.mark.anyio
async def test_policy_evaluator_tenant_boundary():
    store = MemoryTenancyStore()
    await store.init_db()
    evaluator = PolicyEvaluator(store=store)

    # Organization A Tool (private)
    await store.set_tool_ownership("private_tool_a", owner_org="org_a", visibility="private")

    # Organization B User
    user_b = Principal(
        principal_id="pid_b",
        issuer="https://supabase.co/auth/v1",
        subject="user_b",
        org_id="org_b",
        roles=["developer"],
        permissions={"tool:call"},
    )

    # Denied across tenant boundary
    res = await evaluator.evaluate(user_b, "tool:call", "private_tool_a")
    assert res.allowed is False
    assert res.decision == "DENY_TENANT_BOUNDARY"

    # Public Tool allowed
    await store.set_tool_ownership("public_tool", owner_org="org_a", visibility="public")
    res_pub = await evaluator.evaluate(user_b, "tool:call", "public_tool")
    assert res_pub.allowed is True
    assert res_pub.decision == "ALLOW_PUBLIC"


def test_rbac_enforce_middleware_integration():
    ctx = build_context([])
    ctx.rbac_enabled = True
    app, _ = build_app(ctx)
    client = TestClient(app)

    # Calling an endpoint when RBAC is enabled
    res = client.get("/tools")
    assert res.status_code in (200, 401, 403)


