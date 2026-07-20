"""Tests for env precedence: OS env wins when set and non-blank, else config/.env."""
import multiple_mcp_main as m


def test_os_env_wins_when_set():
    env = m.merge_env({"KEY": "from_os"}, {"KEY": "from_config"})
    assert env["KEY"] == "from_os"


def test_config_fallback_when_absent():
    env = m.merge_env({}, {"KEY": "from_config"})
    assert env["KEY"] == "from_config"


def test_blank_os_value_falls_back_to_config():
    # a set-but-empty OS var must NOT block the config fallback
    env = m.merge_env({"KEY": ""}, {"KEY": "from_config"})
    assert env["KEY"] == "from_config"
    env2 = m.merge_env({"KEY": "   "}, {"KEY": "from_config"})
    assert env2["KEY"] == "from_config"


def test_os_only_keys_preserved():
    env = m.merge_env({"ONLY_OS": "x"}, {"ONLY_CONFIG": "y"})
    assert env["ONLY_OS"] == "x" and env["ONLY_CONFIG"] == "y"


def test_none_config_value_ignored():
    env = m.merge_env({"KEY": "os"}, {"KEY": None})
    assert env["KEY"] == "os"


def test_missing_fallbacks_is_ok():
    assert m.merge_env({"A": "1"}, None) == {"A": "1"}
