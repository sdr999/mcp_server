"""Tests for plugins.onboarding.OnboardingManager: the risk-gated onboarding
flow that replaces the removed Azure sync path. Network checks are disabled
throughout so results are deterministic and offline.
"""
import asyncio
import itertools
import sys
from pathlib import Path

import pytest

from plugins import dependency_risk as risk
from plugins.onboarding import OnboardingManager
from plugins.tool_loader import ToolLoader

_uid = itertools.count()
SRC = Path(__file__).resolve().parent.parent


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def add_tool(self, t):
        self.tools[t.name] = t
        return t

    def remove_tool(self, name, version=None):
        self.tools.pop(name, None)


def _dirs(tmp_path):
    import importlib
    pkg = f"onboard_pkg_{next(_uid)}"
    tools_dir = tmp_path / pkg
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    sys.path.insert(0, str(SRC))
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    pending_dir = tmp_path / f"{pkg}_pending"
    return tools_dir, pending_dir


def _manager(tmp_path, **kwargs):
    tools_dir, pending_dir = _dirs(tmp_path)
    loader = ToolLoader(FakeMCP(), tools_dir, src_dir=SRC)
    kwargs.setdefault("network_check", False)
    kwargs.setdefault("allowlist", set())
    kwargs.setdefault("denylist", set())
    return OnboardingManager(tools_dir, pending_dir, loader, **kwargs)


SAFE_SOURCE = "def greet(name: str) -> str:\n    return f'hi {name}'\n"


def test_no_new_dependencies_onboards_immediately(tmp_path):
    mgr = _manager(tmp_path)
    record = asyncio.run(mgr.onboard("greet", SAFE_SOURCE, []))
    assert record["status"] == "onboarded"
    assert "greet" in mgr.loader.mcp.tools
    assert not mgr.list_pending()


def test_invalid_name_rejected(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(mgr.onboard("../evil", SAFE_SOURCE, []))


def test_syntax_error_rejected(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(mgr.onboard("broken", "def broken(:\n", []))


def test_source_registering_no_tool_is_held_pending_not_falsely_onboarded(tmp_path):
    # Parses fine, no deps, but the function name != module stem and there's no
    # @tool / TOOLS export -> the loader registers nothing. Onboarding must NOT
    # report "onboarded" (the pre-fix bug).
    mgr = _manager(tmp_path)
    record = asyncio.run(mgr.onboard("mytool", "def something_else():\n    return 1\n", []))
    assert record["status"] == "pending"
    assert "failed to load" in record["hold_reason"]
    # brand-new file that failed to load is rolled back, not left behind
    assert not (mgr.tools_dir / "mytool.py").exists()


def test_import_error_source_is_held_pending_and_rolled_back(tmp_path):
    mgr = _manager(tmp_path)
    record = asyncio.run(mgr.onboard("boomtool", "raise RuntimeError('boom')\n", []))
    assert record["status"] == "pending"
    assert "failed to load" in record["hold_reason"]
    assert not (mgr.tools_dir / "boomtool.py").exists()


def test_slow_import_is_bounded_and_does_not_hang(tmp_path):
    # Top-level sleep longer than the import timeout: the off-loop, timeout-bounded
    # import must give up and hold pending rather than freeze. Whole test < 1s.
    mgr = _manager(tmp_path, import_timeout=0.5)
    src = "import time\ntime.sleep(5)\n\ndef slowtool():\n    return 1\n"
    record = asyncio.run(mgr.onboard("slowtool", src, []))
    assert record["status"] == "pending"
    assert "within 0.5s" in record["hold_reason"]
    assert not (mgr.tools_dir / "slowtool.py").exists()


def test_declared_and_inferred_dependency_are_deduped(tmp_path):
    # `import dotenv` resolves to `python-dotenv`; declaring `python_dotenv`
    # canonicalizes to the same package -> a single spec, installed once.
    mgr = _manager(tmp_path, allowlist={"python-dotenv"})
    src = "import dotenv\n\ndef greet_dep():\n    return 'ok'\n"
    specs = mgr._build_specs(src, ["python_dotenv==1.0.0"])
    canon = [risk.canonical_name(risk.spec_name(s)) for s in specs]
    assert canon.count("python-dotenv") == 1, specs


def test_high_risk_dependency_is_held_pending(tmp_path):
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    src = "import evilpkg\n\ndef use_it():\n    return evilpkg.run()\n"
    record = asyncio.run(mgr.onboard("bad_tool", src, ["evilpkg==1.0"]))
    assert record["status"] == "pending"
    assert "evilpkg" not in mgr.loader.mcp.tools
    assert "bad_tool" not in mgr.loader.mcp.tools
    pending = mgr.list_pending()
    assert len(pending) == 1
    assert pending[0]["name"] == "bad_tool"


def test_autoinstall_disabled_holds_pending_even_for_low_risk(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, autoinstall=False, allowlist={"harmlesspkg"})

    async def must_not_run(specs, timeout):
        pytest.fail("must not attempt install when autoinstall is disabled")

    monkeypatch.setattr("plugins.onboarding._pip_install", must_not_run)
    record = asyncio.run(mgr.onboard("needs_dep", SAFE_SOURCE, ["harmlesspkg==1.0"]))
    assert record["status"] == "pending"
    assert "auto-install" in record["hold_reason"]


def test_low_risk_dependency_auto_installs_and_loads(tmp_path, monkeypatch):
    installed = {}

    async def fake_pip_install(specs, timeout):
        installed["specs"] = specs
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_install", fake_pip_install)
    mgr = _manager(tmp_path, allowlist={"harmlesspkg"})
    # harmlesspkg is declared but not imported at module level, since the fake
    # install doesn't actually make it importable -- this test is about the
    # install-then-load wiring, not a real package install.
    src = "def good_tool():\n    return 'ok'\n"
    record = asyncio.run(mgr.onboard("good_tool", src, ["harmlesspkg==1.0"]))
    assert record["status"] == "onboarded"
    assert installed["specs"] == ["harmlesspkg==1.0"]
    assert not mgr.list_pending()
    assert "good_tool" in mgr.loader.mcp.tools


def test_failed_install_falls_back_to_pending(tmp_path, monkeypatch):
    async def failing_pip_install(specs, timeout):
        return False, "network unreachable"

    monkeypatch.setattr("plugins.onboarding._pip_install", failing_pip_install)
    mgr = _manager(tmp_path, allowlist={"harmlesspkg"})
    src = "import harmlesspkg\n\ndef uses_dep():\n    return 'ok'\n"
    record = asyncio.run(mgr.onboard("flaky_tool", src, ["harmlesspkg==1.0"]))
    assert record["status"] == "pending"
    assert "install failed" in record["hold_reason"]


def test_approve_forces_install_and_load(tmp_path, monkeypatch):
    async def fake_pip_install(specs, timeout):
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_install", fake_pip_install)
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    # evilpkg is declared but not imported at module level, so the (faked)
    # install doesn't need to actually provide an importable module for the
    # subsequent load to succeed -- this test is about the approve/override
    # mechanics, not a real package install.
    src = "def risky_tool():\n    return 'ok'\n"
    record = asyncio.run(mgr.onboard("risky_tool", src, ["evilpkg==1.0"]))
    assert record["status"] == "pending"

    approved = asyncio.run(mgr.approve("risky_tool"))
    assert approved["status"] == "onboarded"
    assert "risky_tool" in mgr.loader.mcp.tools
    assert not mgr.list_pending()


def test_approve_unknown_raises_keyerror(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(KeyError):
        asyncio.run(mgr.approve("nope"))


def test_reject_discards_pending(tmp_path):
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    src = "import evilpkg\n"
    asyncio.run(mgr.onboard("throwaway", src, ["evilpkg==1.0"]))
    assert len(mgr.list_pending()) == 1
    assert mgr.reject("throwaway") is True
    assert mgr.list_pending() == []
    assert mgr.reject("throwaway") is False


def test_onboarding_disabled_flag(tmp_path):
    mgr = _manager(tmp_path, enabled=False)
    with pytest.raises(ValueError):
        asyncio.run(mgr.onboard("anything", SAFE_SOURCE, []))
