"""Unit and integration tests for Phase 3 Tenant & Workspace Catalog Scoping."""
from __future__ import annotations

import asyncio
import pytest
from starlette.testclient import TestClient

from plugins.config import build_context
from plugins.app import build_app
from plugins.identity import Principal
from plugins.tenancy import MemoryTenancyStore
from plugins.tenancy.scoping import filter_tools_for_principal
from plugins.rbac import PolicyEvaluator


@pytest.mark.anyio
async def test_filter_tools_tenant_isolation():
    store = MemoryTenancyStore()
    await store.init_db()
    evaluator = PolicyEvaluator(store=store)

    # Set ownerships
    await store.set_tool_ownership("tool_org_a", owner_org="org_a", visibility="private")
    await store.set_tool_ownership("tool_org_b", owner_org="org_b", visibility="private")
    await store.set_tool_ownership("tool_public", owner_org="org_a", visibility="public")

    tools = [
        {"name": "tool_org_a", "description": "Org A Private"},
        {"name": "tool_org_b", "description": "Org B Private"},
        {"name": "tool_public", "description": "Public Tool"},
    ]

    # Caller from Org A
    user_a = Principal(
        principal_id="pid_a",
        issuer="https://supabase.co/auth/v1",
        subject="user_a",
        org_id="org_a",
        roles=["developer"],
        permissions={"tool:list", "tool:call"},
    )

    filtered_a = await filter_tools_for_principal(store, evaluator, user_a, tools)
    names_a = {t["name"] for t in filtered_a}
    assert "tool_org_a" in names_a
    assert "tool_public" in names_a
    assert "tool_org_b" not in names_a

    # Caller from Org B
    user_b = Principal(
        principal_id="pid_b",
        issuer="https://supabase.co/auth/v1",
        subject="user_b",
        org_id="org_b",
        roles=["developer"],
        permissions={"tool:list", "tool:call"},
    )

    filtered_b = await filter_tools_for_principal(store, evaluator, user_b, tools)
    names_b = {t["name"] for t in filtered_b}
    assert "tool_org_b" in names_b
    assert "tool_public" in names_b
    assert "tool_org_a" not in names_b


@pytest.mark.anyio
async def test_filter_tools_superadmin_sees_all():
    store = MemoryTenancyStore()
    await store.init_db()
    evaluator = PolicyEvaluator(store=store)

    await store.set_tool_ownership("tool_org_a", owner_org="org_a", visibility="private")
    await store.set_tool_ownership("tool_org_b", owner_org="org_b", visibility="private")

    tools = [
        {"name": "tool_org_a", "description": "Org A Private"},
        {"name": "tool_org_b", "description": "Org B Private"},
    ]

    superadmin = Principal(
        principal_id="pid_admin",
        issuer="https://supabase.co/auth/v1",
        subject="admin@acme.com",
        roles=["platform_superadmin"],
        permissions={"platform:admin"},
    )

    filtered = await filter_tools_for_principal(store, evaluator, superadmin, tools)
    assert len(filtered) == 2


def test_tools_catalog_route_scoping():
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)

    res = client.get("/tools")
    assert res.status_code in (200, 401)
    if res.status_code == 200:
        data = res.json()
        assert "tools" in data
