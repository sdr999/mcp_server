"""Unit tests for Secured Upstream MCP Servers (API Key, Bearer Token, Custom Headers, Secret Masking).

Run: pytest src/tests/test_upstreams_poc_security.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Ensure src directory is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from starlette.testclient import TestClient
from plugins.config import build_context
from plugins.app import build_app
from plugins.upstreams import UpstreamRegistry, mask_secret


def test_mask_secret_utility():
    assert mask_secret(None) is None
    assert mask_secret("") is None
    assert mask_secret("short") == "***"
    assert mask_secret("secret_api_key_12345") == "secr***"


def test_upstream_registry_security_and_redaction(tmp_path):
    storage_file = tmp_path / "upstreams.json"
    registry = UpstreamRegistry(storage_file=storage_file)

    # 1. Add API Key secured upstream
    registry.add(
        "poc_api_key_server",
        "http://localhost:9001",
        api_key="secret_key_9999",
        header_name="X-API-Key"
    )

    # 2. Add Bearer Token secured upstream
    registry.add(
        "poc_bearer_server",
        "http://localhost:9002",
        token="jwt_bearer_token_abc123"
    )

    # 3. Add Custom Headers upstream
    registry.add(
        "poc_tenant_server",
        "http://localhost:9003",
        headers={"X-Tenant-ID": "acme_corp"}
    )

    # 4. Verify Secret Redaction on list()
    servers = registry.list()
    assert len(servers) == 3

    api_key_item = next(s for s in servers if s["name"] == "poc_api_key_server")
    assert api_key_item["api_key"] == "secr***"
    assert api_key_item["header_name"] == "X-API-Key"

    bearer_item = next(s for s in servers if s["name"] == "poc_bearer_server")
    assert bearer_item["token"] == "jwt_***"

    # 5. Verify Persistent Storage to upstreams.json
    assert storage_file.exists()
    disk_data = json.loads(storage_file.read_text(encoding="utf-8"))
    assert "poc_api_key_server" in disk_data
    assert disk_data["poc_api_key_server"]["api_key"] == "secret_key_9999"

    # 6. Verify Re-hydration from disk
    new_registry = UpstreamRegistry(storage_file=storage_file)
    rehydrated = new_registry.list()
    assert len(rehydrated) == 3


def test_admin_upstream_api_integration(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    pkg_parent = str(tmp_path.resolve())
    sys.modules.pop("tools", None)
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)

    ctx = build_context([], base_dir=tmp_path)
    ctx.tools_dir = tools_dir
    ctx.admin_token = "admintoken"
    app, _mcp = build_app(ctx)
    client = TestClient(app)

    headers = {"Authorization": "Bearer admintoken"}

    # Add upstream via Admin API
    payload = {
        "name": "poc_remote_server",
        "url": "http://localhost:9005",
        "api_key": "admin_api_key_12345",
        "header_name": "X-Custom-Key",
        "headers": {"X-Tenant": "tenant_a"}
    }
    resp_add = client.post("/admin/mcp/upstreams", json=payload, headers=headers)
    assert resp_add.status_code == 201
    assert resp_add.json()["status"] == "added"

    # List upstreams and check redaction
    resp_list = client.get("/mcp/upstreams", headers=headers)
    assert resp_list.status_code == 200
    upstreams = resp_list.json()["upstreams"]
    matched = next(u for u in upstreams if u["name"] == "poc_remote_server")
    assert matched["api_key"] == "admi***"

    # Remove upstream via Admin API
    resp_rem = client.post("/admin/mcp/upstreams/poc_remote_server/remove", headers=headers)
    assert resp_rem.status_code == 200
    assert resp_rem.json()["status"] == "removed"
