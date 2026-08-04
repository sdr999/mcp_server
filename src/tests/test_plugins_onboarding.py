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
from plugins.onboarding import OnboardingConflict, OnboardingManager
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


SAFE_SOURCE = "from tools_sdk import tool\n\n@tool()\ndef greet(name: str) -> str:\n    return f'hi {name}'\n"


def _tool_src(name: str, extra: str = "") -> str:
    """An explicitly-declared tool (the contract onboarding now requires)."""
    return f"from tools_sdk import tool\n{extra}\n@tool()\ndef {name}():\n    return 1\n"


def test_no_new_dependencies_onboards_immediately(tmp_path):
    mgr = _manager(tmp_path)
    record = asyncio.run(mgr.onboard("greet", SAFE_SOURCE, []))
    assert record["status"] == "onboarded"
    assert "greet" in mgr.loader.mcp.tools
    assert not mgr.list_pending()


def test_guessed_dependency_name_is_held_pending(tmp_path):
    # `import someobscurelib` has no known import->distribution mapping, so the
    # package name is a guess. Not allowlisted -> held for admin confirmation.
    mgr = _manager(tmp_path)
    src = "import someobscurelib\n\ndef guesser():\n    return 1\n"
    record = asyncio.run(mgr.onboard("guesser", src, []))
    assert record["status"] == "pending"
    assert "guessed" in record["hold_reason"]
    assert "guesser" not in mgr.loader.mcp.tools


def test_allowlisted_guessed_dependency_is_not_held_for_being_guessed(tmp_path, monkeypatch):
    # Same guessed import, but allowlisted -> the guessed-name gate does not fire.
    async def fake_pip_install(specs, timeout, only_binary=False):
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_install", fake_pip_install)
    mgr = _manager(tmp_path, allowlist={"someobscurelib"})
    src = "def okguess():\n    return 1\n"  # stem==func so it registers a tool
    # declare the import via source but keep the tool loadable without the dep
    record = asyncio.run(mgr.onboard("okguess", "import someobscurelib\n" + src, []))
    # It will fail to load (someobscurelib isn't really importable) -> pending,
    # but crucially NOT for the "guessed" reason.
    assert "guessed" not in record.get("hold_reason", "")


def test_transitive_dependency_high_risk_holds_pending(tmp_path, monkeypatch):
    # Direct dep is allowlisted/clean, but its resolved closure contains a
    # denylisted transitive package -> the whole submission is held.
    async def fake_closure(specs, timeout, only_binary=False):
        return True, [
            {"name": "gooddirect", "version": "1.0", "requested": True},
            {"name": "evil-transitive", "version": "0.1", "requested": False},
        ]

    async def must_not_install(specs, timeout, only_binary=False):
        pytest.fail("install must not run when a transitive dep is high risk")

    monkeypatch.setattr("plugins.onboarding._pip_resolve_closure", fake_closure)
    monkeypatch.setattr("plugins.onboarding._pip_install", must_not_install)
    mgr = _manager(tmp_path, network_check=True, allowlist={"gooddirect"},
                   denylist={"evil-transitive"})
    record = asyncio.run(mgr.onboard("closuretool", "def closuretool():\n    return 1\n",
                                     ["gooddirect==1.0"]))
    assert record["status"] == "pending"
    assert "transitive" in record["hold_reason"]
    assert "evil-transitive" in record["hold_reason"]
    assert any(r["name"] == "evil-transitive" for r in record["closure_reports"])


def test_clean_transitive_closure_proceeds_to_install(tmp_path, monkeypatch):
    installed = {}

    async def fake_closure(specs, timeout, only_binary=False):
        return True, [
            {"name": "gooddirect", "version": "1.0", "requested": True},
            {"name": "benign-transitive", "version": "2.0", "requested": False},
        ]

    async def fake_install(specs, timeout, only_binary=False):
        installed["specs"] = specs
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_resolve_closure", fake_closure)
    monkeypatch.setattr("plugins.onboarding._pip_install", fake_install)
    mgr = _manager(tmp_path, network_check=True,
                   allowlist={"gooddirect", "benign-transitive"}, denylist=set())
    record = asyncio.run(mgr.onboard("cleanclosure", _tool_src("cleanclosure"),
                                     ["gooddirect==1.0"]))
    assert record["status"] == "onboarded"
    assert installed["specs"] == ["gooddirect==1.0"]
    assert record["closure_reports"]  # closure was assessed


def test_unresolvable_closure_holds_pending(tmp_path, monkeypatch):
    async def failing_closure(specs, timeout, only_binary=False):
        return False, "No matching distribution found for nonexistent==1.0"

    async def must_not_install(specs, timeout, only_binary=False):
        pytest.fail("install must not run when closure resolution failed")

    monkeypatch.setattr("plugins.onboarding._pip_resolve_closure", failing_closure)
    monkeypatch.setattr("plugins.onboarding._pip_install", must_not_install)
    mgr = _manager(tmp_path, network_check=True, allowlist={"nonexistent"}, denylist=set())
    record = asyncio.run(mgr.onboard("badclosure", "def badclosure():\n    return 1\n",
                                     ["nonexistent==1.0"]))
    assert record["status"] == "pending"
    assert "could not resolve dependency closure" in record["hold_reason"]


def test_pending_source_is_stored_non_importably(tmp_path):
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    asyncio.run(mgr.onboard("held", "import evilpkg\n", ["evilpkg==1.0"]))
    # stored as held.py.pending (+ held.json), never held.py
    names = sorted(p.name for p in mgr.pending_dir.iterdir())
    assert "held.py.pending" in names
    assert "held.json" in names
    assert "held.py" not in names


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
    canon = [risk.canonical_name(risk.spec_name(spec)) for spec, _origin in specs]
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

    async def must_not_run(specs, timeout, only_binary=False):
        pytest.fail("must not attempt install when autoinstall is disabled")

    monkeypatch.setattr("plugins.onboarding._pip_install", must_not_run)
    record = asyncio.run(mgr.onboard("needs_dep", SAFE_SOURCE, ["harmlesspkg==1.0"]))
    assert record["status"] == "pending"
    assert "auto-install" in record["hold_reason"]


def test_low_risk_dependency_auto_installs_and_loads(tmp_path, monkeypatch):
    installed = {}

    async def fake_pip_install(specs, timeout, only_binary=False):
        installed["specs"] = specs
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_install", fake_pip_install)
    mgr = _manager(tmp_path, allowlist={"harmlesspkg"})
    # harmlesspkg is declared but not imported at module level, since the fake
    # install doesn't actually make it importable -- this test is about the
    # install-then-load wiring, not a real package install.
    src = _tool_src("good_tool")
    record = asyncio.run(mgr.onboard("good_tool", src, ["harmlesspkg==1.0"]))
    assert record["status"] == "onboarded"
    assert installed["specs"] == ["harmlesspkg==1.0"]
    assert not mgr.list_pending()
    assert "good_tool" in mgr.loader.mcp.tools


def test_failed_install_falls_back_to_pending(tmp_path, monkeypatch):
    async def failing_pip_install(specs, timeout, only_binary=False):
        return False, "network unreachable"

    monkeypatch.setattr("plugins.onboarding._pip_install", failing_pip_install)
    mgr = _manager(tmp_path, allowlist={"harmlesspkg"})
    src = _tool_src("good_tool", extra="import harmlesspkg")
    record = asyncio.run(mgr.onboard("flaky_tool", src, ["harmlesspkg==1.0"]))
    assert record["status"] == "pending"
    assert "install failed" in record["hold_reason"]


def test_approve_forces_install_and_load(tmp_path, monkeypatch):
    async def fake_pip_install(specs, timeout, only_binary=False):
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_install", fake_pip_install)
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    # evilpkg is declared but not imported at module level, so the (faked)
    # install doesn't need to actually provide an importable module for the
    # subsequent load to succeed -- this test is about the approve/override
    # mechanics, not a real package install.
    src = _tool_src("risky_tool")
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


# ---- Batch 3/4: conflict, overwrite, signed mode, name validation ----------
def test_duplicate_name_conflicts_without_overwrite(tmp_path):
    mgr = _manager(tmp_path)
    asyncio.run(mgr.onboard("dup", "def dup():\n    return 1\n", []))
    with pytest.raises(OnboardingConflict):
        asyncio.run(mgr.onboard("dup", "def dup():\n    return 2\n", []))


def test_pending_name_conflicts_without_overwrite(tmp_path):
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    asyncio.run(mgr.onboard("dup2", "import evilpkg\n", ["evilpkg==1.0"]))
    assert mgr.get_pending("dup2") is not None
    with pytest.raises(OnboardingConflict):
        asyncio.run(mgr.onboard("dup2", "def dup2():\n    return 1\n", []))


def test_overwrite_replaces_existing_tool(tmp_path):
    mgr = _manager(tmp_path)
    asyncio.run(mgr.onboard("dup3", _tool_src("dup3"), []))
    rec = asyncio.run(mgr.onboard("dup3", _tool_src("dup3", extra="# v2"), [], overwrite=True))
    assert rec["status"] == "onboarded"
    assert "# v2" in (mgr.tools_dir / "dup3.py").read_text()


def test_failed_overwrite_restores_previous_working_version(tmp_path):
    mgr = _manager(tmp_path)
    good = _tool_src("restorable")
    asyncio.run(mgr.onboard("restorable", good, []))
    assert "restorable" in mgr.loader.mcp.tools
    # Overwrite with a source that registers no tool -> load fails.
    rec = asyncio.run(mgr.onboard("restorable", "def not_matching():\n    return 1\n", [], overwrite=True))
    assert rec["status"] == "pending"
    # The previously-working version is restored on disk and in the registry.
    assert (mgr.tools_dir / "restorable.py").read_text() == good
    assert "restorable" in mgr.loader.mcp.tools


def test_signed_tools_mode_rejects_onboarding(tmp_path):
    mgr = _manager(tmp_path)

    class _Verifier:
        require = True

    mgr.loader.verifier = _Verifier()
    with pytest.raises(ValueError):
        asyncio.run(mgr.onboard("nope", "def nope():\n    return 1\n", []))


def test_approve_and_reject_reject_invalid_names(tmp_path):
    mgr = _manager(tmp_path)
    with pytest.raises(KeyError):
        asyncio.run(mgr.approve("../evil"))
    assert mgr.reject("../evil") is False


def test_pending_detail_includes_source(tmp_path):
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    asyncio.run(mgr.onboard("detailed", "import evilpkg\n# marker\n", ["evilpkg==1.0"]))
    detail = mgr.get_pending_detail("detailed")
    assert detail is not None
    assert "# marker" in detail["source"]
    assert mgr.get_pending_detail("missing") is None


def test_pending_count_tracks_queue(tmp_path):
    mgr = _manager(tmp_path, denylist={"evilpkg"})
    assert mgr.pending_count() == 0
    asyncio.run(mgr.onboard("p1", "import evilpkg\n", ["evilpkg==1.0"]))
    assert mgr.pending_count() == 1


def test_audit_log_records_actions(tmp_path):
    audit = tmp_path / "audit.log"
    mgr = _manager(tmp_path, denylist={"evilpkg"}, audit_log_path=audit)
    asyncio.run(mgr.onboard("audited", "import evilpkg\n", ["evilpkg==1.0"]))
    mgr.reject("audited")
    lines = [l for l in audit.read_text().splitlines() if l.strip()]
    actions = [__import__("json").loads(l) for l in lines]
    assert [a["action"] for a in actions] == ["onboard", "reject"]
    assert actions[0]["result"] == "pending"
    assert actions[1]["result"] == "rejected"


def test_only_binary_flag_is_passed_to_pip(tmp_path, monkeypatch):
    seen = {}

    async def fake_install(specs, timeout, only_binary=False):
        seen["only_binary"] = only_binary
        return True, ""

    monkeypatch.setattr("plugins.onboarding._pip_install", fake_install)
    mgr = _manager(tmp_path, allowlist={"harmlesspkg"}, only_binary=True)
    asyncio.run(mgr.onboard("obtool", "def obtool():\n    return 1\n", ["harmlesspkg==1.0"]))
    assert seen["only_binary"] is True


def test_only_binary_args_builder():
    from plugins.onboarding import _only_binary_args
    assert _only_binary_args(True) == ["--only-binary", ":all:"]
    assert _only_binary_args(False) == []


# ---- Exposure policy + tool manifest (Phases 1-3) --------------------------
THREE_FN_SRC = (
    "from tools_sdk import tool\n\n"
    "def _celsius_to_f(c):\n    return c * 9 / 5 + 32\n\n"
    "def _fetch_raw(city):\n    return {'c': 21}\n\n"
    "@tool(name='current_weather', description='Weather for a city')\n"
    "def get_weather(city: str) -> str:\n"
    "    return f\"{city}: {_celsius_to_f(_fetch_raw(city)['c'])}F\"\n"
)


def test_three_functions_only_the_declared_tool_is_exposed(tmp_path):
    # The scenario: 1 @tool + 2 helpers. Only the tool is registered; the
    # manifest names the exposed tool and lists the helpers as not_exposed.
    mgr = _manager(tmp_path)
    rec = asyncio.run(mgr.onboard("weather", THREE_FN_SRC, []))
    assert rec["status"] == "onboarded"
    assert rec["registered_tools"] == ["current_weather"]
    m = rec["tool_manifest"]
    assert m["mechanism"] == "decorator"
    assert [t["name"] for t in m["tools"]] == ["current_weather"]
    not_exposed = {e["function"] for e in m["not_exposed"]}
    assert not_exposed == {"_celsius_to_f", "_fetch_raw"}
    # the exposed tool carries a param schema in the manifest
    assert "city" in str(m["tools"][0]["parameters"])


def test_legacy_stem_convention_is_rejected_under_strict_policy(tmp_path):
    mgr = _manager(tmp_path)  # require_explicit defaults to True
    rec = asyncio.run(mgr.onboard("legacytool", "def legacytool():\n    return 1\n", []))
    assert rec["status"] == "pending"
    assert "legacy filename-match" in rec["hold_reason"]
    assert "legacytool" not in mgr.loader.mcp.tools


def test_legacy_allowed_when_policy_relaxed(tmp_path):
    mgr = _manager(tmp_path, require_explicit=False)
    rec = asyncio.run(mgr.onboard("legacytool", "def legacytool():\n    return 1\n", []))
    assert rec["status"] == "onboarded"
    assert rec["tool_manifest"]["mechanism"] == "legacy"


def test_no_tool_exposed_gives_actionable_reason_and_lists_functions(tmp_path):
    mgr = _manager(tmp_path)
    src = "def helper_a(x):\n    return x\n\ndef do_thing(y):\n    return y\n"
    rec = asyncio.run(mgr.onboard("notool", src, []))
    assert rec["status"] == "pending"
    assert "no function is exposed as a tool" in rec["hold_reason"]
    assert "helper_a" in rec["hold_reason"] and "do_thing" in rec["hold_reason"]


def test_max_tools_per_file_enforced(tmp_path):
    mgr = _manager(tmp_path, max_tools=1)
    src = ("from tools_sdk import tool\n\n"
           "@tool()\ndef a():\n    return 1\n\n"
           "@tool()\ndef b():\n    return 2\n")
    rec = asyncio.run(mgr.onboard("multi", src, []))
    assert rec["status"] == "pending"
    assert "exceeding the limit" in rec["hold_reason"]


def test_tools_export_shadowing_decorated_emits_warning(tmp_path):
    mgr = _manager(tmp_path)
    src = ("from tools_sdk import tool\n\n"
           "@tool()\ndef exposed():\n    return 1\n\n"
           "@tool()\ndef shadowed():\n    return 2\n\n"
           "TOOLS = [exposed]\n")
    rec = asyncio.run(mgr.onboard("shadowtool", src, []))
    assert rec["status"] == "onboarded"
    assert rec["tool_manifest"]["mechanism"] == "TOOLS"
    assert any("shadowed" in w for w in rec["tool_manifest"]["warnings"])
