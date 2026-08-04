"""Unit tests for the dynamic tool loader and config validation.

These import multiple_mcp_main WITHOUT triggering any start-up side effects,
which was impossible before the refactor (argparse/Azure ran at import time).

Run: pytest src/tests/test_tool_loader.py
Requires: fastmcp (for FunctionTool). The Azure/watchdog imports are only needed
at module import; the tests themselves use a fake MCP.
"""
import base64
import textwrap
from pathlib import Path

import pytest

import multiple_mcp_main as m


# ----------------------------------------------------------------------
# decode_config_path
# ----------------------------------------------------------------------
def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_decode_config_valid(tmp_path):
    rel, local = m.decode_config_path(_b64("mcp_servers/traced_tools"), tmp_path)
    assert rel == "mcp_servers/traced_tools"
    assert str(local).startswith(str(tmp_path.resolve()))


@pytest.mark.parametrize("bad", ["../etc/passwd", "/abs/path", "a/../../b", "C:\\win"])
def test_decode_config_rejects_unsafe(tmp_path, bad):
    with pytest.raises(ValueError):
        m.decode_config_path(_b64(bad), tmp_path)


# ----------------------------------------------------------------------
# ToolLoader
# ----------------------------------------------------------------------
class FakeMCP:
    """Records add/remove instead of talking to a real server."""

    def __init__(self):
        self.tools = {}

    def add_tool(self, tool):
        self.tools[tool.name] = tool
        return tool

    def remove_tool(self, name, version=None):
        self.tools.pop(name, None)


import itertools
_pkg_uid = itertools.count()


def _loader(tmp_path):
    """Return (loader, tools_dir, package_name). Each test gets a UNIQUE package
    name so Python's sys.modules cache for the package does not bleed across
    tests (in production the tools-dir basename is a single stable package)."""
    import importlib
    import sys
    pkg = f"tools_pkg_{next(_pkg_uid)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    sys.path.insert(0, str(Path(m.__file__).resolve().parent))  # tools_sdk importable
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    return m.ToolLoader(FakeMCP(), d), d, pkg


def test_legacy_convention(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "adder.py").write_text("def adder(a: int, b: int) -> int:\n    return a + b\n")
    loader.load_path(d / "adder.py")
    assert "adder" in loader.mcp.tools


def test_decorator_decouples_name_from_file(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "weatherfile.py").write_text(textwrap.dedent("""
        from tools_sdk import tool
        @tool(name="weather", description="w")
        def anything(city: str) -> str:
            return city
    """))
    loader.load_path(d / "weatherfile.py")
    assert "weather" in loader.mcp.tools           # named by decorator, not file
    assert "weatherfile" not in loader.mcp.tools


def test_multiple_tools_per_file_via_TOOLS(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "pack.py").write_text(textwrap.dedent("""
        def a(x: int) -> int: return x
        def b(x: int) -> int: return x
        TOOLS = {"alpha": a, "beta": b}
    """))
    loader.load_path(d / "pack.py")
    assert {"alpha", "beta"} <= set(loader.mcp.tools)


def test_register_hook(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "reg.py").write_text(textwrap.dedent("""
        def hello(name: str) -> str: return name
        def register(mcp):
            mcp.add_tool(hello)
    """))
    loader.load_path(d / "reg.py")
    assert "hello" in loader.mcp.tools


def test_duplicate_name_first_wins(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "one.py").write_text(textwrap.dedent("""
        from tools_sdk import tool
        @tool(name="dup")
        def x() -> int: return 1
    """))
    (d / "two.py").write_text(textwrap.dedent("""
        from tools_sdk import tool
        @tool(name="dup")
        def y() -> int: return 2
    """))
    loader.load_path(d / "one.py")
    loader.load_path(d / "two.py")
    assert loader._name_owner["dup"] == f"{pkg}.one"   # first wins


def test_reload_replaces_old_tools(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    f = d / "pack.py"
    f.write_text("def a(): return 1\nTOOLS = {'alpha': a}\n")
    loader.load_path(f)
    assert "alpha" in loader.mcp.tools
    import os, time
    time.sleep(0.01)
    f.write_text("def b(): return 2\nTOOLS = {'beta': b}\n")
    os.utime(f, None)
    loader.load_path(f)
    assert "beta" in loader.mcp.tools and "alpha" not in loader.mcp.tools


# ----------------------------------------------------------------------
# Fault tolerance: a faulty tool/module must never stop the loader/server.
# ----------------------------------------------------------------------
def test_import_error_is_isolated(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "boom.py").write_text("raise RuntimeError('boom at import')\ndef boom(): return 1\n")
    (d / "good.py").write_text("def good(x: int) -> int:\n    return x\n")
    loader.load_all()                       # must not raise
    assert "good" in loader.mcp.tools       # sibling still loads
    assert "boom" not in loader.mcp.tools


def test_tool_with_input_params_loads(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "wi.py").write_text("def wi(city: str, days: int = 3) -> str:\n    return f'{city}:{days}'\n")
    loader.load_path(d / "wi.py")
    assert "wi" in loader.mcp.tools


def test_bad_entry_in_TOOLS_is_skipped(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "mixed.py").write_text("def good(x: int) -> int: return x\nTOOLS = {'ok': good, 'bad': 42}\n")
    loader.load_path(d / "mixed.py")
    assert "ok" in loader.mcp.tools and "bad" not in loader.mcp.tools


def test_register_exception_is_isolated(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    (d / "rb.py").write_text("def register(mcp):\n    raise ValueError('nope')\n")
    (d / "ok.py").write_text("def ok(x: int) -> int: return x\n")
    loader.load_all()                       # must not raise
    assert "ok" in loader.mcp.tools


def test_reload_to_faulty_unregisters_old(tmp_path):
    loader, d, pkg = _loader(tmp_path)
    import os, time
    f = d / "svc.py"
    f.write_text("def svc(x: int) -> int: return x\n")
    loader.load_path(f)
    assert "svc" in loader.mcp.tools
    time.sleep(0.02)
    f.write_text("raise RuntimeError('broken edit')\n")
    os.utime(f, None)
    loader.load_path(f)                     # must not raise
    assert "svc" not in loader.mcp.tools
