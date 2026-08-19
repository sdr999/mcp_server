"""Automated test suite verifying seamless auth with MCP_ADMIN_TOKEN, ApiKeyAuth, and Bearer JWT tokens across all endpoints."""
import pytest
from starlette.testclient import TestClient

from plugins.app import build_app
from plugins.config import AppContext, build_context


def create_test_client(auth_type: str = "none", admin_token: str = "admin-secret-123", api_key_value: str = "api-key-456"):
    ctx = build_context(argv=[])
    ctx.auth_type = auth_type
    ctx.admin_token = admin_token
    ctx.api_key_value = api_key_value
    ctx.api_key_header = "authorization"
    app, _ = build_app(ctx)
    return TestClient(app)


def test_admin_token_on_status_and_tools_in_bearer_jwt_mode():
    client = create_test_client(auth_type="bearer_jwt", admin_token="admin-secret-123")

    # 1. Bearer header with admin token
    res = client.get("/status", headers={"Authorization": "Bearer admin-secret-123"})
    assert res.status_code == 200
    assert res.json()["ready"] is False or res.json()["ready"] is True

    # 2. X-Admin-Token header
    res = client.get("/tools", headers={"X-Admin-Token": "admin-secret-123"})
    assert res.status_code == 200
    assert "tools" in res.json()

    # 3. Query parameter ?token=
    res = client.get("/metrics?token=admin-secret-123")
    assert res.status_code == 200

    # 4. /whoami returns platform_superadmin principal
    res = client.get("/whoami", headers={"X-Admin-Token": "admin-secret-123"})
    assert res.status_code == 200
    data = res.json()
    assert data["subject"] == "admin-token"
    assert "platform_superadmin" in data["roles"]


def test_admin_token_on_status_and_tools_in_api_key_mode():
    client = create_test_client(auth_type="api_key", admin_token="admin-secret-123", api_key_value="api-key-456")

    # 1. API key value works
    res = client.get("/status", headers={"Authorization": "api-key-456"})
    assert res.status_code == 200

    # 2. Admin token works on /tools in api_key mode
    res = client.get("/tools", headers={"Authorization": "Bearer admin-secret-123"})
    assert res.status_code == 200

    # 3. X-Admin-Token works on /tools in api_key mode
    res = client.get("/tools", headers={"X-Admin-Token": "admin-secret-123"})
    assert res.status_code == 200

    # 4. Invalid key gets 401
    res = client.get("/tools", headers={"Authorization": "invalid-key"})
    assert res.status_code == 401


def test_admin_token_on_admin_endpoints():
    client = create_test_client(auth_type="bearer_jwt", admin_token="admin-secret-123")

    # Admin route via Authorization Bearer
    res = client.get("/admin/logs", headers={"Authorization": "Bearer admin-secret-123"})
    assert res.status_code == 200
    assert "logs" in res.json()

    # Admin route via X-Admin-Token
    res = client.get("/admin/logs", headers={"X-Admin-Token": "admin-secret-123"})
    assert res.status_code == 200

    # Admin route via ?token=
    res = client.get("/admin/logs?token=admin-secret-123")
    assert res.status_code == 200


def test_openapi_spec_contains_updated_security_schemes():
    client = create_test_client(auth_type="none")
    res = client.get("/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert "ApiKeyAuth" in schemes
    assert "BearerAuth" in schemes
    assert "AdminTokenAuth" in schemes
    assert "XAdminTokenAuth" in schemes
