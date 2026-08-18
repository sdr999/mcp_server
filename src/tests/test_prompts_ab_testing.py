"""Unit tests for Prompt Management & Deterministic A/B Testing."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.plugins.app import build_app
from src.plugins.config import AppContext
from src.plugins.prompts import PromptRepository, ABTestManager


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


def test_prompt_hydration():
    repo = PromptRepository()
    template = "Hello {{name}}, welcome to {{service}}!"
    hydrated = repo.hydrate(template, {"name": "Alice", "service": "MCP Tool Gateway"})
    assert hydrated == "Hello Alice, welcome to MCP Tool Gateway!"


def test_ab_testing_deterministic_sticky_selection():
    ab = ABTestManager()
    variants = {"variant_a": "A template", "variant_b": "B template"}

    # Selecting for same tenant multiple times returns the EXACT SAME variant
    var1_key, _ = ab.select_variant("tenant-123", "prompt-tool", variants)
    var2_key, _ = ab.select_variant("tenant-123", "prompt-tool", variants)
    assert var1_key == var2_key


def test_prompt_routes(test_ctx):
    app, _ = build_app(test_ctx)
    client = TestClient(app)
    headers = {"Authorization": "Bearer myadmintoken"}

    # 1. Register a new prompt template
    resp = client.post(
        "/admin/prompts",
        json={
            "name": "greeting",
            "template": "Hello {{name}}",
            "version": "v1.0.0",
            "variants": {"v1": "Hello {{name}}", "v2": "Hi {{name}}!"},
        },
        headers=headers,
    )
    assert resp.status_code == 200

    # 2. Get prompt variant with variable hydration
    resp_var = client.get('/admin/prompts/greeting/variant?vars={"name":"Bob"}', headers=headers)
    assert resp_var.status_code == 200
    data = resp_var.json()
    assert "hydrated_text" in data
    assert "Bob" in data["hydrated_text"]
