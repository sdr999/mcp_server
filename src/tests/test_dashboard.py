"""Unit tests for live admin dashboard routes, KV JSON endpoint, and SSE connection cap."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.plugins.app import build_app
from src.plugins.config import AppContext


@pytest.fixture
def test_ctx(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    return AppContext(
        base_dir=tmp_path,
        tools_dir=tools,
        env={},
        auth_type="none",
        api_key_header="X-API-Key",
        api_key_value="secret",
        jwks_url="",
        jwt_issuer=None,
        jwt_audience=None,
        jwt_required_scopes=None,
        host="127.0.0.1",
        port=8000,
        import_timeout=5.0,
        metrics_enabled=True,
        sandbox=False,
        sandbox_timeout=5.0,
        sandbox_mem_mb=0,
        sandbox_cpu_sec=0,
        admin_token="myadmintoken",
        require_signed=False,
        manifest_name="manifest.json",
        signing_key=None,
    )


def test_dashboard_html_auth(test_ctx):
    app, _ = build_app(test_ctx)
    client = TestClient(app)

    # 1. Without token -> 401
    resp1 = client.get("/admin/dashboard")
    assert resp1.status_code == 401

    # 2. With Bearer token -> 200
    resp2 = client.get("/admin/dashboard", headers={"Authorization": "Bearer myadmintoken"})
    assert resp2.status_code == 200
    assert "Live Reliability & Telemetry Dashboard" in resp2.text


def test_dashboard_json_kv_endpoint(test_ctx):
    app, _ = build_app(test_ctx)
    client = TestClient(app)

    # 1. GET /admin/dashboard/json with token -> returns clean key-value summary
    resp = client.get("/admin/dashboard/json", headers={"Authorization": "Bearer myadmintoken"})
    assert resp.status_code == 200
    data = resp.json()
    assert "server_status" in data
    assert "total_tools" in data
    assert "active_sse_clients" in data
    assert "rate_limit_default_rpm" in data

    # 2. GET /admin/dashboard?format=json with token -> returns same key-value JSON
    resp_fmt = client.get("/admin/dashboard?format=json", headers={"Authorization": "Bearer myadmintoken"})
    assert resp_fmt.status_code == 200
    assert resp_fmt.json()["total_tools"] == data["total_tools"]
