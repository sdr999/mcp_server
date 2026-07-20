"""Signed tools (supply-chain hardening).

With ``MCP_REQUIRE_SIGNED_TOOLS=true``, a tool file is imported only if it is
listed in a trusted manifest with a matching SHA-256. If ``MCP_TOOL_SIGNING_KEY``
is set, the manifest's own HMAC signature must verify first (so the manifest
itself can't be tampered with).

Manifest format (``tools.manifest.json`` inside the tools dir)::

    {
      "algorithm": "sha256",
      "tools": { "weather.py": "<sha256hex>" },
      "signature": "<hmac-sha256 of the sorted tools map>"
    }
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

log = logging.getLogger("MCP_logger")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_signature(tools: dict, signing_key: str) -> str:
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()


class ToolVerifier:
    """Verifies each tool file against a SHA-256 manifest before it is imported.

    When ``require`` is True, a file is only importable if it is present in a
    trusted manifest with a matching hash. When ``signing_key`` is set, the
    manifest's own HMAC signature must verify first (tamper protection).
    """

    def __init__(self, tools_dir: Path, manifest_name: str, signing_key: Optional[str], require: bool):
        self.require = require
        self.entries: Dict[str, str] = {}
        self.trusted = False
        manifest_path = tools_dir / manifest_name
        if not manifest_path.exists():
            if require:
                log.error("Signed tools required but manifest %s is missing", manifest_path)
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            tools = data.get("tools", {})
            if signing_key:
                if not hmac.compare_digest(manifest_signature(tools, signing_key), data.get("signature", "")):
                    log.error("Tool manifest signature is invalid; refusing to trust it")
                    return
            self.entries = tools
            self.trusted = True
        except Exception as exc:
            log.error("Could not read tool manifest %s: %s", manifest_path, exc)

    def verify(self, file_path: Path) -> Tuple[bool, str]:
        if not self.require:
            return True, ""
        if not self.trusted:
            return False, "no trusted manifest"
        want = self.entries.get(file_path.name)
        if not want:
            return False, "not listed in manifest"
        if not hmac.compare_digest(sha256_file(file_path), want):
            return False, "hash mismatch"
        return True, ""
