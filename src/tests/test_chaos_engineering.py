"""Unit tests for Chaos Engineering & Fault Injection Engine."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.plugins.app import build_app
from src.plugins.config import AppContext
from src.plugins.chaos import ChaosEngine


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


def test_chaos_engine_safety_gate():
    # Without allow_chaos=True, enable() should fail
    engine = ChaosEngine(allow_chaos_env=False)
    assert not engine.enable()
    assert not engine.is_enabled

    # With allow_chaos=True, enable() succeeds
    engine_allowed = ChaosEngine(allow_chaos_env=True)
    assert engine_allowed.enable()
    assert engine_allowed.is_enabled


def test_chaos_admin_routes(test_ctx):
    app, _ = build_app(test_ctx)
    client = TestClient(app)
    headers = {"Authorization": "Bearer myadmintoken"}

    # 1. Check chaos status
    resp = client.get("/admin/chaos", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # 2. Try enabling (blocked by env safety gate)
    resp_enable = client.post("/admin/chaos/enable", headers=headers)
    assert resp_enable.status_code == 403

    # 3. Configure rules
    resp_rules = client.post("/admin/chaos/rules", json={"delay_ms": 50, "exception_rate": 0.5, "http_status": 503}, headers=headers)
    assert resp_rules.status_code == 200
    stats = resp_rules.json()["stats"]
    assert stats["delay_ms"] == 50.0
    assert stats["exception_rate"] == 0.5
    assert stats["http_status"] == 503
