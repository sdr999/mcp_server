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
import importlib
import json
import logging
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Tuple

from . import dependency_risk as risk
from .tool_loader import ToolLoader, prepare_with_timeout

log = logging.getLogger("MCP_logger")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
DEFAULT_INSTALL_TIMEOUT = 120.0
DEFAULT_IMPORT_TIMEOUT = 30.0


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
    # A freshly created site-packages entry may not be visible to import
    # machinery that already cached the directory listing. Invalidate the
    # finder caches so the just-installed distribution is importable in-process.
    importlib.invalidate_caches()
    return True, ""


class OnboardingManager:
    """Owns the pending-submission store and drives the risk-gated onboarding
    flow described in the module docstring."""

    def __init__(self, tools_dir: Path, pending_dir: Path, loader: ToolLoader, *,
                 allowlist=None, denylist=None, network_check: bool = True,
                 network_timeout: float = 3.0, autoinstall: bool = True,
                 install_timeout: float = DEFAULT_INSTALL_TIMEOUT,
                 import_timeout: float = DEFAULT_IMPORT_TIMEOUT, enabled: bool = True,
                 loader_lock: Optional["asyncio.Lock"] = None):
        self.tools_dir = tools_dir
        self.pending_dir = pending_dir
        self.loader = loader
        # Serializes tool imports/registry mutations against the reload drain
        # (and other onboards): both run on the loop but the actual import runs
        # in an executor thread, so two concurrent imports of a module would
        # race importlib. A shared lock makes them mutually exclusive. Tests
        # that construct a manager without a drain get their own private lock.
        self.loader_lock = loader_lock or asyncio.Lock()
        self.allowlist = allowlist if allowlist is not None else {risk.canonical_name(n) for n in risk.DEFAULT_ALLOWLIST}
        self.denylist = denylist if denylist is not None else {risk.canonical_name(n) for n in risk.DEFAULT_DENYLIST}
        self.network_check = network_check
        self.network_timeout = network_timeout
        self.autoinstall = autoinstall
        self.install_timeout = install_timeout
        self.import_timeout = import_timeout
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
        # Canonical names so a declared ``python_dotenv`` and an inferred
        # ``import dotenv`` -> ``python-dotenv`` are recognized as one package
        # and not installed twice.
        covered = {risk.spec_name(s) for s in explicit}
        for mod in risk.detect_missing_imports(source):
            resolved = risk.resolve_import_name(mod)
            if risk.canonical_name(resolved) not in covered:
                explicit.append(resolved)
                covered.add(risk.canonical_name(resolved))
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

        registered, failure = await self._write_live(name, source)
        if failure or not registered:
            # Truthful outcome: the source parsed and its deps installed, but the
            # module raised on import, was refused (e.g. signed-tools), or exposed
            # no tool. Report it as pending rather than a false "onboarded".
            record["status"] = "pending"
            record["hold_reason"] = f"tool failed to load: {failure or 'source registered no tools'}"
            record["installed"] = install_specs
            self._write_pending(name, source, record)
            log.error("Tool %r held pending: %s", name, record["hold_reason"])
            return record

        record["installed"] = install_specs
        record["registered_tools"] = registered
        log.info("Tool %r onboarded (%d dependency install(s), tools: %s)",
                 name, len(install_specs), registered)
        return record

    async def _write_live(self, name: str, source: str) -> Tuple[List[str], Optional[str]]:
        """Write the tool into the live tools dir and load it, importing OFF the
        serving loop bounded by ``import_timeout`` (a hostile module's top-level
        code cannot freeze the server). Returns (registered tool names, failure
        reason); a brand-new submission that fails to load is rolled back so no
        broken file lingers."""
        path = self.tools_dir / f"{name}.py"
        pre_existed = path.exists()
        path.write_text(source, encoding="utf-8")

        module_name = self.loader.module_name_for_path(path)
        if not module_name:
            return [], "internal error: tool path is not inside the tools directory"

        async with self.loader_lock:  # mutual exclusion with the reload drain
            self.loader.invalidate(module_name)  # force a real re-import even on overwrite
            plan = await prepare_with_timeout(self.loader, path, self.import_timeout)
            if plan is None:
                outcome = ([], f"import did not complete within {self.import_timeout}s")
            else:
                self.loader.commit(plan)  # on-loop, fast
                outcome = self.loader.module_outcome(module_name)

        registered, failure = outcome
        if (failure or not registered) and not pre_existed:
            # Don't leave a broken, newly created file behind. (Overwrite of an
            # existing tool is left intact -- conflict handling is a later item.)
            self.loader.unload_path(path)
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        return registered, failure

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

        registered, failure = await self._write_live(name, source)
        if failure or not registered:
            # Deps installed but the tool still won't load: keep it pending with
            # the real reason rather than clearing it and claiming success.
            pending["status"] = "pending"
            pending["hold_reason"] = f"tool failed to load after approval: {failure or 'source registered no tools'}"
            pending["installed"] = install_specs
            self._write_pending(name, source, pending)
            raise RuntimeError(pending["hold_reason"])

        self._clear_pending(name)
        pending["status"] = "onboarded"
        pending["installed"] = install_specs
        pending["registered_tools"] = registered
        pending.pop("hold_reason", None)
        log.warning("Tool %r approved by admin override and onboarded (tools: %s)", name, registered)
        return pending

    def reject(self, name: str) -> bool:
        if self.get_pending(name) is None:
            return False
        self._clear_pending(name)
        log.info("Pending tool %r rejected and discarded", name)
        return True
