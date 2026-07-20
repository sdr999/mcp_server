"""Tests for the flag-driven, Azure-agnostic tool source (MCP_TOOL_SOURCE).

validate_context should:
- accept auto/local without Azure credentials,
- require credentials only in strict 'azure' mode,
- reject an invalid source value.
"""
from pathlib import Path

import pytest

import multiple_mcp_main as m


def _ctx(env, tool_source="auto", auth_type="none"):
    return m.AppContext(
        base_dir=Path("."), local_tools_dir=Path("./t"), remote_prefix="x", env=env,
        auth_type=auth_type, api_key_header="authorization", api_key_value="",
        jwks_url="", jwt_issuer=None, jwt_audience=None, jwt_required_scopes=None,
        host="0.0.0.0", port=8000, poll_interval=60, import_timeout=30,
        metrics_enabled=True, sandbox=False, sandbox_timeout=30, sandbox_mem_mb=0,
        sandbox_cpu_sec=0, admin_token="", tool_source=tool_source,
        require_signed=False, manifest_name="tools.manifest.json", signing_key=None,
    )


def test_local_mode_needs_no_azure():
    m.validate_context(_ctx({}, tool_source="local"))  # must not raise


def test_auto_mode_needs_no_azure():
    m.validate_context(_ctx({}, tool_source="auto"))   # must not raise


def test_azure_mode_requires_credentials():
    with pytest.raises(RuntimeError, match="MCP_TOOL_SOURCE=azure"):
        m.validate_context(_ctx({}, tool_source="azure"))


def test_azure_mode_with_credentials_ok():
    env = {"AZURE_FILESTORE_CONNECTION_URL": "x", "AZURE_FILESTORE_NAME": "y"}
    m.validate_context(_ctx(env, tool_source="azure"))  # must not raise


def test_invalid_source_rejected():
    with pytest.raises(RuntimeError, match="MCP_TOOL_SOURCE must be"):
        m.validate_context(_ctx({}, tool_source="cloud"))
