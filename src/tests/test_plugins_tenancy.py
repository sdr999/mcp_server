"""Unit and integration tests for Phase 1 Pluggable Tenancy Store, Seeder, and Admin REST API."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from plugins.config import build_context
from plugins.app import build_app
from plugins.tenancy import MemoryTenancyStore, JsonTenancyStore, SqliteTenancyStore
from plugins.tenancy.seeder import seed_tenancy_store_if_empty
from plugins.identity import derive_principal_id


@pytest.mark.anyio
async def test_memory_tenancy_store_contract():
    store = MemoryTenancyStore()
    await store.init_db()

    # Create Org & Workspace
    org = await store.create_org("acme", "ACME Corp")
    assert org.org_id == "acme"
    ws = await store.create_workspace("prod", "acme", "Production")
    assert ws.workspace_id == "prod"

    # Save Role & Bind Member
    await store.save_role("org_admin", ["tool:list", "tool:call", "org:admin"])
    pid = derive_principal_id("https://supabase.co/auth/v1", "user_admin_1")
    mem = await store.bind_member(pid, "acme", "org_admin", "prod")
    assert mem.principal_id == pid

    # Resolve Principal
    principal = await store.resolve_principal("https://supabase.co/auth/v1", "user_admin_1", active_org="acme", active_ws="prod")
    assert principal is not None
    assert principal.org_id == "acme"
    assert principal.workspace_id == "prod"
    assert "org_admin" in principal.roles
    assert "org:admin" in principal.permissions


@pytest.mark.anyio
async def test_sqlite_tenancy_store_contract():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tenancy.db"
        store = SqliteTenancyStore(db_path)
        await store.init_db()

        # Create Org & Workspace
        org = await store.create_org("stark", "Stark Industries")
        assert org.org_id == "stark"
        ws = await store.create_workspace("lab", "stark", "Lab Workspace")
        assert ws.workspace_id == "lab"

        # List Orgs
        orgs = await store.list_orgs()
        assert len(orgs) == 1
        assert orgs[0].name == "Stark Industries"

        # Member Binding
        pid = derive_principal_id("https://supabase.co/auth/v1", "tony_stark")
        await store.bind_member(pid, "stark", "platform_superadmin", "lab")
        mems = await store.list_org_members("stark")
        assert len(mems) == 1
        assert mems[0].principal_id == pid


@pytest.mark.anyio
async def test_json_tenancy_store_contract():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "tenancy.json"
        store = JsonTenancyStore(json_path)
        await store.init_db()

        org = await store.create_org("wayne", "Wayne Enterprises")
        assert org.org_id == "wayne"
        assert json_path.exists()

        # Re-open and verify persistence
        store2 = JsonTenancyStore(json_path)
        await store2.init_db()
        org2 = await store2.get_org("wayne")
        assert org2 is not None
        assert org2.name == "Wayne Enterprises"


@pytest.mark.anyio
async def test_mongo_tenancy_store_imports():
    from plugins.tenancy import MongoTenancyStore
    from plugins.tenancy.mongo_store import HAS_MOTOR
    assert MongoTenancyStore is not None
    if not HAS_MOTOR:
        with pytest.raises(RuntimeError, match="motor package is required"):
            MongoTenancyStore("mongodb://localhost:27017")



@pytest.mark.anyio
async def test_tenancy_seeder_idempotency():
    store = MemoryTenancyStore()
    await store.init_db()

    ctx = build_context([])
    await seed_tenancy_store_if_empty(store, ctx)
    await seed_tenancy_store_if_empty(store, ctx)  # Idempotent re-run

    org = await store.get_org("default")
    assert org is not None
    assert org.name == "Default Organization"

    roles = await store.list_roles()
    assert len(roles) >= 4
    role_names = {r.role for r in roles}
    assert "platform_superadmin" in role_names
    assert "org_admin" in role_names


def test_admin_tenancy_rest_api_crud():
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)
    headers = {"Authorization": "Bearer mysecretadmin"}

    # 1. Create Organization
    res = client.post("/admin/orgs", json={"org_id": "cyberdyne", "name": "Cyberdyne Systems"}, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["org_id"] == "cyberdyne"

    # 2. List Organizations
    res = client.get("/admin/orgs", headers=headers)
    assert res.status_code == 200
    orgs = res.json()
    assert any(o["org_id"] == "cyberdyne" for o in orgs)

    # 3. Create Workspace
    res = client.post("/admin/orgs/cyberdyne/workspaces", json={"workspace_id": "skynet", "name": "Skynet Defense"}, headers=headers)
    assert res.status_code == 201
    assert res.json()["workspace_id"] == "skynet"

    # 4. List Workspaces
    res = client.get("/admin/orgs/cyberdyne/workspaces", headers=headers)
    assert res.status_code == 200
    wss = res.json()
    assert len(wss) == 1
    assert wss[0]["name"] == "Skynet Defense"

    # 5. Bind Member
    res = client.post("/admin/orgs/cyberdyne/members", json={"principal_id": "pid_miles_dyson", "role": "org_admin", "workspace_id": "skynet"}, headers=headers)
    assert res.status_code == 201
    assert res.json()["role"] == "org_admin"

    # 6. List Members
    res = client.get("/admin/orgs/cyberdyne/members", headers=headers)
    assert res.status_code == 200
    mems = res.json()
    assert len(mems) == 1
    assert mems[0]["principal_id"] == "pid_miles_dyson"
