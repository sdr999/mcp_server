"""Fault-isolated tool discovery, registration, and (optional) sandboxed execution.

Split model for concurrency + responsiveness:
  * ``prepare()`` does the slow work (verify, import, resolve) and may run in an
    executor thread -- it does not mutate the FastMCP registry.
  * ``commit()`` applies the plan (add_tool/remove_tool) and MUST run on the
    serving event loop.
``load_path()`` runs both inline (used by tests, --validate, and admin reload of
a single tool, all of which are already on-loop or off-server).
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib
import inspect
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastmcp.tools import FunctionTool

from metrics import METRICS
from tools_sdk import TOOL_MARKER
from .signing import ToolVerifier

log = logging.getLogger("MCP_logger")

DEFAULT_SANDBOX_TIMEOUT = 30


class _CollectingRegistrar:
    """Passed to a module's ``register()`` hook; collects tools without
    registering them, so the loader applies duplicate-name policy uniformly."""

    def __init__(self):
        self.collected: List[Tuple[str, FunctionTool]] = []

    def add_tool(self, tool_or_fn):
        try:
            tool_obj = (
                tool_or_fn
                if isinstance(tool_or_fn, FunctionTool)
                else FunctionTool.from_function(tool_or_fn)
            )
        except Exception as exc:  # one bad tool must not abort register()
            log.error("register(): could not build tool from %r: %s", tool_or_fn, exc)
            return None
        self.collected.append((tool_obj.name, tool_obj))
        return tool_obj


@dataclass
class _LoadPlan:
    """Result of importing/resolving a tool file OFF the event loop. Applying it
    (``commit``) is a fast, on-loop registry mutation."""
    module_name: str
    mtime: Optional[float]
    resolved: List[Tuple[str, "FunctionTool"]]
    failure: Optional[str] = None  # "deleted" | "unsigned: ..." | "import error: ..." etc.


async def _run_sandboxed(runner: str, module_name: str, qualname: str, args: dict,
                          syspath: List[str], timeout: float, limits: dict):
    """Execute one tool call in a separate process, bounded by a timeout. Raises
    on failure/timeout so FastMCP returns an error result to the client."""
    request = json.dumps({
        "syspath": syspath, "module": module_name, "qualname": qualname,
        "args": args, "limits": limits or {},
    }).encode()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, runner,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(request), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        raise RuntimeError(f"tool execution exceeded {timeout}s and was killed")
    if not out:
        raise RuntimeError(f"sandboxed tool produced no result: {err.decode(errors='replace')[:200]}")
    payload = json.loads(out.decode().strip())
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", "sandboxed tool failed"))
    return payload["result"]


class ToolLoader:
    """Resolves tool modules and registers them on the given FastMCP instance."""

    def __init__(self, mcp, tools_dir: Path, verifier: Optional[ToolVerifier] = None,
                 *, wrap_execution: bool = False, sandbox: bool = False,
                 sandbox_timeout: float = DEFAULT_SANDBOX_TIMEOUT, sandbox_limits: Optional[dict] = None,
                 src_dir: Optional[Path] = None):
        self.mcp = mcp
        self.tools_dir = tools_dir
        self.verifier = verifier
        self.wrap_execution = wrap_execution or sandbox  # metrics and/or sandbox
        self.sandbox = sandbox
        self.sandbox_timeout = sandbox_timeout
        self.sandbox_limits = sandbox_limits or {}
        self.src_dir = src_dir or Path(__file__).resolve().parent.parent
        self._module_tools: Dict[str, List[str]] = {}   # module -> [tool names]
        self._name_owner: Dict[str, str] = {}           # tool name -> owning module
        self._mtime: Dict[str, float] = {}              # module -> last-loaded mtime
        self._tool_info: Dict[str, dict] = {}           # tool name -> catalog metadata
        self._failures: Dict[str, str] = {}             # module -> failure reason
        self._disabled: Dict[str, str] = {}             # disabled tool name -> owning module
        self._changed = False

    # -- path/module helpers ------------------------------------------------
    def module_name_for_path(self, file_path: Path) -> Optional[str]:
        try:
            file_path = file_path.resolve()
            root = self.tools_dir.resolve()
            if not file_path.is_relative_to(root):
                return None
            if file_path.suffix != ".py" or file_path.name == "__init__.py":
                return None
            return f"{self.tools_dir.name}.{file_path.stem}"
        except Exception:
            return None

    def file_for_module(self, module_name: str) -> Path:
        return self.tools_dir / (module_name.split(".")[-1] + ".py")

    def module_for_tool(self, name: str) -> Optional[str]:
        return self._name_owner.get(name) or self._disabled.get(name)

    def _import(self, module_name: str):
        sys.modules.pop(module_name, None)  # force a fresh import on reload
        return importlib.import_module(module_name)

    # -- resolution ---------------------------------------------------------
    def _make_wrapper(self, original, tool_name: str):
        """Wrap a tool callable to record metrics and (optionally) execute it in a
        subprocess sandbox. functools.wraps preserves the signature so FastMCP
        still builds the correct input schema."""
        module_name = getattr(original, "__module__", None)
        qualname = getattr(original, "__qualname__", getattr(original, "__name__", ""))
        sandbox = self.sandbox
        timeout = self.sandbox_timeout
        limits = self.sandbox_limits
        syspath = [str(self.tools_dir.resolve().parent), str(self.src_dir)]
        runner = str(self.src_dir / "tool_runner.py")

        @functools.wraps(original)
        async def wrapper(**kwargs):
            start = time.perf_counter()
            METRICS.inc("mcp_tool_calls_total", tool=tool_name)
            try:
                if sandbox:
                    return await _run_sandboxed(runner, module_name, qualname, kwargs, syspath, timeout, limits)
                result = original(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception:
                METRICS.inc("mcp_tool_errors_total", tool=tool_name)
                raise
            finally:
                METRICS.observe("mcp_tool_duration_seconds", time.perf_counter() - start, tool=tool_name)

        return wrapper

    def _to_tool(self, obj, explicit_name: Optional[str]) -> Tuple[str, FunctionTool]:
        if isinstance(obj, FunctionTool):
            return obj.name, obj  # pre-built tools pass through unwrapped
        meta = getattr(obj, TOOL_MARKER, None) or {}
        name = explicit_name or meta.get("name") or getattr(obj, "__name__", None)
        fn = self._make_wrapper(obj, name) if (self.wrap_execution and name) else obj
        tool_obj = FunctionTool.from_function(
            fn, name=name, description=meta.get("description"), tags=meta.get("tags")
        )
        return name, tool_obj

    def _resolve_tools(self, module, module_name: str) -> List[Tuple[str, FunctionTool]]:
        """Return (name, tool) pairs using the first matching mechanism.
        A single malformed tool is logged and skipped, never aborting the module."""
        results: List[Tuple[str, FunctionTool]] = []

        def _safe_add(obj, explicit_name):
            try:
                results.append(self._to_tool(obj, explicit_name))
            except Exception as exc:
                ident = explicit_name or getattr(obj, "__name__", repr(obj))
                log.error("Skipping invalid tool %r in %s: %s", ident, module_name, exc)

        register = getattr(module, "register", None)
        if callable(register):
            registrar = _CollectingRegistrar()
            try:
                register(registrar)
            except Exception as exc:
                log.error("register() raised in %s: %s", module_name, exc)
            if registrar.collected:
                return registrar.collected

        exported = getattr(module, "TOOLS", None)
        if exported:
            items = exported.items() if isinstance(exported, dict) else [(None, o) for o in exported]
            for explicit_name, obj in items:
                if callable(obj) or isinstance(obj, FunctionTool):
                    _safe_add(obj, explicit_name)
                else:
                    log.error("TOOLS entry %r in %s is not callable; skipped", explicit_name, module_name)
            if results:
                return results

        decorated = [v for v in vars(module).values() if callable(v) and hasattr(v, TOOL_MARKER)]
        if decorated:
            for fn in decorated:
                _safe_add(fn, None)
            if results:
                return results

        stem = module_name.split(".")[-1]
        fn = getattr(module, stem, None)
        if callable(fn):
            _safe_add(fn, stem)

        return results

    # -- (un)register -------------------------------------------------------
    def unload_module(self, module_name: str) -> None:
        for name in self._module_tools.pop(module_name, []):
            with contextlib.suppress(Exception):
                self.mcp.remove_tool(name)
            if self._name_owner.get(name) == module_name:
                self._name_owner.pop(name, None)
            self._tool_info.pop(name, None)
            self._changed = True
        self._mtime.pop(module_name, None)
        sys.modules.pop(module_name, None)

    def prepare(self, file_path: Path) -> Optional[_LoadPlan]:
        """Verify + import + resolve a tool file. Safe to run OFF the loop; does
        not touch the FastMCP registry. Returns None when nothing changed."""
        try:
            module_name = self.module_name_for_path(file_path)
            if not module_name:
                return None
            if not file_path.exists():
                return _LoadPlan(module_name, None, [], failure="deleted")
            try:
                mtime = file_path.stat().st_mtime
            except FileNotFoundError:
                return _LoadPlan(module_name, None, [], failure="deleted")
            if self._mtime.get(module_name) == mtime and module_name in self._module_tools:
                return None  # unchanged since last load

            if self.verifier is not None:
                ok, reason = self.verifier.verify(file_path)
                if not ok:
                    return _LoadPlan(module_name, mtime, [], failure=f"unsigned/untrusted: {reason}")

            try:
                module = self._import(module_name)
            except Exception as exc:
                return _LoadPlan(module_name, mtime, [], failure=f"import error: {exc}")

            return _LoadPlan(module_name, mtime, self._resolve_tools(module, module_name))
        except Exception as exc:  # prepare must never raise into the drain
            log.error("prepare() failed for %s: %s", file_path, exc)
            return None

    def commit(self, plan: Optional[_LoadPlan]) -> None:
        """Apply a prepared plan to the registry. MUST run on the serving loop."""
        if plan is None:
            return
        module_name = plan.module_name
        self.unload_module(module_name)  # clear stale registrations first

        if plan.failure == "deleted":
            return
        if plan.failure:
            self._failures[module_name] = plan.failure
            if plan.mtime is not None:
                self._mtime[module_name] = plan.mtime
            METRICS.inc("mcp_load_failures_total")
            log.error("Not loading %s: %s", module_name, plan.failure)
            return

        registered: List[str] = []
        for name, tool_obj in plan.resolved:
            if not name:
                log.error("Skipping unnamed tool in %s", module_name)
                continue
            if name in self._disabled:
                log.info("Tool %r from %s is disabled; skipping registration", name, module_name)
                continue
            owner = self._name_owner.get(name)
            if owner and owner != module_name:
                log.warning(
                    "Tool name %r from %s ignored: already provided by %s (first wins)",
                    name, module_name, owner,
                )
                continue
            try:
                self.mcp.add_tool(tool_obj)
                self._name_owner[name] = module_name
                self._tool_info[name] = {
                    "name": name,
                    "module": module_name,
                    "description": getattr(tool_obj, "description", None),
                    "tags": sorted(getattr(tool_obj, "tags", None) or []),
                }
                registered.append(name)
                self._changed = True
            except Exception as exc:
                log.error("Failed to register tool %r from %s: %s", name, module_name, exc)

        self._module_tools[module_name] = registered
        if plan.mtime is not None:
            self._mtime[module_name] = plan.mtime
        if registered:
            self._failures.pop(module_name, None)
            METRICS.inc("mcp_reloads_total")
            log.info("Loaded %d tool(s) from %s: %s", len(registered), module_name, registered)
        else:
            self._failures[module_name] = "no valid tools"
            METRICS.inc("mcp_load_failures_total")

    def load_path(self, file_path: Path) -> None:
        """Prepare + commit inline. Never raises. Used by tests, --validate, and
        single-tool admin reloads (all already on-loop or off-server)."""
        try:
            self.commit(self.prepare(file_path))
        except Exception as exc:
            log.error("Unexpected error loading %s: %s", file_path, exc)

    def unload_path(self, file_path: Path) -> None:
        module_name = self.module_name_for_path(file_path)
        if module_name:
            self.unload_module(module_name)

    def load_all(self) -> None:
        for py in self.tools_dir.glob("*.py"):
            if py.name != "__init__.py":
                self.load_path(py)

    # -- admin / introspection ----------------------------------------------
    def disable(self, name: str) -> bool:
        module = self._name_owner.get(name)
        if not module and name not in self._disabled:
            return False
        self._disabled[name] = module or self._disabled.get(name, "")
        with contextlib.suppress(Exception):
            self.mcp.remove_tool(name)
        if module and name in self._module_tools.get(module, []):
            self._module_tools[module].remove(name)
        self._name_owner.pop(name, None)
        self._tool_info.pop(name, None)
        self._changed = True
        return True

    def enable(self, name: str) -> Optional[str]:
        """Re-enable a disabled tool; returns the owning module to reload (or None)."""
        module = self._disabled.pop(name, None)
        if module:
            self._mtime.pop(module, None)
            self._module_tools.pop(module, None)
        return module

    def stats(self) -> dict:
        return {
            "loaded_modules": len([m for m, v in self._module_tools.items() if v]),
            "total_tools": sum(len(v) for v in self._module_tools.values()),
            "failed_modules": len(self._failures),
            "disabled_tools": len(self._disabled),
            "failures": dict(self._failures),
        }

    def catalog(self) -> List[dict]:
        return sorted(self._tool_info.values(), key=lambda t: t["name"])

    def pop_changed(self) -> bool:
        changed, self._changed = self._changed, False
        return changed


async def prepare_with_timeout(loader: ToolLoader, path: Path, timeout: float):
    """Import/resolve a tool OFF the loop, bounded by a timeout so a slow or
    hanging import cannot block the server. On timeout the plan is skipped."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, loader.prepare, path), timeout=timeout)
    except asyncio.TimeoutError:
        log.error("Import of %s exceeded %ss; skipping (worker thread may linger)", path, timeout)
        return None


async def initial_load(loader: ToolLoader, import_timeout: float) -> None:
    """Load all tools with imports off-loop and registration on-loop. Yields
    between files so /healthz and /readyz stay responsive during startup."""
    for py in sorted(loader.tools_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        plan = await prepare_with_timeout(loader, py, import_timeout)
        loader.commit(plan)  # on-loop, fast
