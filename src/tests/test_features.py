"""Unit tests for the feature-branch additions:
signed-tool verification, disable/enable, stats/catalog, and the --sign/--validate CLI.

Run: pytest src/tests/test_features.py
Requires: fastmcp (for FunctionTool).
"""
import hashlib
import itertools
import json
import os
import time
from pathlib import Path

import multiple_mcp_main as m


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
    import sys
    pkg = f"feat_pkg_{next(_pkg_uid)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    sys.path.insert(0, str(Path(m.__file__).resolve().parent))
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
    v = m.ToolVerifier(d, "tools.manifest.json", signing_key=None, require=True)
    loader = m.ToolLoader(FakeMCP(), d, verifier=v)
    loader.load_all()
    assert "a" in loader.mcp.tools          # listed + matches
    assert "b" not in loader.mcp.tools      # not in manifest -> refused


def test_signing_detects_tamper(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    (d / "tools.manifest.json").write_text(json.dumps({"tools": {"a.py": "deadbeef"}}))
    v = m.ToolVerifier(d, "tools.manifest.json", signing_key=None, require=True)
    loader = m.ToolLoader(FakeMCP(), d, verifier=v)
    loader.load_all()
    assert "a" not in loader.mcp.tools      # hash mismatch -> refused


def test_hmac_manifest_signature_gate(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    tools = {"a.py": _sha(d / "a.py")}
    key = "s3cret"
    (d / "tools.manifest.json").write_text(json.dumps({"tools": tools, "signature": m._manifest_signature(tools, key)}))
    assert m.ToolVerifier(d, "tools.manifest.json", key, require=True).trusted
    (d / "tools.manifest.json").write_text(json.dumps({"tools": tools, "signature": "bad"}))
    assert not m.ToolVerifier(d, "tools.manifest.json", key, require=True).trusted


# ---- disable / enable ------------------------------------------------
def test_disable_enable(tmp_path):
    d, pkg = _dir(tmp_path)
    (d / "svc.py").write_text("def svc(x: int) -> int:\n    return x\n")
    loader = m.ToolLoader(FakeMCP(), d)
    loader.load_path(d / "svc.py")
    assert "svc" in loader.mcp.tools
    assert loader.disable("svc") is True
    assert "svc" not in loader.mcp.tools
    # reload while disabled must NOT re-register
    time.sleep(0.02)
    os.utime(d / "svc.py", None)
    loader.load_path(d / "svc.py")
    assert "svc" not in loader.mcp.tools
    mod = loader.enable("svc")
    assert mod == f"{pkg}.svc"
    loader.load_path(loader.file_for_module(mod))
    assert "svc" in loader.mcp.tools        # re-registered after enable


# ---- stats / catalog -------------------------------------------------
def test_stats_and_catalog(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "ok.py").write_text("from tools_sdk import tool\n@tool(description='desc')\ndef ok(x: int) -> int:\n    return x\n")
    (d / "broken.py").write_text("raise RuntimeError('x')\n")
    loader = m.ToolLoader(FakeMCP(), d)
    loader.load_all()
    stats = loader.stats()
    assert stats["total_tools"] == 1
    assert stats["failed_modules"] >= 1
    assert any(t["name"] == "ok" and t["description"] == "desc" for t in loader.catalog())


# ---- CLI: --sign then --validate ------------------------------------
def test_sign_then_validate(tmp_path):
    d, _ = _dir(tmp_path)
    (d / "a.py").write_text("def a(x: int) -> int:\n    return x\n")
    assert m.run_sign(d, signing_key="k") == 0
    manifest = json.loads((d / "tools.manifest.json").read_text())
    assert "a.py" in manifest["tools"] and "signature" in manifest
    assert m.run_validate(d) == 0           # a.py yields a tool
