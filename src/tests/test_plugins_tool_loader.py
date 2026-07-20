"""Tests for plugins.tool_loader + plugins.signing: signed-tool verification,
disable/enable, stats/catalog, and sandboxed execution.
"""
import asyncio
import hashlib
import itertools
import json
import sys
import time
from pathlib import Path

import pytest

from plugins.signing import ToolVerifier
from plugins.tool_loader import ToolLoader

SRC = Path(__file__).resolve().parent.parent


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def add_tool(self, t):
        self.tools[t.name] = t
        return t

    def remove_tool(self, name, version=None):
        self.tools.pop(name, None)


_pkg_uid = itertools.count()


def _dir(tmp_path):
    import importlib
    pkg = f"loader_pkg_{next(_pkg_uid)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    sys.path.insert(0, str(SRC))
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    return d, pkg


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---- signed tools ----------------------------------------------------
def test_signing_requires_manifest_match(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    (d / "b.py").write_text("def b(x: int) -> int:\n    return x\n")
    (d / "tools.manifest.json").write_text(json.dumps({"tools": {"a.py": _sha(d / "a.py")}}))
    v = ToolVerifier(d, "tools.manifest.json", signing_key=None, require=True)
    loader = ToolLoader(FakeMCP(), d, verifier=v, src_dir=SRC)
    loader.load_all()
    assert "a" in loader.mcp.tools
    assert "b" not in loader.mcp.tools


def test_unsigned_mode_loads_everything(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    loader = ToolLoader(FakeMCP(), d, verifier=None, src_dir=SRC)
    loader.load_all()
    assert "a" in loader.mcp.tools


# ---- disable / enable --------------------------------------------------
def test_disable_then_enable_round_trip(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    loader = ToolLoader(FakeMCP(), d, src_dir=SRC)
    loader.load_all()
    assert "a" in loader.mcp.tools

    assert loader.disable("a") is True
    assert "a" not in loader.mcp.tools
    assert loader.stats()["disabled_tools"] == 1

    module = loader.enable("a")
    assert module is not None
    loader.load_path(loader.file_for_module(module))
    assert "a" in loader.mcp.tools
    assert loader.stats()["disabled_tools"] == 0


def test_disable_unknown_tool_returns_false(tmp_path):
    d, _ = _dir(tmp_path)
    loader = ToolLoader(FakeMCP(), d, src_dir=SRC)
    assert loader.disable("nope") is False


# ---- fault isolation -----------------------------------------------------
def test_broken_module_is_isolated(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "good.py").write_text("def good(x: int) -> int:\n    return x\n")
    (d / "bad.py").write_text("raise RuntimeError('boom')\n")
    loader = ToolLoader(FakeMCP(), d, src_dir=SRC)
    loader.load_all()
    assert "good" in loader.mcp.tools
    stats = loader.stats()
    assert stats["failed_modules"] == 1


# ---- catalog / stats ------------------------------------------------------
def test_catalog_contains_registered_tools(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    loader = ToolLoader(FakeMCP(), d, src_dir=SRC)
    loader.load_all()
    names = [t["name"] for t in loader.catalog()]
    assert names == ["a"]


# ---- sandboxed execution ---------------------------------------------------
async def _call(loader, name, **args):
    return await loader.mcp.tools[name].fn(**args)


def test_sandbox_returns_correct_result(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "adder.py").write_text("def adder(x: int, y: int) -> int:\n    return x + y\n")
    loader = ToolLoader(FakeMCP(), d, sandbox=True, sandbox_timeout=10, src_dir=SRC)
    loader.load_all()
    result = asyncio.run(_call(loader, "adder", x=2, y=3))
    assert result == 5


def test_sandbox_timeout_raises(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "slow.py").write_text(
        "import time\n\ndef slow(secs: float) -> str:\n    time.sleep(secs)\n    return 'done'\n"
    )
    loader = ToolLoader(FakeMCP(), d, sandbox=True, sandbox_timeout=0.5, src_dir=SRC)
    loader.load_all()
    with pytest.raises(RuntimeError):
        asyncio.run(_call(loader, "slow", secs=5))
