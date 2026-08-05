"""Advanced Unit Tests for Next-Level Self-Healing Engine Enhancements.

Run: pytest src/tests/test_advanced_auto_healer.py
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
from plugins.auto_healer import AutoHealer


def test_unbound_symbol_auto_imports():
    healer = AutoHealer()
    code = """
def process_data(items: List[str]) -> Path:
    data = json.loads('{"a": 1}')
    return Path("/tmp/out")
"""
    res = healer.heal_source(code, name="process_data")
    assert res.syntax_ok is True
    assert "from pathlib import Path" in res.corrected_source
    assert "from typing import List" in res.corrected_source
    assert "import json" in res.corrected_source
    assert any("Path" in fix for fix in res.fixes_applied)


def test_input_type_coercion_in_tool_loader(tmp_path):
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

    # Onboard tool typed with int, bool, float
    payload = {
        "name": "typed_calc",
        "source": """from tools_sdk import tool

@tool()
def typed_calc(user_id: int, active: bool, score: float) -> dict:
    return {"user_id": user_id, "user_type": type(user_id).__name__, "active": active, "score": score}
"""
    }
    resp = client.post("/admin/tools/onboard", json=payload, headers=headers)
    assert resp.status_code == 201

    # Call with stringified arguments: "42", "true", "98.5"
    call_payload = {
        "arguments": {
            "user_id": "42",
            "active": "true",
            "score": "98.5"
        }
    }
    resp_call = client.post("/tools/typed_calc/call", json=call_payload, headers=headers)
    assert resp_call.status_code == 200
    res = resp_call.json()
    assert res["tool"] == "typed_calc"


def test_one_click_accept_proposal_and_auto_patch_endpoints(tmp_path):
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

    # 1. Accept Proposal Endpoint
    payload = {
        "name": "proposal_tool",
        "source": "def proposal_tool(user_id: int) -> dict:\n    \"\"\"Fetches user data.\"\"\"\n    return {'user_id': user_id}"
    }
    resp_acc = client.post("/admin/tools/onboard/accept_proposal", json=payload, headers=headers)
    assert resp_acc.status_code == 201
    assert resp_acc.json()["auto_healed"] is True

    # 2. Auto-patch Endpoint
    resp_patch = client.post("/admin/tools/proposal_tool/auto_patch", headers=headers)
    assert resp_patch.status_code == 200
