"""Tool onboarding: submit a tool module + its dependencies over HTTP instead
of dropping a file on disk (the replacement for the removed Azure sync path).

Flow
----
1. Validate the tool name (safe module-stem only) and that the source at
   least parses (``ast.parse``) -- never executed until the loader imports it.
2. Detect imports the source needs (stdlib/already-installed ones are
   ignored) and merge them with any explicitly declared ``requirements``.
3. Risk-assess every dependency (``dependency_risk.assess_requirement``).
4. Decide:
   * Any requirement scores "high", any requirement/spec is malformed, or
     auto-install is disabled while new installs are needed
     -> hold as **pending**: nothing is installed, nothing is loaded, and the
        submission + full risk report is written to the pending directory for
        an admin to inspect via ``GET /admin/tools/pending``.
   * Otherwise -> install the (low/medium risk) missing dependencies, write
     the tool into the live tools directory, and hot-load it immediately.
5. An admin can force either outcome later: ``approve`` installs+loads a
   pending submission regardless of its risk score; ``reject`` discards it.

This module has no hard dependency beyond the stdlib + what ``tool_loader``
already needs; installs run pip in a subprocess (never a shell), and only
after every spec has been validated by ``dependency_risk`` regex matching.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from . import dependency_risk as risk
from .tool_loader import ToolLoader

log = logging.getLogger("MCP_logger")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
DEFAULT_INSTALL_TIMEOUT = 120.0


async def _pip_install(specs: List[str], timeout: float):
    """Install already-validated specs in a subprocess. Never invoked with a
    spec that hasn't passed dependency_risk's strict regex."""
    if not specs:
        return True, ""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install",
        "--no-input", "--disable-pip-version-check", "--quiet", *specs,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return False, f"pip install exceeded {timeout}s and was killed"
    if proc.returncode != 0:
        return False, err.decode(errors="replace")[:2000]
    return True, ""


class OnboardingManager:
    """Owns the pending-submission store and drives the risk-gated onboarding
    flow described in the module docstring."""

    def __init__(self, tools_dir: Path, pending_dir: Path, loader: ToolLoader, *,
                 allowlist=None, denylist=None, network_check: bool = True,
                 network_timeout: float = 3.0, autoinstall: bool = True,
                 install_timeout: float = DEFAULT_INSTALL_TIMEOUT, enabled: bool = True):
        self.tools_dir = tools_dir
        self.pending_dir = pending_dir
        self.loader = loader
        self.allowlist = allowlist if allowlist is not None else {n.lower() for n in risk.DEFAULT_ALLOWLIST}
        self.denylist = denylist if denylist is not None else {n.lower() for n in risk.DEFAULT_DENYLIST}
        self.network_check = network_check
        self.network_timeout = network_timeout
        self.autoinstall = autoinstall
        self.install_timeout = install_timeout
        self.enabled = enabled
        self.pending_dir.mkdir(parents=True, exist_ok=True)

    # -- pending store --------------------------------------------------
    def _pending_paths(self, name: str):
        return self.pending_dir / f"{name}.py", self.pending_dir / f"{name}.json"

    def list_pending(self) -> List[dict]:
        out = []
        for meta_path in sorted(self.pending_dir.glob("*.json")):
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception as exc:
                log.error("Could not read pending record %s: %s", meta_path, exc)
        return out

    def get_pending(self, name: str) -> Optional[dict]:
        _src, meta_path = self._pending_paths(name)
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_pending(self, name: str, source: str, record: dict) -> None:
        src_path, meta_path = self._pending_paths(name)
        src_path.write_text(source, encoding="utf-8")
        meta_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    def _clear_pending(self, name: str) -> None:
        src_path, meta_path = self._pending_paths(name)
        src_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    # -- risk assessment --------------------------------------------------
    def _assess_specs(self, specs: List[str]) -> List[risk.RiskReport]:
        return [
            risk.assess_requirement(
                s, allowlist=self.allowlist, denylist=self.denylist,
                network_check=self.network_check, network_timeout=self.network_timeout,
            )
            for s in specs
        ]

    def _build_specs(self, source: str, requirements: List[str]) -> List[str]:
        explicit = list(requirements or [])
        covered = {risk.spec_name(s) for s in explicit}
        for mod in risk.detect_missing_imports(source):
            resolved = risk.resolve_import_name(mod)
            if resolved.lower() not in covered:
                explicit.append(resolved)
                covered.add(resolved.lower())
        return explicit

    # -- onboarding ---------------------------------------------------------
    async def onboard(self, name: str, source: str, requirements: Optional[List[str]] = None) -> dict:
        if not self.enabled:
            raise ValueError("tool onboarding is disabled (MCP_TOOL_ONBOARD_ENABLED=false)")
        if not _NAME_RE.match(name or ""):
            raise ValueError("invalid tool name: must match ^[A-Za-z_][A-Za-z0-9_]{0,63}$")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise ValueError(f"tool source has a syntax error: {exc}")

        specs = self._build_specs(source, requirements or [])
        reports = self._assess_specs(specs)
        needs_install = [r for r in reports if not r.already_installed]

        hold_reason = None
        if not self.autoinstall and needs_install:
            hold_reason = "auto-install of new dependencies is disabled (MCP_TOOL_AUTOINSTALL_DEPS=false)"
        elif any(not r.valid or r.level == "high" for r in reports):
            hold_reason = "one or more dependencies were assessed as high risk"

        record = {
            "name": name,
            "status": "pending" if hold_reason else "onboarded",
            "requested_at": time.time(),
            "requirements": specs,
            "risk_reports": [asdict(r) for r in reports],
        }

        if hold_reason:
            record["hold_reason"] = hold_reason
            self._write_pending(name, source, record)
            log.warning("Tool %r held pending: %s", name, hold_reason)
            return record

        install_specs = [r.spec for r in needs_install if r.valid]
        ok, err = await _pip_install(install_specs, self.install_timeout)
        if not ok:
            record["status"] = "pending"
            record["hold_reason"] = f"dependency install failed: {err}"
            self._write_pending(name, source, record)
            log.error("Tool %r held pending: dependency install failed: %s", name, err)
            return record

        self._write_live(name, source)
        record["installed"] = install_specs
        log.info("Tool %r onboarded (%d dependency install(s))", name, len(install_specs))
        return record

    def _write_live(self, name: str, source: str) -> None:
        path = self.tools_dir / f"{name}.py"
        path.write_text(source, encoding="utf-8")
        self.loader.load_path(path)

    async def approve(self, name: str) -> dict:
        """Force-install (if needed) and load a pending submission, overriding
        its risk assessment. An explicit admin action, not automatic."""
        pending = self.get_pending(name)
        if pending is None:
            raise KeyError(name)
        src_path, _meta_path = self._pending_paths(name)
        source = src_path.read_text(encoding="utf-8")

        install_specs = [r["spec"] for r in pending.get("risk_reports", [])
                          if r.get("valid", True) and not r.get("already_installed")]
        ok, err = await _pip_install(install_specs, self.install_timeout)
        if not ok:
            pending["hold_reason"] = f"admin-approved install failed: {err}"
            self._write_pending(name, source, pending)
            raise RuntimeError(f"dependency install failed: {err}")

        self._write_live(name, source)
        self._clear_pending(name)
        pending["status"] = "onboarded"
        pending["installed"] = install_specs
        pending.pop("hold_reason", None)
        log.warning("Tool %r approved by admin override and onboarded", name)
        return pending

    def reject(self, name: str) -> bool:
        if self.get_pending(name) is None:
            return False
        self._clear_pending(name)
        log.info("Pending tool %r rejected and discarded", name)
        return True
