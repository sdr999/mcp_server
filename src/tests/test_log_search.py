"""Unit tests for Lightweight Log Search Index."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.plugins.app import build_app
from src.plugins.config import AppContext
from src.plugins.intelligence import LogSearchIndex


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


def test_log_search_indexing_and_masking():
    index = LogSearchIndex(max_capacity=10)
    index.add_execution_log(
        tool_name="database_query",
        status="error",
        duration_sec=0.15,
        input_payload={"query": "SELECT * FROM users WHERE token = 'Bearer secret_bearer_token_123'"},
        output_payload=None,
        error_msg="ConnectionTimeoutError: Database pool exhausted",
        tenant_id="tenant-prod",
    )

    # 1. Search for keyword "database"
    results = index.search("database")
    assert len(results) == 1
    assert results[0]["tool_name"] == "database_query"

    # 2. Verify secret tokens were masked in index payload
    assert "secret_bearer_token_123" not in results[0]["input"]
    assert "[REDACTED]" in results[0]["input"]



def test_log_search_route(test_ctx):
    app, _ = build_app(test_ctx)
    client = TestClient(app)

    # Seed an execution log entry
    app.state.log_search_index.add_execution_log(
        tool_name="weather_tool",
        status="success",
        duration_sec=0.05,
        input_payload={"location": "Tokyo"},
        output_payload={"temp": "22C"},
    )

    resp = client.get("/admin/intelligence/search?q=Tokyo", headers={"Authorization": "Bearer myadmintoken"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results_count"] == 1
    assert data["results"][0]["tool_name"] == "weather_tool"
