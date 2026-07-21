"""Tool onboarding: submit a tool module + its dependencies over HTTP instead
of dropping a file on disk (the replacement for the removed Azure sync path).

Flow
----
1. Validate the tool name (safe module-stem only) and that the source at
   least parses (``ast.parse``) -- never executed until the loader imports it.
2. Detect imports the source needs (stdlib/already-installed ones are
   ignored) and merge them with any explicitly declared ``requirements``,
   tagging each as declared / inferred (known import->dist mapping) / guessed
   (import name used verbatim).
3. Risk-assess every direct dependency (``dependency_risk.assess_requirement``).
4. Before installing, resolve the full transitive **closure** with
   ``pip install --dry-run --report`` and risk-assess every *transitive*
   package too, so a benign top-level package cannot smuggle in a malicious
   dependency. (Network-gated; skipped when ``network_check`` is off.)
5. Decide:
   * Any dependency (direct or transitive) scores "high" or is malformed, a
     guessed dependency name isn't allowlisted, or auto-install is disabled
     while new installs are needed
     -> hold as **pending**: nothing is installed, nothing is loaded, and the
        submission + full risk report is written to the pending directory for
        an admin to inspect via ``GET /admin/tools/pending``.
   * Otherwise -> install the (low/medium risk) missing dependencies, write
     the tool into the live tools directory, and hot-load it immediately.
6. An admin can force either outcome later: ``approve`` installs+loads a
   pending submission regardless of its risk score; ``reject`` discards it.

This module has no hard dependency beyond the stdlib + what ``tool_loader``
already needs; installs run pip in a subprocess (never a shell), and only
after every spec has been validated by ``dependency_risk`` regex matching.
Pending submissions are stored with a ``.py.pending`` suffix so held (possibly
untrusted) code is not importable via ``sys.path``.
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

from metrics import METRICS
from . import dependency_risk as risk
from .tool_loader import ToolLoader, prepare_with_timeout

log = logging.getLogger("MCP_logger")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
DEFAULT_INSTALL_TIMEOUT = 120.0
DEFAULT_IMPORT_TIMEOUT = 30.0
MAX_SOURCE_BYTES = 1 * 1024 * 1024   # 1 MiB
MAX_REQUIREMENTS = 50


class OnboardingConflict(Exception):
    """Raised when onboarding a name that already exists (live or pending)
    without ``overwrite=True``. The route maps this to HTTP 409."""


def _only_binary_args(only_binary: bool) -> List[str]:
    # --only-binary :all: forbids source distributions, so pip never runs a
    # package's setup.py (arbitrary code) during install/resolution.
    return ["--only-binary", ":all:"] if only_binary else []


async def _pip_install(specs: List[str], timeout: float, only_binary: bool = False):
    """Install already-validated specs in a subprocess. Never invoked with a
    spec that hasn't passed dependency_risk's strict regex."""
    if not specs:
        return True, ""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install",
        "--no-input", "--disable-pip-version-check", "--quiet",
        *_only_binary_args(only_binary), *specs,
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


async def _pip_resolve_closure(specs: List[str], timeout: float, only_binary: bool = False):
    """Resolve (but do not install) the full dependency closure of ``specs``
    via ``pip install --dry-run --report -``. Returns ``(ok, packages | error)``
    where each package is ``{"name", "version", "requested"}`` (``requested``
    is True for the specs asked for, False for transitively-pulled deps).

    Same subprocess/no-shell discipline as ``_pip_install``; specs must already
    have passed the strict grammar."""
    if not specs:
        return True, []
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "--dry-run", "--report", "-",
        "--no-input", "--disable-pip-version-check", "--quiet",
        *_only_binary_args(only_binary), *specs,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return False, f"dependency resolution exceeded {timeout}s and was killed"
    if proc.returncode != 0:
        return False, (err.decode(errors="replace").strip()[:2000] or "pip could not resolve the dependencies")
    try:
        report = json.loads(out.decode() or "{}")
    except ValueError as exc:
        return False, f"could not parse pip dependency report: {exc}"
    packages = []
    for item in report.get("install", []):
        meta = item.get("metadata", {}) or {}
        packages.append({
            "name": meta.get("name", ""),
            "version": meta.get("version", ""),
            "requested": bool(item.get("requested")),
        })
    return True, packages


class OnboardingManager:
    """Owns the pending-submission store and drives the risk-gated onboarding
    flow described in the module docstring."""

    def __init__(self, tools_dir: Path, pending_dir: Path, loader: ToolLoader, *,
                 allowlist=None, denylist=None, network_check: bool = True,
                 network_timeout: float = 3.0, autoinstall: bool = True,
                 install_timeout: float = DEFAULT_INSTALL_TIMEOUT,
                 import_timeout: float = DEFAULT_IMPORT_TIMEOUT, enabled: bool = True,
                 only_binary: bool = False, audit_log_path: Optional[Path] = None,
                 loader_lock: Optional["asyncio.Lock"] = None):
        self.tools_dir = tools_dir
        self.pending_dir = pending_dir
        self.loader = loader
        self.only_binary = only_binary
        self.audit_log_path = audit_log_path
        # Serializes tool imports/registry mutations against the reload drain
        # (and other onboards): both run on the loop but the actual import runs
        # in an executor thread, so two concurrent imports of a module would
        # race importlib. A shared lock makes them mutually exclusive. Tests
        # that construct a manager without a drain get their own private lock.
        self.loader_lock = loader_lock or asyncio.Lock()
        # Serializes pip subprocesses (resolve + install) so two concurrent
        # onboards don't run pip against the same environment simultaneously.
        self._install_lock = asyncio.Lock()
        self.allowlist = allowlist if allowlist is not None else {risk.canonical_name(n) for n in risk.DEFAULT_ALLOWLIST}
        self.denylist = denylist if denylist is not None else {risk.canonical_name(n) for n in risk.DEFAULT_DENYLIST}
        self.network_check = network_check
        self.network_timeout = network_timeout
        self.autoinstall = autoinstall
        self.install_timeout = install_timeout
        self.import_timeout = import_timeout
        self.enabled = enabled
        self.pending_dir.mkdir(parents=True, exist_ok=True)

    # -- audit trail ----------------------------------------------------
    def _audit(self, action: str, name: str, result: str, detail: str = "") -> None:
        """Append one JSON line to the audit log for an onboarding action.
        Best-effort: a write failure never breaks onboarding. Note: the server
        has a single shared admin token, so there is no per-actor identity to
        record here -- the audit answers "what happened", not "who did it"."""
        if not self.audit_log_path:
            return
        entry = {"ts": time.time(), "action": action, "name": name,
                 "result": result, "detail": detail}
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:
            log.error("Could not write onboarding audit entry: %s", exc)

    # -- pending store --------------------------------------------------
    def _pending_paths(self, name: str):
        # ``.py.pending`` (not ``.py``) so held, unreviewed code sitting under a
        # directory that may be on sys.path is not importable as a module.
        return self.pending_dir / f"{name}.py.pending", self.pending_dir / f"{name}.json"

    def pending_count(self) -> int:
        return sum(1 for _ in self.pending_dir.glob("*.json"))

    def list_pending(self) -> List[dict]:
        out = []
        for meta_path in sorted(self.pending_dir.glob("*.json")):
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception as exc:
                log.error("Could not read pending record %s: %s", meta_path, exc)
        return out

    def get_pending(self, name: str) -> Optional[dict]:
        if not _NAME_RE.match(name or ""):
            return None
        _src, meta_path = self._pending_paths(name)
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_pending_detail(self, name: str) -> Optional[dict]:
        """Full pending record including the held source, for admin review."""
        record = self.get_pending(name)
        if record is None:
            return None
        src_path, _meta = self._pending_paths(name)
        source = ""
        with contextlib.suppress(Exception):
            source = src_path.read_text(encoding="utf-8")
        return {**record, "source": source}

    def _write_pending(self, name: str, source: str, record: dict) -> None:
        src_path, meta_path = self._pending_paths(name)
        src_path.write_text(source, encoding="utf-8")
        meta_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    def _clear_pending(self, name: str) -> None:
        src_path, meta_path = self._pending_paths(name)
        src_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    # -- risk assessment --------------------------------------------------
    def _assess_one(self, spec: str, origin: str) -> risk.RiskReport:
        return risk.assess_requirement(
            spec, allowlist=self.allowlist, denylist=self.denylist,
            network_check=self.network_check, network_timeout=self.network_timeout,
            origin=origin,
        )

    def _assess_specs(self, specs_with_origin: List[Tuple[str, str]]) -> List[risk.RiskReport]:
        return [self._assess_one(spec, origin) for spec, origin in specs_with_origin]

    def _build_specs(self, source: str, requirements: List[str]) -> List[Tuple[str, str]]:
        """Return [(spec, origin)] merging declared requirements with imports
        detected in the source. Canonical names so a declared ``python_dotenv``
        and an inferred ``import dotenv`` -> ``python-dotenv`` are recognized as
        one package and not installed twice."""
        out: List[Tuple[str, str]] = [(s, "declared") for s in (requirements or [])]
        covered = {risk.spec_name(s) for s in (requirements or [])}
        for mod in risk.detect_missing_imports(source):
            package, origin = risk.classify_import(mod)
            if risk.canonical_name(package) not in covered:
                out.append((package, origin))
                covered.add(risk.canonical_name(package))
        return out

    # -- onboarding ---------------------------------------------------------
    def _hold(self, name: str, source: str, record: dict, reason: str) -> dict:
        """Persist a submission as pending with ``reason`` and record it."""
        record["status"] = "pending"
        record["hold_reason"] = reason
        self._write_pending(name, source, record)
        METRICS.inc("mcp_tool_onboards_total", result="pending")
        self._audit("onboard", name, "pending", reason)
        log.warning("Tool %r held pending: %s", name, reason)
        return record

    async def onboard(self, name: str, source: str, requirements: Optional[List[str]] = None,
                       *, overwrite: bool = False) -> dict:
        if not self.enabled:
            raise ValueError("tool onboarding is disabled (MCP_TOOL_ONBOARD_ENABLED=false)")
        if self.loader.verifier is not None and getattr(self.loader.verifier, "require", False):
            # Signed-tools mode only loads files listed in a trusted manifest;
            # an onboarded file wouldn't be, so it could never load. Reject up
            # front instead of silently holding everything pending.
            raise ValueError("tool onboarding is unavailable while signed tools are required "
                             "(MCP_REQUIRE_SIGNED_TOOLS=true); publish via the signed manifest instead")
        if not _NAME_RE.match(name or ""):
            raise ValueError("invalid tool name: must match ^[A-Za-z_][A-Za-z0-9_]{0,63}$")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise ValueError(f"tool source has a syntax error: {exc}")

        if not overwrite:
            if (self.tools_dir / f"{name}.py").exists():
                raise OnboardingConflict(f"a live tool named {name!r} already exists; "
                                         "pass overwrite=true to replace it")
            if self.get_pending(name) is not None:
                raise OnboardingConflict(f"a pending submission named {name!r} already exists; "
                                         "pass overwrite=true to replace it")

        specs_with_origin = self._build_specs(source, requirements or [])
        reports = self._assess_specs(specs_with_origin)
        needs_install = [r for r in reports if not r.already_installed]

        # A "guessed" dependency name (inferred from an import with no known
        # import->distribution mapping) may not be the real PyPI package;
        # unless it's allowlisted, require an admin to confirm it.
        guessed = [r for r in reports
                   if r.origin == "guessed" and risk.canonical_name(r.name) not in self.allowlist]

        record = {
            "name": name,
            "status": "onboarded",
            "requested_at": time.time(),
            "requirements": [spec for spec, _ in specs_with_origin],
            "risk_reports": [asdict(r) for r in reports],
        }

        if not self.autoinstall and needs_install:
            return self._hold(name, source, record,
                              "auto-install of new dependencies is disabled (MCP_TOOL_AUTOINSTALL_DEPS=false)")
        if any(not r.valid or r.level == "high" for r in reports):
            return self._hold(name, source, record, "one or more dependencies were assessed as high risk")
        if guessed:
            return self._hold(name, source, record,
                              "a dependency name was guessed from an import and could not be verified "
                              f"({', '.join(sorted(r.name for r in guessed))}); "
                              "declare it explicitly in requirements or add it to the allowlist")

        install_specs = [r.spec for r in needs_install if r.valid]

        # Resolve + risk-assess the transitive closure before installing, so a
        # low-risk top-level package can't pull in a high-risk dependency. Only
        # when network checks are on (offline resolution isn't meaningful).
        if self.network_check and install_specs:
            async with self._install_lock:
                ok, closure = await _pip_resolve_closure(install_specs, self.install_timeout, self.only_binary)
            if not ok:
                return self._hold(name, source, record, f"could not resolve dependency closure: {closure}")
            transitive = [self._assess_one(f"{p['name']}=={p['version']}", "transitive")
                          for p in closure if not p["requested"] and p["name"]]
            record["closure_reports"] = [asdict(r) for r in transitive]
            risky = [r for r in transitive if not r.valid or r.level == "high"]
            if risky:
                return self._hold(name, source, record,
                                  "a transitive dependency was assessed as high risk: "
                                  + ", ".join(sorted(r.name for r in risky)))

        async with self._install_lock:
            ok, err = await _pip_install(install_specs, self.install_timeout, self.only_binary)
        if not ok:
            record["installed"] = []
            return self._hold(name, source, record, f"dependency install failed: {err}")

        registered, failure = await self._write_live(name, source)
        if failure or not registered:
            # Truthful outcome: the source parsed and its deps installed, but the
            # module raised on import, was refused, or exposed no tool. Report it
            # as pending rather than a false "onboarded".
            record["installed"] = install_specs
            return self._hold(name, source, record,
                              f"tool failed to load: {failure or 'source registered no tools'}")

        record["installed"] = install_specs
        record["registered_tools"] = registered
        METRICS.inc("mcp_tool_onboards_total", result="onboarded")
        self._audit("onboard", name, "onboarded", f"tools={registered}")
        log.info("Tool %r onboarded (%d dependency install(s), tools: %s)",
                 name, len(install_specs), registered)
        return record

    async def _write_live(self, name: str, source: str) -> Tuple[List[str], Optional[str]]:
        """Write the tool into the live tools dir and load it, importing OFF the
        serving loop bounded by ``import_timeout`` (a hostile module's top-level
        code cannot freeze the server). Returns (registered tool names, failure
        reason). A brand-new submission that fails to load is rolled back; an
        overwrite that fails to load is restored to its previous version so a
        working tool is never clobbered by a bad update."""
        path = self.tools_dir / f"{name}.py"
        old_content = path.read_text(encoding="utf-8") if path.exists() else None
        module_name = self.loader.module_name_for_path(path)
        if not module_name:
            return [], "internal error: tool path is not inside the tools directory"

        async with self.loader_lock:  # mutual exclusion with the reload drain
            path.write_text(source, encoding="utf-8")
            registered, failure = await self._load_locked(module_name, path)
            if failure or not registered:
                if old_content is not None:
                    # Restore & reload the previously-working version.
                    path.write_text(old_content, encoding="utf-8")
                    await self._load_locked(module_name, path)
                else:
                    self.loader.unload_path(path)
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
        return registered, failure

    async def _load_locked(self, module_name: str, path: Path) -> Tuple[List[str], Optional[str]]:
        """Import (off-loop, timeout-bounded) + register one tool file. MUST be
        called with ``self.loader_lock`` held."""
        self.loader.invalidate(module_name)  # force a real re-import even on overwrite
        plan = await prepare_with_timeout(self.loader, path, self.import_timeout)
        if plan is None:
            return [], f"import did not complete within {self.import_timeout}s"
        self.loader.commit(plan)  # on-loop, fast
        return self.loader.module_outcome(module_name)

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
        # Admin override: install regardless of risk, but still serialize pip.
        async with self._install_lock:
            ok, err = await _pip_install(install_specs, self.install_timeout, self.only_binary)
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
        METRICS.inc("mcp_tool_onboards_total", result="approved")
        self._audit("approve", name, "onboarded", f"tools={registered}")
        log.warning("Tool %r approved by admin override and onboarded (tools: %s)", name, registered)
        return pending

    def reject(self, name: str) -> bool:
        if self.get_pending(name) is None:
            return False
        self._clear_pending(name)
        METRICS.inc("mcp_tool_onboards_total", result="rejected")
        self._audit("reject", name, "rejected")
        log.info("Pending tool %r rejected and discarded", name)
        return True
