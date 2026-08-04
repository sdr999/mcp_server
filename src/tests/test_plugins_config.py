"""Tests for plugins.config: env precedence and safe --config path resolution."""
import base64

import pytest

from plugins import config as cfg


def test_os_env_wins_when_set():
    env = cfg.merge_env({"KEY": "from_os"}, {"KEY": "from_config"})
    assert env["KEY"] == "from_os"


def test_config_fallback_when_absent():
    env = cfg.merge_env({}, {"KEY": "from_config"})
    assert env["KEY"] == "from_config"


def test_blank_os_value_falls_back_to_config():
    env = cfg.merge_env({"KEY": ""}, {"KEY": "from_config"})
    assert env["KEY"] == "from_config"
    env2 = cfg.merge_env({"KEY": "   "}, {"KEY": "from_config"})
    assert env2["KEY"] == "from_config"


def test_none_config_value_ignored():
    env = cfg.merge_env({"KEY": "os"}, {"KEY": None})
    assert env["KEY"] == "os"


def test_missing_fallbacks_is_ok():
    assert cfg.merge_env({"A": "1"}, None) == {"A": "1"}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_decode_config_path_resolves_relative_dir(tmp_path):
    (tmp_path / "mytools").mkdir()
    decoded, local = cfg.decode_config_path(_b64("mytools"), tmp_path)
    assert decoded == "mytools"
    assert local == (tmp_path / "mytools").resolve()


@pytest.mark.parametrize("hostile", ["../escape", "/etc/passwd", "C:\\evil", "a/../../b"])
def test_decode_config_path_rejects_traversal(tmp_path, hostile):
    with pytest.raises(ValueError):
        cfg.decode_config_path(_b64(hostile), tmp_path)


def test_decode_config_path_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        cfg.decode_config_path(_b64(""), tmp_path)


def test_validate_context_requires_jwks_for_bearer_jwt(tmp_path):
    ctx = cfg.AppContext(
        base_dir=tmp_path, tools_dir=tmp_path / "tools", env={}, auth_type="bearer_jwt",
        api_key_header="authorization", api_key_value="", jwks_url="", jwt_issuer=None,
        jwt_audience=None, jwt_required_scopes=None, host="0.0.0.0", port=8000,
        import_timeout=30, metrics_enabled=True, sandbox=False, sandbox_timeout=30,
        sandbox_mem_mb=0, sandbox_cpu_sec=0, admin_token="", require_signed=False,
        manifest_name="tools.manifest.json", signing_key=None,
    )
    with pytest.raises(RuntimeError):
        cfg.validate_context(ctx)


def test_transport_defaults_to_http_and_validates(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    ctx = cfg.build_context([], base_dir=tmp_path)
    assert ctx.mcp_transport == "http"
    cfg.validate_context(ctx)                       # no raise

    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    assert cfg.build_context([], base_dir=tmp_path).mcp_transport == "sse"

    monkeypatch.setenv("MCP_TRANSPORT", "bogus")
    with pytest.raises(RuntimeError):
        cfg.validate_context(cfg.build_context([], base_dir=tmp_path))


def test_load_environment_works_without_the_optional_framework(monkeypatch, tmp_path):
    # The agentic framework is an optional soft dependency; load_environment must
    # not require it (the server core never reads global_variables.env).
    monkeypatch.setattr(cfg, "global_variables", None)
    env = cfg.load_environment(tmp_path)
    assert isinstance(env, dict)
