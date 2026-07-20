"""CLI utilities: ``--validate DIR`` (CI gate) and ``--sign DIR`` (manifest generation)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from .signing import sha256_file, manifest_signature
from .tool_loader import ToolLoader

DEFAULT_MANIFEST = "tools.manifest.json"


def run_validate(tools_dir: Path, src_dir: Path) -> int:
    """Load a local tools directory and report results. No server started.
    Exit code 0 if all modules yield tools, 1 if any failed/empty."""
    if not tools_dir.exists():
        print(json.dumps({"error": f"directory not found: {tools_dir}"}))
        return 2
    sys.path.insert(0, str(tools_dir.resolve().parent))
    sys.path.insert(0, str(src_dir))  # tools_sdk importable
    loader = ToolLoader(FastMCP(name="validate"), tools_dir, src_dir=src_dir)
    loader.load_all()
    stats = loader.stats()
    print(json.dumps({"stats": stats, "tools": [t["name"] for t in loader.catalog()]}, indent=2))
    return 1 if stats["failed_modules"] else 0


def run_sign(tools_dir: Path, signing_key: Optional[str], manifest_name: str = DEFAULT_MANIFEST) -> int:
    """Generate a SHA-256 manifest (optionally HMAC-signed) for a local dir."""
    if not tools_dir.exists():
        print(json.dumps({"error": f"directory not found: {tools_dir}"}))
        return 2
    tools = {
        p.name: sha256_file(p)
        for p in sorted(tools_dir.glob("*.py"))
        if p.name != "__init__.py"
    }
    manifest = {"algorithm": "sha256", "tools": tools}
    if signing_key:
        manifest["signature"] = manifest_signature(tools, signing_key)
    out = tools_dir / manifest_name
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "written", "manifest": str(out), "tools": len(tools),
                      "signed": bool(signing_key)}))
    return 0
