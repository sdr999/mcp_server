"""Full middleware chain integration test (M5 fix).

Verifies ApiKeyMiddleware -> IdentityMiddleware -> TraceCorrelationMiddleware -> ReliabilityMiddleware -> route handler.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.plugins.app import build_app
from src.plugins.config import AppContext


@pytest.fixture
def integration_app(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "sample_tool.py").write_text("def ping(): return 'pong'\n")
    ctx = AppContext(
        base_dir=tmp_path,
        tools_dir=tools,
        env={"MCP_RATE_LIMIT_DEFAULT_RPM": "2"},
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
        admin_token="adminpass",
        require_signed=False,
        manifest_name="manifest.json",
        signing_key=None,
        rate_limit_enabled=True,
        rate_limit_default_rpm=2,
    )
    app, _ = build_app(ctx)
    return app


def test_full_middleware_chain_rate_limiting_and_exempt_paths(integration_app):
    client = TestClient(integration_app)

    # 1. Healthcheck is exempt from rate limiting
    for _ in range(5):
        resp = client.get("/healthz")
        assert resp.status_code == 200

    # 2. Regular route returns X-RateLimit-Remaining header
    resp1 = client.get("/tools")
    assert resp1.status_code == 200
    assert "X-RateLimit-Remaining" in resp1.headers
    assert resp1.headers["X-RateLimit-Remaining"] == "1"

    resp2 = client.get("/tools")
    assert resp2.status_code == 200
    assert resp2.headers["X-RateLimit-Remaining"] == "0"

    # 3. Third request crosses limit -> 429 Too Many Requests with Retry-After header
    resp3 = client.get("/tools")
    assert resp3.status_code == 429
    assert resp3.json()["error"] == "Too Many Requests"
    assert "Retry-After" in resp3.headers
