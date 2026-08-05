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
from dataclasses import dataclass, field
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
class ResolutionReport:
    """An explainable account of how a module's functions became (or did not
    become) tools -- so onboarding can preview the exposed surface, apply
    exposure policy, and give authors actionable feedback.

    ``mechanism`` is the winning authoring mechanism (``register`` | ``TOOLS`` |
    ``decorator`` | ``legacy``) or ``None`` when nothing resolved.
    """
    mechanism: Optional[str] = None
    functions_seen: List[str] = field(default_factory=list)   # module-level defs
    selected: List[str] = field(default_factory=list)         # tool names exposed
    excluded: List[Tuple[str, str]] = field(default_factory=list)  # (fn_name, reason)
    warnings: List[str] = field(default_factory=list)


@dataclass
class _LoadPlan:
    """Result of importing/resolving a tool file OFF the event loop. Applying it
    (``commit``) is a fast, on-loop registry mutation."""
    module_name: str
    mtime: Optional[float]
    resolved: List[Tuple[str, "FunctionTool"]]
    failure: Optional[str] = None  # "deleted" | "unsigned: ..." | "import error: ..." etc.
    resolution: Optional[ResolutionReport] = None


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
        self._tools: Dict[str, FunctionTool] = {}       # tool name -> registered tool (for direct calls)
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
        parent_dir = str(self.tools_dir.parent.resolve())
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        top_pkg = module_name.split(".")[0]
        if top_pkg in sys.modules:
            mod = sys.modules[top_pkg]
            mod_file = getattr(mod, "__file__", None)
            if mod_file and not str(Path(mod_file).resolve()).startswith(parent_dir):
                sys.modules.pop(top_pkg, None)
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

            # Self-Healing Input Type Coercion (convert string arguments to int/bool/float if typed)
            with contextlib.suppress(Exception):
                sig = inspect.signature(original)
                for p_name, param in sig.parameters.items():
                    if p_name in kwargs and isinstance(kwargs[p_name], str):
                        val_str = kwargs[p_name]
                        target_type = param.annotation
                        if target_type in (int, "int") and re.match(r"^-?\d+$", val_str):
                            kwargs[p_name] = int(val_str)
                        elif target_type in (bool, "bool") and val_str.lower() in ("true", "false", "1", "0"):
                            kwargs[p_name] = val_str.lower() in ("true", "1")
                        elif target_type in (float, "float") and re.match(r"^-?\d+(\.\d+)?$", val_str):
                            kwargs[p_name] = float(val_str)

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

    @staticmethod
    def _functions_defined_in(module, module_name: str) -> List[str]:
        """Top-level functions DEFINED in this module (not imported), in source
        order. Includes ``_``-prefixed helpers so the report can show them as
        'seen but not exposed'."""
        seen = []
        for key, val in vars(module).items():
            if key.startswith("__"):
                continue
            if inspect.isfunction(val) and getattr(val, "__module__", None) == module.__name__:
                seen.append(key)
        return seen

    def _resolve_tools(self, module, module_name: str) -> List[Tuple[str, FunctionTool]]:
        """Back-compat shim: return only the (name, tool) pairs."""
        results, _report = self._resolve_with_report(module, module_name)
        return results

    def _resolve_with_report(self, module, module_name: str
                             ) -> Tuple[List[Tuple[str, FunctionTool]], ResolutionReport]:
        """Return ((name, tool) pairs, ResolutionReport) using the first matching
        mechanism. A single malformed tool is logged and skipped, never aborting
        the module. The report explains what was exposed and what was not, for
        onboarding preview / policy / author feedback."""
        results: List[Tuple[str, FunctionTool]] = []
        report = ResolutionReport(functions_seen=self._functions_defined_in(module, module_name))

        def _safe_add(obj, explicit_name):
            try:
                results.append(self._to_tool(obj, explicit_name))
            except Exception as exc:
                ident = explicit_name or getattr(obj, "__name__", repr(obj))
                log.error("Skipping invalid tool %r in %s: %s", ident, module_name, exc)

        def _finish(mechanism, exposed_fns, exclusion_reason):
            # ``exposed_fns`` is the set of source FUNCTION names that became
            # tools (not the tool names, which @tool(name=...) may rename).
            report.mechanism = mechanism
            report.selected = [n for n, _ in results]
            report.excluded = [(fn, exclusion_reason) for fn in report.functions_seen
                               if fn not in exposed_fns]
            return results, report

        register = getattr(module, "register", None)
        if callable(register):
            registrar = _CollectingRegistrar()
            try:
                register(registrar)
            except Exception as exc:
                log.error("register() raised in %s: %s", module_name, exc)
            if registrar.collected:
                results.extend(registrar.collected)
                # register() decides exposure opaquely; don't attribute helpers.
                return _finish("register", set(report.functions_seen), "")

        exported = getattr(module, "TOOLS", None)
        if exported:
            items = exported.items() if isinstance(exported, dict) else [(None, o) for o in exported]
            exposed = set()
            for explicit_name, obj in items:
                if callable(obj) or isinstance(obj, FunctionTool):
                    _safe_add(obj, explicit_name)
                    if (fname := getattr(obj, "__name__", None)):
                        exposed.add(fname)
                else:
                    log.error("TOOLS entry %r in %s is not callable; skipped", explicit_name, module_name)
            if results:
                # Warn if @tool-decorated functions exist but are shadowed by TOOLS.
                shadowed = [k for k, v in vars(module).items()
                            if callable(v) and hasattr(v, TOOL_MARKER) and k not in exposed]
                if shadowed:
                    report.warnings.append(
                        f"@tool-decorated function(s) {shadowed} are ignored because TOOLS is defined")
                return _finish("TOOLS", exposed, "not listed in TOOLS")

        decorated = [(k, v) for k, v in vars(module).items()
                     if callable(v) and hasattr(v, TOOL_MARKER)]
        if decorated:
            for _fname, fn in decorated:
                _safe_add(fn, None)
            if results:
                return _finish("decorator", {k for k, _ in decorated}, "not decorated with @tool")

        stem = module_name.split(".")[-1]
        fn = getattr(module, stem, None)
        if callable(fn):
            _safe_add(fn, stem)
            if results:
                return _finish("legacy", {stem}, "name does not match the file stem")

        return _finish(None, set(), "not exposed by any authoring mechanism")

    # -- (un)register -------------------------------------------------------
    def unload_module(self, module_name: str) -> None:
        for name in self._module_tools.pop(module_name, []):
            with contextlib.suppress(Exception):
                provider = getattr(self.mcp, "local_provider", self.mcp)
                provider.remove_tool(name)
            if self._name_owner.get(name) == module_name:
                self._name_owner.pop(name, None)
            self._tool_info.pop(name, None)
            self._tools.pop(name, None)
            self._changed = True
        self._mtime.pop(module_name, None)
        # A module that has been unloaded (deleted / rolled back) is no longer
        # "failing"; drop any recorded failure so /status stats don't leak it.
        # commit() re-records a fresh failure right after, if the reload fails.
        self._failures.pop(module_name, None)
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

            resolved, report = self._resolve_with_report(module, module_name)
            return _LoadPlan(module_name, mtime, resolved, resolution=report)
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
                self._tools[name] = tool_obj            # keep a ref for direct calls
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

    def invalidate(self, module_name: str) -> None:
        """Forget a module's cached mtime so the next ``prepare()`` re-imports
        it even if the file's mtime looks unchanged. Used before re-loading a
        file that was just (over)written, so mtime-dedup can't skip it."""
        self._mtime.pop(module_name, None)

    def module_outcome(self, module_name: str) -> Tuple[List[str], Optional[str]]:
        """After a load attempt, report (registered tool names, failure reason)
        for one module. Callers that need a truthful load result -- e.g. tool
        onboarding -- use this instead of assuming ``load_path`` succeeded."""
        return list(self._module_tools.get(module_name, [])), self._failures.get(module_name)

    def get_tool(self, name: str) -> Optional["FunctionTool"]:
        """The currently-registered tool object for ``name`` (None if unknown or
        disabled). Used by the direct-execution HTTP endpoint; invoking
        ``tool.run(arguments)`` goes through the same metrics/sandbox wrapper as
        an MCP ``tools/call``."""
        return self._tools.get(name)

    def load_all(self) -> None:
        for py in self.tools_dir.glob("*.py"):
            if py.name != "__init__.py":
                self.load_path(py)

    # -- external plugin registration ---------------------------------------
    def register_external_tool(
        self,
        name: str,
        fn_or_tool: Any,
        description: Optional[str] = None,
        module_name: str = "openapi",
        tags: Optional[List[str]] = None,
    ) -> FunctionTool:
        """Register a dynamic external tool (e.g. from OpenAPI plugin) into FastMCP and loader registries."""
        _name, tool_obj = self._to_tool(fn_or_tool, name)
        if description and hasattr(tool_obj, "description"):
            tool_obj.description = description

        with contextlib.suppress(Exception):
            provider = getattr(self.mcp, "local_provider", self.mcp)
            provider.add_tool(tool_obj)

        self._name_owner[name] = module_name
        self._tools[name] = tool_obj
        self._tool_info[name] = {
            "name": name,
            "module": module_name,
            "description": getattr(tool_obj, "description", None) or description,
            "tags": sorted(tags or ["openapi"]),
        }
        if module_name not in self._module_tools:
            self._module_tools[module_name] = []
        if name not in self._module_tools[module_name]:
            self._module_tools[module_name].append(name)
        self._changed = True
        return tool_obj

    def unregister_external_tool(self, name: str, module_name: str = "openapi") -> bool:
        """Unregister an external tool from FastMCP and loader registries."""
        with contextlib.suppress(Exception):
            provider = getattr(self.mcp, "local_provider", self.mcp)
            provider.remove_tool(name)
        if self._name_owner.get(name) == module_name:
            self._name_owner.pop(name, None)
        self._tool_info.pop(name, None)
        self._tools.pop(name, None)
        if module_name in self._module_tools and name in self._module_tools[module_name]:
            self._module_tools[module_name].remove(name)
        self._changed = True
        return True

    # -- admin / introspection ----------------------------------------------

    def disable(self, name: str) -> bool:
        module = self._name_owner.get(name)
        if not module and name not in self._disabled:
            return False
        self._disabled[name] = module or self._disabled.get(name, "")
        with contextlib.suppress(Exception):
            provider = getattr(self.mcp, "local_provider", self.mcp)
            provider.remove_tool(name)
        if module and name in self._module_tools.get(module, []):
            self._module_tools[module].remove(name)
        self._name_owner.pop(name, None)
        self._tool_info.pop(name, None)
        self._tools.pop(name, None)
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
