"""Tests for subprocess sandboxing and the metrics registry.

Run: pytest src/tests/test_sandbox_metrics.py
Requires: fastmcp. Sandbox tests spawn subprocesses via the same interpreter.
"""
import asyncio
import itertools
import sys
import time
from pathlib import Path

import pytest

import multiple_mcp_main as m
from metrics import Metrics


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def add_tool(self, t):
        self.tools[t.name] = t
        return t

    def remove_tool(self, name, version=None):
        self.tools.pop(name, None)


_uid = itertools.count()


def _dir(tmp_path):
    import importlib
    pkg = f"sbx_pkg_{next(_uid)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    sys.path.insert(0, str(Path(m.__file__).resolve().parent))
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    return d


async def _call(loader, name, **args):
    return await loader.mcp.tools[name].fn(**args)


# ---- sandbox ----------------------------------------------------------
def test_sandbox_returns_correct_result(tmp_path):
    d = _dir(tmp_path)
    (d / "add.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    loader = m.ToolLoader(FakeMCP(), d, sandbox=True, sandbox_timeout=15)
    loader.load_path(d / "add.py")
    assert asyncio.run(_call(loader, "add", a=2, b=3)) == 5


def test_sandbox_isolates_crash(tmp_path):
    d = _dir(tmp_path)
    (d / "boom.py").write_text("def boom(x: int) -> int:\n    raise ValueError('kaboom')\n")
    loader = m.ToolLoader(FakeMCP(), d, sandbox=True, sandbox_timeout=15)
    loader.load_path(d / "boom.py")
    with pytest.raises(RuntimeError, match="kaboom"):
        asyncio.run(_call(loader, "boom", x=1))


def test_sandbox_enforces_timeout(tmp_path):
    d = _dir(tmp_path)
    (d / "slow.py").write_text("import time\ndef slow(x: int) -> int:\n    time.sleep(10)\n    return x\n")
    loader = m.ToolLoader(FakeMCP(), d, sandbox=True, sandbox_timeout=1)
    loader.load_path(d / "slow.py")
    start = time.perf_counter()
    with pytest.raises(RuntimeError, match="exceeded"):
        asyncio.run(_call(loader, "slow", x=1))
    assert time.perf_counter() - start < 5


def test_metrics_wrap_in_process(tmp_path):
    d = _dir(tmp_path)
    (d / "mul.py").write_text("def mul(a: int, b: int) -> int:\n    return a * b\n")
    loader = m.ToolLoader(FakeMCP(), d, wrap_execution=True, sandbox=False)
    loader.load_path(d / "mul.py")
    assert asyncio.run(_call(loader, "mul", a=4, b=5)) == 20


# ---- metrics registry -------------------------------------------------
def test_metrics_render_counter_and_gauge():
    mx = Metrics()
    mx.declare("mcp_tool_calls_total", "calls")
    mx.inc("mcp_tool_calls_total", tool="a")
    mx.inc("mcp_tool_calls_total", tool="a")
    mx.observe("mcp_tool_duration_seconds", 0.5, tool="a")
    mx.gauge("mcp_ready", lambda: 1.0, "ready")
    out = mx.render()
    assert 'mcp_tool_calls_total{tool="a"} 2.0' in out
    assert "# TYPE mcp_tool_calls_total counter" in out
    assert "mcp_tool_duration_seconds_count{tool=\"a\"} 1" in out
    assert "mcp_ready 1.0" in out
