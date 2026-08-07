"""Unit tests for Token, Cost & Tenant Budget Engine."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.plugins.app import build_app
from src.plugins.config import AppContext
from src.plugins.cost import CostTracker


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


def test_cost_tracker_calculation():
    tracker = CostTracker()
    cost1 = tracker.record_usage(tenant_id="tenant-a", prompt_tokens=1000, completion_tokens=1000, model="gpt-4o")
    assert cost1 == 0.0125  # (1 * 0.0025) + (1 * 0.01)

    spend_a = tracker.get_tenant_spend("tenant-a")
    assert spend_a == 0.0125

    stats = tracker.get_stats()
    assert stats["total_spend_usd"] == 0.0125
    assert stats["total_tokens"] == 2000


def test_budget_middleware_enforcement(test_ctx):
    app, _ = build_app(test_ctx)
    client = TestClient(app)

    # 1. Normal request passes and returns budget headers
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert "X-Cost-USD" in resp.headers
    assert "X-Budget-Remaining" in resp.headers

    # 2. Record excessive spend exceeding budget limit ($100)
    tracker = app.state.cost_tracker
    tracker.record_usage(tenant_id="default", prompt_tokens=100_000_000, completion_tokens=100_000_000, model="gpt-4o")

    # 3. Next request rejected with 429 Budget Exceeded
    resp2 = client.get("/healthz")
    assert resp2.status_code == 429
    assert resp2.json()["error"] == "Budget Exceeded"
