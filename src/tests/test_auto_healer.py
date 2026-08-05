"""Unit tests for the Self-Healing Tool Onboarding Engine.

Run: pytest src/tests/test_auto_healer.py
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


def test_auto_healer_import_and_decorator_fix():
    healer = AutoHealer()
    plain_source = """
# Calculate account balance with docstring
def get_balance(user_id: int) -> dict:
    \"\"\"Calculates account balance for given user.\"\"\"
    return {"user_id": user_id, "balance": 100.0}
"""
    res = healer.heal_source(plain_source, name="get_balance")
    assert res.syntax_ok is True
    assert res.has_autofix is True
    assert "from tools_sdk import tool" in res.corrected_source
    assert '@tool(description="Calculates account balance for given user.")' in res.corrected_source
    assert "# Calculate account balance with docstring" in res.corrected_source  # Preserves comments!


def test_auto_healer_dependency_inference():
    healer = AutoHealer()
    source = """from tools_sdk import tool
import yaml
import PIL

@tool()
def parse_yaml(data: str) -> dict:
    return yaml.safe_load(data)
"""
    res = healer.heal_source(source, name="parse_yaml", requirements=[])
    assert "pyyaml" in res.suggested_requirements
    assert "pillow" in res.suggested_requirements
    assert any("pyyaml" in fix for fix in res.fixes_applied)


def test_auto_healer_missing_colon_fix():
    healer = AutoHealer()
    broken_colon = """def add_func(a: int, b: int)
    return a + b
"""
    res = healer.heal_source(broken_colon, name="add_func")
    assert res.syntax_ok is True
    assert "def add_func(a: int, b: int):" in res.corrected_source


def test_auto_healer_untyped_param_annotation():
    healer = AutoHealer()
    untyped_source = """from tools_sdk import tool

@tool()
def hello(name, count):
    return f"Hello {name} {count}"
"""
    res = healer.heal_source(untyped_source, name="hello")
    assert res.syntax_ok is True
    assert "name: str" in res.corrected_source


def test_auto_heal_onboarding_and_revert_integration(tmp_path):
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

    # 1. Dry-run validate undecorated tool code -> inspect Auto-Fix Proposal
    payload_validate = {
        "name": "auto_tool",
        "source": "def auto_tool(user_id: int) -> dict:\n    \"\"\"Fetches user data.\"\"\"\n    return {'user_id': user_id}"
    }
    resp_val = client.post("/admin/tools/validate_source", json=payload_validate, headers=headers)
    assert resp_val.status_code == 200
    val_data = resp_val.json()
    assert val_data["has_autofix"] is True
    assert "from tools_sdk import tool" in val_data["corrected_source"]
    assert len(val_data["autofix_summary"]) >= 1

    # 2. Onboard broken undecorated tool with auto_heal=true (default)
    payload_onboard = {
        "name": "auto_tool",
        "source": "def auto_tool(user_id: int) -> dict:\n    \"\"\"Fetches user data.\"\"\"\n    return {'user_id': user_id}",
        "auto_heal": True
    }
    resp_onboard = client.post("/admin/tools/onboard", json=payload_onboard, headers=headers)
    assert resp_onboard.status_code == 201
    data_onboard = resp_onboard.json()
    assert data_onboard["auto_healed"] is True
    assert len(data_onboard["fixes_applied"]) >= 1

    # 3. Verify tool is live and callable
    call_payload = {"arguments": {"user_id": 42}}
    resp_call = client.post("/tools/auto_tool/call", json=call_payload, headers=headers)
    assert resp_call.status_code == 200
    assert resp_call.json()["tool"] == "auto_tool"


    # 4. Revert tool back to original undecorated source
    resp_revert = client.post("/admin/tools/auto_tool/revert", headers=headers)
    assert resp_revert.status_code == 200
    assert resp_revert.json()["auto_healed"] is False

