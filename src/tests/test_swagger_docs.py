"""Unit tests for Swagger UI and OpenAPI specification endpoints.

Run: pytest src/tests/test_swagger_docs.py
"""
import sys
from pathlib import Path

# Ensure src directory is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from starlette.testclient import TestClient
from plugins.config import build_context
from plugins.app import build_app


def test_swagger_ui_and_openapi_endpoints(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    ctx = build_context([], base_dir=SRC_DIR)
    ctx.tools_dir = tools_dir
    app, _mcp = build_app(ctx)
    client = TestClient(app)


    # Test /docs HTML page
    resp_docs = client.get("/docs")
    assert resp_docs.status_code == 200
    assert "Swagger UI" in resp_docs.text
    assert "swagger-ui-bundle.js" in resp_docs.text

    # Test /swagger HTML page alias
    resp_swagger = client.get("/swagger")
    assert resp_swagger.status_code == 200
    assert "Swagger UI" in resp_swagger.text

    # Test /openapi.json endpoint (now FastAPI-generated: OpenAPI 3.1.x)
    resp_json = client.get("/openapi.json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert str(data.get("openapi", "")).startswith("3.")
    assert "paths" in data
    assert "/healthz" in data["paths"]
    assert "/tools" in data["paths"]
    assert "/tools/{name}/call" in data["paths"]
    assert "/admin/tools/onboard" in data["paths"]

    # Test /openapi.yaml endpoint (serialized from the FastAPI-generated schema)
    resp_yaml = client.get("/openapi.yaml")
    assert resp_yaml.status_code == 200
    assert "openapi:" in resp_yaml.text


def test_validate_source_endpoint(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    ctx = build_context([], base_dir=SRC_DIR)
    ctx.tools_dir = tools_dir
    ctx.admin_token = "admintoken"
    app, _mcp = build_app(ctx)
    client = TestClient(app)

    headers = {"Authorization": "Bearer admintoken"}
    payload = {
        "source": "from tools_sdk import tool\n\n@tool()\ndef ping() -> str:\n    return 'pong'\n"
    }
    resp = client.post("/admin/tools/validate_source", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["syntax_ok"] is True
    assert "ping" in data["tools_found"]


def test_onboard_calls_validation_internally(tmp_path):
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

    # 1. Test onboarding with a syntax error
    payload_syntax_err = {
        "name": "bad_syntax",
        "source": "def broken_func(\n    return 123"
    }
    resp = client.post("/admin/tools/onboard", json=payload_syntax_err, headers=headers)
    assert resp.status_code == 400
    assert "validation failed" in resp.json()["error"]

    # 2. Test successful onboarding attaching hints
    payload_good = {
        "name": "good_tool",
        "source": "from tools_sdk import tool\n\n@tool()\ndef good_tool() -> str:\n    return 'ok'"
    }
    resp_good = client.post("/admin/tools/onboard", json=payload_good, headers=headers)
    assert resp_good.status_code == 201
    assert "hints" in resp_good.json()

    # 3. Test missing tools_sdk import hint
    payload_missing_import = {
        "name": "missing_imp",
        "source": "@tool()\ndef missing_imp() -> str:\n    return 'no import'"
    }
    resp_miss = client.post("/admin/tools/validate_source", json=payload_missing_import, headers=headers)
    assert resp_miss.status_code == 200
    summaries_and_hints = resp_miss.json().get("autofix_summary", []) + resp_miss.json().get("hints", [])
    assert any("from tools_sdk import tool" in msg for msg in summaries_and_hints)
