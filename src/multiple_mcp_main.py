"""Dynamic MCP tool server.

Serves tools over SSE (FastMCP). Tool modules are distributed via an Azure File
Share, mirrored to a local directory, and (re)loaded at runtime.

Tool authoring contract (see ``tools_sdk``): a module may expose tools via a
``register(registrar)`` hook, a ``TOOLS`` export, ``@tool``-decorated functions,
or the legacy "function name == file stem" convention. The tool name is no longer
required to match the file name.

Features
--------
* Liveness ``/healthz`` and readiness ``/readyz`` (ready only after initial load).
* Observability: ``/status`` (load stats) and ``/tools`` (catalog).
* Admin API (requires ``MCP_ADMIN_TOKEN``): resync, reload a tool, enable/disable a tool.
* Optional signed-tool enforcement (``MCP_REQUIRE_SIGNED_TOOLS`` + a SHA/HMAC manifest).
* Best-effort ``tools/list_changed`` push to connected clients on reload.
* CLI utilities: ``--validate DIR`` (CI gate) and ``--sign DIR`` (generate manifest).

Design notes
------------
* All start-up work runs inside ``main()`` — importing this module has no side
  effects, so it can be unit-tested (see ``tests/test_tool_loader.py``).
* Tool registry mutations happen ONLY on the serving event loop, drained from a
  thread-safe queue. The Azure poller and filesystem watcher merely enqueue.
* The Azure poller downloads atomically (``*.tmp`` then ``os.replace``).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import hmac
import importlib
import json
import logging
import os
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import dotenv_values
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from azure.storage.fileshare import ShareServiceClient, ShareDirectoryClient
from azure.core.exceptions import ResourceNotFoundError

from fastmcp import FastMCP
from fastmcp.tools import FunctionTool
from fastmcp.server.auth.providers.jwt import JWTVerifier

from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.middleware.base import BaseHTTPMiddleware

from agentic_framework.utils import global_variables

from tools_sdk import TOOL_MARKER
from metrics import METRICS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("MCP_logger")

# The Azure SDK logs every HTTP request/response at INFO, which is extremely
# verbose and buries the server's own logs. Default those loggers to WARNING
# (real Azure warnings/errors still surface). Override with MCP_AZURE_LOG_LEVEL
# (e.g. "INFO") to get the wire logs back.
logging.getLogger("azure").setLevel(logging.WARNING)

SRC_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_POLL_INTERVAL = 60
DEFAULT_IMPORT_TIMEOUT = 30
DEFAULT_SANDBOX_TIMEOUT = 30
DEFAULT_MANIFEST = "tools.manifest.json"
HEALTH_PATH = "/healthz"
READY_PATH = "/readyz"
DOCS_PATHS = {"/docs", "/swagger", "/openapi.json", "/openapi.yaml"}
EXEMPT_PATHS = {HEALTH_PATH, READY_PATH} | DOCS_PATHS


# ======================================================================
# Configuration
# ======================================================================
@dataclass
class AppContext:
    base_dir: Path
    local_tools_dir: Path
    remote_prefix: str
    env: dict
    auth_type: str
    api_key_header: str
    api_key_value: str
    jwks_url: str
    jwt_issuer: Optional[str]
    jwt_audience: Optional[str]
    jwt_required_scopes: Optional[List[str]]
    host: str
    port: int
    poll_interval: int
    import_timeout: float
    metrics_enabled: bool
    sandbox: bool
    sandbox_timeout: float
    sandbox_mem_mb: int
    sandbox_cpu_sec: int
    admin_token: str
    tool_source: str            # "auto" | "azure" | "local"
    require_signed: bool
    manifest_name: str
    signing_key: Optional[str]
    share_client: object = None
    remote_dir_client: object = None
    azure_enabled: bool = False  # resolved at startup


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dynamic MCP tool server")
    p.add_argument("--config", help="Base64-encoded tools directory path (server mode)")
    p.add_argument("--validate", metavar="DIR", help="Validate a local tools directory and exit")
    p.add_argument("--sign", metavar="DIR", help="Generate a signed manifest for a local dir and exit")
    return p


def merge_env(os_env, fallbacks: dict) -> dict:
    """Precedence: an OS environment variable wins when it is set AND non-blank;
    otherwise the config/.env fallback is used. A blank OS value (``KEY=""``)
    is treated as unset so the fallback still applies."""
    env = dict(os_env)
    for key, value in (fallbacks or {}).items():
        if value is None:
            continue
        current = env.get(key)
        if current is None or str(current).strip() == "":
            env[key] = value
    return env


def load_environment(base_dir: Path) -> dict:
    """Build the process env: OS environment variables take precedence; the
    checked-in ``config/.env`` provides fallbacks for keys that are unset or blank.

    ``global_variables.env`` is aliased to the result so the framework and
    adapters read the same configuration. A missing ``config/.env`` is fine.
    """
    env_path = base_dir / "config" / ".env"
    fallbacks = dotenv_values(str(env_path)) if env_path.exists() else {}
    env = merge_env(os.environ, fallbacks)
    global_variables.env = env
    return env


def decode_config_path(raw: str, base_dir: Path) -> Tuple[str, Path]:
    """Decode the base64 ``--config`` value into a validated tools directory.

    Raises ValueError on traversal / absolute / drive-qualified paths so a
    malformed or hostile config cannot escape ``base_dir``.
    """
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    decoded = base64.b64decode(raw).decode("utf-8").strip()

    if not decoded:
        raise ValueError("--config decoded to an empty path")
    if decoded.startswith(("/", "\\")) or ".." in Path(decoded).parts or ":" in decoded[:3]:
        raise ValueError(f"--config tool path is not a safe relative path: {decoded!r}")

    base_resolved = base_dir.resolve()
    local = (base_dir / decoded).resolve()
    # Correct containment check (avoids the /base vs /base-evil prefix bug).
    if not local.is_relative_to(base_resolved):
        raise ValueError(f"--config path escapes base dir: {decoded!r}")
    return decoded, local


def build_context(argv: Optional[List[str]] = None) -> AppContext:
    """Parse args + environment into a context for server mode. No network I/O."""
    args = _make_parser().parse_args(argv)
    if not args.config:
        raise SystemExit("--config is required to run the server")

    base_dir = Path(__file__).resolve().parent
    env = load_environment(base_dir)
    remote_prefix, local_tools_dir = decode_config_path(args.config, base_dir)

    auth_type = (env.get("MCP_AUTH_TYPE") or "").lower()
    if not auth_type and env.get("MCP_AUTHENTICATION_FLAG", "false").lower() == "true":
        auth_type = "bearer_jwt"  # backward compat

    scopes = [s.strip() for s in (env.get("MCP_JWT_REQUIRED_SCOPES") or "").split(",") if s.strip()]

    return AppContext(
        base_dir=base_dir,
        local_tools_dir=local_tools_dir,
        remote_prefix=remote_prefix,
        env=env,
        auth_type=auth_type,
        api_key_header=env.get("MCP_API_KEY_HEADER", "Authorization").lower(),
        api_key_value=env.get("MCP_API_KEY_VALUE", ""),
        jwks_url=env.get("JWKS_URL", ""),
        jwt_issuer=env.get("MCP_JWT_ISSUER") or None,
        jwt_audience=env.get("MCP_JWT_AUDIENCE") or None,
        jwt_required_scopes=scopes or None,
        host=env.get("MCP_HOST", DEFAULT_HOST),
        port=int(env.get("MCP_PORT", DEFAULT_PORT)),
        poll_interval=int(env.get("MCP_POLL_INTERVAL_SEC", DEFAULT_POLL_INTERVAL)),
        import_timeout=float(env.get("MCP_TOOL_IMPORT_TIMEOUT_SEC", DEFAULT_IMPORT_TIMEOUT)),
        metrics_enabled=(env.get("MCP_METRICS", "true").lower() == "true"),
        sandbox=(env.get("MCP_SANDBOX_TOOLS", "false").lower() == "true"),
        sandbox_timeout=float(env.get("MCP_SANDBOX_TIMEOUT_SEC", DEFAULT_SANDBOX_TIMEOUT)),
        sandbox_mem_mb=int(env.get("MCP_SANDBOX_MEM_MB", "0")),
        sandbox_cpu_sec=int(env.get("MCP_SANDBOX_CPU_SEC", "0")),
        admin_token=env.get("MCP_ADMIN_TOKEN", ""),
        tool_source=(env.get("MCP_TOOL_SOURCE", "auto").lower()),
        require_signed=env.get("MCP_REQUIRE_SIGNED_TOOLS", "false").lower() == "true",
        manifest_name=env.get("MCP_TOOL_MANIFEST", DEFAULT_MANIFEST),
        signing_key=env.get("MCP_TOOL_SIGNING_KEY") or None,
    )


def validate_context(ctx: AppContext) -> None:
    """Fail fast on missing required configuration."""
    if ctx.tool_source not in ("auto", "azure", "local"):
        raise RuntimeError(f"MCP_TOOL_SOURCE must be auto|azure|local, got {ctx.tool_source!r}")
    # Azure creds are only mandatory in strict 'azure' mode. In 'auto' the server
    # falls back to the local tools directory; in 'local' Azure is never used.
    if ctx.tool_source == "azure" and (
        not ctx.env.get("AZURE_FILESTORE_CONNECTION_URL") or not ctx.env.get("AZURE_FILESTORE_NAME")
    ):
        raise RuntimeError("MCP_TOOL_SOURCE=azure requires AZURE_FILESTORE_CONNECTION_URL and AZURE_FILESTORE_NAME")
    if ctx.auth_type == "bearer_jwt" and not ctx.jwks_url:
        raise RuntimeError("JWKS_URL must be set when MCP_AUTH_TYPE=bearer_jwt")
    if ctx.auth_type == "api_key" and not ctx.api_key_value:
        raise RuntimeError("MCP_API_KEY_VALUE must be set when MCP_AUTH_TYPE=api_key")


# ======================================================================
# Signed-tool verification (feature: signed manifest)
# ======================================================================
def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_signature(tools: dict, signing_key: str) -> str:
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()


class ToolVerifier:
    """Verifies each tool file against a SHA-256 manifest before it is imported.

    Manifest (``tools.manifest.json`` in the tools dir):
        {"algorithm":"sha256","tools":{"weather.py":"<sha256>", ...},
         "signature":"<hmac-sha256 of the sorted tools map, optional>"}

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
                if not hmac.compare_digest(_manifest_signature(tools, signing_key), data.get("signature", "")):
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
        if not hmac.compare_digest(_sha256_file(file_path), want):
            return False, "hash mismatch"
        return True, ""


# ======================================================================
# FastMCP construction & auth
# ======================================================================
def build_mcp(ctx: AppContext) -> Tuple[FastMCP, Optional[JWTVerifier]]:
    """Return (mcp, jwt_verifier). The verifier is reused to protect the custom
    read routes (/status, /tools, /metrics) in bearer_jwt mode."""
    if ctx.auth_type == "bearer_jwt":
        if not ctx.jwt_audience:
            log.warning(
                "MCP_JWT_AUDIENCE is not set: the JWT verifier accepts tokens issued "
                "for any audience by this IdP. Set MCP_JWT_AUDIENCE to restrict access."
            )
        auth = JWTVerifier(
            jwks_uri=ctx.jwks_url,
            issuer=ctx.jwt_issuer,
            audience=ctx.jwt_audience,
            required_scopes=ctx.jwt_required_scopes,
        )
        return FastMCP(name="Tool Server", auth=auth), auth
    return FastMCP(name="Tool Server"), None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Constant-time API-key check. Exempts liveness/readiness paths for probes."""

    def __init__(self, app, header: str, value: str, exempt=EXEMPT_PATHS):
        super().__init__(app)
        self._header = header.lower()
        self._value = value
        self._exempt = set(exempt)

    async def dispatch(self, request, call_next):
        if request.url.path in self._exempt:
            return await call_next(request)
        provided = request.headers.get(self._header, "")
        if not hmac.compare_digest(provided, self._value):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ======================================================================
# Tool loading
# ======================================================================
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
    failure: Optional[str] = None   # "deleted" | "unsigned: ..." | "import error: ..." etc.


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
    """Resolves tool modules and registers them on the given FastMCP instance.

    Split model for concurrency + responsiveness:
      * ``prepare()`` does the slow work (verify, import, resolve) and may run in
        an executor thread — it does not mutate the FastMCP registry.
      * ``commit()`` applies the plan (add_tool/remove_tool) and MUST run on the
        serving event loop.
    ``load_path()`` runs both inline (used by tests, --validate, and admin reload
    of a single tool, all of which are already on the loop or off-server).
    """

    def __init__(self, mcp: FastMCP, tools_dir: Path, verifier: Optional[ToolVerifier] = None,
                 *, wrap_execution: bool = False, sandbox: bool = False,
                 sandbox_timeout: float = DEFAULT_SANDBOX_TIMEOUT, sandbox_limits: Optional[dict] = None):
        self.mcp = mcp
        self.tools_dir = tools_dir
        self.verifier = verifier
        self.wrap_execution = wrap_execution or sandbox   # metrics and/or sandbox
        self.sandbox = sandbox
        self.sandbox_timeout = sandbox_timeout
        self.sandbox_limits = sandbox_limits or {}
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
        import functools
        import inspect
        import time

        module_name = getattr(original, "__module__", None)
        qualname = getattr(original, "__qualname__", getattr(original, "__name__", ""))
        sandbox = self.sandbox
        timeout = self.sandbox_timeout
        limits = self.sandbox_limits
        syspath = [str(self.tools_dir.resolve().parent), str(SRC_DIR)]
        runner = str(SRC_DIR / "tool_runner.py")

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
        """Re-enable a disabled tool; returns the owning module to reload (or None).

        Invalidates the module's mtime/tracking so the follow-up load_path actually
        re-imports and re-registers (otherwise mtime-dedup would skip it, since the
        file hasn't changed since it was disabled)."""
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


# ======================================================================
# Azure File Share sync (runs off-loop, enqueues reload events)
# ======================================================================
def ensure_remote_directory_hierarchy(share_client, path: str) -> ShareDirectoryClient:
    try:
        share_client.get_share_properties()
    except ResourceNotFoundError:
        raise RuntimeError("Azure File Share does not exist. Create it first.")
    current = ""
    dir_client = share_client.get_directory_client("")
    for seg in [s for s in path.split("/") if s]:
        current = f"{current}/{seg}" if current else seg
        dir_client = share_client.get_directory_client(current)
        try:
            dir_client.get_directory_properties()
        except ResourceNotFoundError:
            share_client.create_directory(current)
    return dir_client


class AzureSync:
    """Mirrors the remote tools directory to local disk and enqueues reload
    events. Atomic downloads guarantee the loader never sees a partial file."""

    def __init__(self, ctx: AppContext, reload_q: "queue.Queue"):
        self.ctx = ctx
        self.q = reload_q

    def _download_if_newer(self, filename: str) -> bool:
        if not filename.endswith(".py"):
            return False
        local = self.ctx.local_tools_dir / filename
        file_client = self.ctx.remote_dir_client.get_file_client(filename)
        try:
            props = file_client.get_file_properties()
        except ResourceNotFoundError:
            return False
        remote_mtime = props["last_modified"].timestamp()
        local_mtime = local.stat().st_mtime if local.exists() else 0.0
        if local.exists() and remote_mtime <= local_mtime + 1e-6:
            return False
        tmp = local.with_suffix(local.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(file_client.download_file().readall())
        os.replace(tmp, local)  # atomic publish
        return True

    def sync_once(self) -> None:
        try:
            remote_items = list(self.ctx.remote_dir_client.list_directories_and_files())
        except ResourceNotFoundError:
            self.ctx.remote_dir_client = ensure_remote_directory_hierarchy(
                self.ctx.share_client, self.ctx.remote_prefix
            )
            return
        remote_py = {it["name"] for it in remote_items if it["name"].endswith(".py")}

        for name in remote_py:
            try:
                if self._download_if_newer(name):
                    self.q.put(("load", str(self.ctx.local_tools_dir / name)))
            except Exception as exc:
                log.error("Error pulling %r: %s", name, exc)

        local_py = {p.name for p in self.ctx.local_tools_dir.glob("*.py") if p.name != "__init__.py"}
        for name in local_py - remote_py:
            try:
                (self.ctx.local_tools_dir / name).unlink(missing_ok=True)
                self.q.put(("unload", str(self.ctx.local_tools_dir / name)))
            except Exception as exc:
                log.error("Error deleting local %r: %s", name, exc)

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.ctx.poll_interval):
            try:
                self.sync_once()
            except Exception as exc:
                log.error("Sync cycle error: %s", exc)


class ToolDirectoryWatcher(FileSystemEventHandler):
    """Watches the local dir for out-of-band edits; enqueues reload events."""

    def __init__(self, reload_q: "queue.Queue", tools_dir: Path):
        self.q = reload_q
        self.tools_dir = tools_dir
        self.observer = Observer()

    def _emit(self, src_path: str, action: str) -> None:
        p = Path(src_path)
        if p.suffix == ".py" and p.name != "__init__.py":
            self.q.put((action, str(p)))

    def on_created(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "load")

    def on_modified(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "load")

    def on_deleted(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "unload")

    def start(self):
        self.observer.schedule(self, str(self.tools_dir.resolve()), recursive=False)
        self.observer.start()

    def stop(self):
        with contextlib.suppress(Exception):
            self.observer.stop()
            self.observer.join(timeout=5)


# ======================================================================
# Client notifications (feature: tools/list_changed) — best effort
# ======================================================================
def _discover_sessions(mcp: FastMCP):
    """Best-effort discovery of active MCP ServerSessions. FastMCP 3.4.2 exposes
    no public registry, so this probes known internal attributes and returns []
    when none are found (clients still see changes on their next list_tools)."""
    for mgr_attr in ("_session_manager", "session_manager", "_sessions"):
        mgr = getattr(mcp, mgr_attr, None)
        if mgr is None:
            continue
        if isinstance(mgr, dict):
            return list(mgr.values())
        for s_attr in ("_sessions", "sessions", "_server_sessions"):
            sessions = getattr(mgr, s_attr, None)
            if isinstance(sessions, dict):
                return list(sessions.values())
            if isinstance(sessions, (list, set, tuple)):
                return list(sessions)
    return []


async def notify_tools_changed(mcp: FastMCP) -> None:
    """Push notifications/tools/list_changed to connected clients (best effort)."""
    try:
        sessions = _discover_sessions(mcp)
        sent = 0
        for sess in sessions:
            send = getattr(sess, "send_tool_list_changed", None)
            if send is None:
                continue
            with contextlib.suppress(Exception):
                await send()
                sent += 1
        if sent:
            log.info("Notified %d client session(s): tools/list_changed", sent)
    except Exception as exc:
        log.debug("tools/list_changed notify skipped: %s", exc)


# ======================================================================
# HTTP routes (health, readiness, status, catalog, admin)
# ======================================================================
async def _health(_request):
    return JSONResponse({"status": "ok"})


async def _readyz(request):
    ready = bool(getattr(request.app.state, "ready", False))
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)


async def _read_guard(request):
    """Enforce the MCP credential on the custom read routes.

    - api_key mode: already enforced by ApiKeyMiddleware (returns None here).
    - bearer_jwt mode: validate the Bearer JWT with the same verifier used for
      /sse, closing the gap where these routes were previously unauthenticated.
    - none mode: open.
    Returns a 401 JSONResponse when denied, else None.
    """
    st = request.app.state
    if getattr(st, "auth_type", "none") != "bearer_jwt":
        return None
    verifier = getattr(st, "jwt_verifier", None)
    if verifier is None:
        return None
    authz = request.headers.get("authorization", "")
    token = authz[7:] if authz.lower().startswith("bearer ") else ""
    if not token or (await verifier.verify_token(token)) is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


async def _status(request):
    if (denied := await _read_guard(request)) is not None:
        return denied
    st = request.app.state
    return JSONResponse({"ready": bool(getattr(st, "ready", False)),
                         "auth": st.auth_type,
                         "source": getattr(st, "tool_source", "unknown"),
                         "stats": st.loader.stats()})


async def _tools_catalog(request):
    if (denied := await _read_guard(request)) is not None:
        return denied
    return JSONResponse({"tools": request.app.state.loader.catalog()})


async def _metrics(request):
    if (denied := await _read_guard(request)) is not None:
        return denied
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")


def _register_metrics(loader: "ToolLoader", app) -> None:
    """Declare counters and scrape-time gauges backed by loader/app state."""
    METRICS.declare("mcp_tool_calls_total", "Total tool invocations")
    METRICS.declare("mcp_tool_errors_total", "Tool invocations that raised")
    METRICS.declare("mcp_tool_duration_seconds", "Tool execution wall-time")
    METRICS.declare("mcp_reloads_total", "Module (re)loads that registered tools")
    METRICS.declare("mcp_load_failures_total", "Module loads that failed or yielded no tools")
    METRICS.gauge("mcp_ready", lambda: 1.0 if getattr(app.state, "ready", False) else 0.0,
                  "1 once the initial tool load has completed")
    METRICS.gauge("mcp_tools_loaded", lambda: loader.stats()["total_tools"], "Currently registered tools")
    METRICS.gauge("mcp_modules_failed", lambda: loader.stats()["failed_modules"], "Modules currently failing to load")
    METRICS.gauge("mcp_tools_disabled", lambda: loader.stats()["disabled_tools"], "Disabled tools")


def _admin_denied(request):
    """Return a JSONResponse if the admin request is unauthorized, else None."""
    token = getattr(request.app.state, "admin_token", "")
    if not token:
        return JSONResponse({"error": "admin API disabled (set MCP_ADMIN_TOKEN)"}, status_code=503)
    authz = request.headers.get("authorization", "")
    provided = authz[7:] if authz.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(provided, token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


async def _admin_resync(request):
    if (denied := _admin_denied(request)) is not None:
        return denied
    st = request.app.state
    if getattr(st, "syncer", None) is None:
        return JSONResponse({"status": "skipped", "reason": "local mode — no Azure sync"}, status_code=409)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, st.syncer.sync_once)
    return JSONResponse({"status": "resynced", "stats": st.loader.stats()})


async def _admin_reload(request):
    if (denied := _admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    module = st.loader.module_for_tool(name)
    if not module:
        return JSONResponse({"error": f"unknown tool {name!r}"}, status_code=404)
    st.loader.load_path(st.loader.file_for_module(module))
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "reloaded", "tool": name, "module": module})


async def _admin_disable(request):
    if (denied := _admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    if not st.loader.disable(name):
        return JSONResponse({"error": f"unknown tool {name!r}"}, status_code=404)
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "disabled", "tool": name})


async def _admin_enable(request):
    if (denied := _admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    module = st.loader.enable(name)
    if module:
        st.loader.load_path(st.loader.file_for_module(module))
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "enabled", "tool": name, "reloaded": bool(module)})


SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MCP Server API - Swagger UI</title>
  <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
  <link rel="icon" type="image/png" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/favicon-32x32.png" />
  <style>
    html { box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }
    *, *:before, *:after { box-sizing: inherit; }
    body { margin:0; background: #fafafa; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js" charset="UTF-8"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js" charset="UTF-8"></script>
  <script>
    window.onload = function() {
      window.ui = SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        plugins: [
          SwaggerUIBundle.plugins.DownloadUrl
        ],
        layout: "StandaloneLayout"
      });
    };
  </script>
</body>
</html>
"""


async def _swagger_ui(_request):
    return HTMLResponse(SWAGGER_UI_HTML)


def _load_openapi_spec() -> dict:
    spec_path = Path(__file__).resolve().parent.parent / "openapi" / "openapi.yaml"
    if not spec_path.exists():
        return {"openapi": "3.0.3", "info": {"title": "MCP Tool Server API", "version": "1.0.0"}, "paths": {}}
    try:
        import yaml
        return yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Failed to parse openapi.yaml: %s", exc)
        return {"openapi": "3.0.3", "info": {"title": "MCP Tool Server API", "version": "1.0.0"}, "paths": {}}


async def _openapi_json(_request):
    spec = _load_openapi_spec()
    return JSONResponse(spec)


async def _openapi_yaml(_request):
    spec_path = Path(__file__).resolve().parent.parent / "openapi" / "openapi.yaml"
    content = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    return PlainTextResponse(content, media_type="text/yaml")


def _feature_routes() -> List[Route]:
    return [
        Route(HEALTH_PATH, _health, methods=["GET"]),
        Route(READY_PATH, _readyz, methods=["GET"]),
        Route("/docs", _swagger_ui, methods=["GET"]),
        Route("/swagger", _swagger_ui, methods=["GET"]),
        Route("/openapi.json", _openapi_json, methods=["GET"]),
        Route("/openapi.yaml", _openapi_yaml, methods=["GET"]),
        Route("/status", _status, methods=["GET"]),
        Route("/tools", _tools_catalog, methods=["GET"]),
        Route("/metrics", _metrics, methods=["GET"]),
        Route("/admin/resync", _admin_resync, methods=["POST"]),
        Route("/admin/reload/{name}", _admin_reload, methods=["POST"]),
        Route("/admin/tool/{name}/disable", _admin_disable, methods=["POST"]),
        Route("/admin/tool/{name}/enable", _admin_enable, methods=["POST"]),
    ]



# ======================================================================
# Reload worker + app assembly
# ======================================================================
async def _prepare_with_timeout(loader: ToolLoader, path: Path, timeout: float):
    """Import/resolve a tool OFF the loop, bounded by a timeout so a slow or
    hanging import cannot block the server. On timeout the plan is skipped.

    Caveat: run_in_executor cannot cancel a truly hung import, so its worker
    thread leaks until the process exits — the real fix is subprocess isolation
    (tracked as the sandboxing feature)."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, loader.prepare, path), timeout=timeout)
    except asyncio.TimeoutError:
        log.error("Import of %s exceeded %ss; skipping (worker thread may linger)", path, timeout)
        return None


async def _initial_load(loader: ToolLoader, import_timeout: float) -> None:
    """Load all tools with imports off-loop and registration on-loop. Yields
    between files so /healthz and /readyz stay responsive during startup."""
    for py in sorted(loader.tools_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        plan = await _prepare_with_timeout(loader, py, import_timeout)
        loader.commit(plan)  # on-loop, fast


async def _reload_drain(loader: ToolLoader, reload_q: "queue.Queue", mcp: FastMCP, import_timeout: float):
    """Apply reload events. Imports run OFF the loop (bounded by import_timeout);
    only the fast registry mutation (commit / unload) runs on-loop. A None item
    stops the drain."""
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, reload_q.get)
        if item is None:
            return
        action, path = item
        try:
            if action == "unload":
                loader.unload_path(Path(path))       # on-loop, fast
            else:
                plan = await _prepare_with_timeout(loader, Path(path), import_timeout)
                loader.commit(plan)                  # on-loop, fast
            if loader.pop_changed():
                await notify_tools_changed(mcp)
        except Exception as exc:
            log.error("Reload error for %s: %s", path, exc)


def build_app(ctx: AppContext):
    """Construct the FastMCP ASGI app with background sync/reload wired into a
    lifespan that also preserves FastMCP's own session-manager lifespan."""
    mcp, jwt_verifier = build_mcp(ctx)
    verifier = ToolVerifier(ctx.local_tools_dir, ctx.manifest_name, ctx.signing_key, ctx.require_signed)
    sandbox_limits = {}
    if ctx.sandbox_mem_mb:
        sandbox_limits["mem"] = ctx.sandbox_mem_mb * 1024 * 1024
    if ctx.sandbox_cpu_sec:
        sandbox_limits["cpu"] = ctx.sandbox_cpu_sec
    loader = ToolLoader(
        mcp, ctx.local_tools_dir, verifier=verifier,
        wrap_execution=ctx.metrics_enabled, sandbox=ctx.sandbox,
        sandbox_timeout=ctx.sandbox_timeout, sandbox_limits=sandbox_limits,
    )
    reload_q: "queue.Queue" = queue.Queue()
    # Azure sync only when enabled; local mode serves the local dir + watcher only.
    syncer = AzureSync(ctx, reload_q) if ctx.azure_enabled else None
    watcher = ToolDirectoryWatcher(reload_q, ctx.local_tools_dir)

    app = mcp.http_app(transport="sse")
    if ctx.auth_type == "api_key":
        app.add_middleware(ApiKeyMiddleware, header=ctx.api_key_header, value=ctx.api_key_value)
    for route in _feature_routes():
        app.router.routes.append(route)

    app.state.ready = False
    app.state.loader = loader
    app.state.syncer = syncer
    app.state.mcp = mcp
    app.state.auth_type = ctx.auth_type or "none"
    app.state.admin_token = ctx.admin_token
    app.state.jwt_verifier = jwt_verifier
    app.state.tool_source = "azure" if ctx.azure_enabled else "local"
    _register_metrics(loader, app)

    original_lifespan = app.router.lifespan_context
    stop_event = threading.Event()

    @contextlib.asynccontextmanager
    async def lifespan(app_):
        loop = asyncio.get_running_loop()

        async def _bootstrap():
            # Runs as a background task so the server accepts requests immediately:
            # /healthz is live at once and /readyz reports 503 until the initial
            # load finishes, then 200. Imports are off-loop (bounded by timeout);
            # registration is on-loop.
            if syncer is not None:
                try:
                    await loop.run_in_executor(None, syncer.sync_once)
                except Exception as exc:
                    log.error("Initial Azure sync failed (continuing): %s", exc)
            await _initial_load(loader, ctx.import_timeout)
            app_.state.ready = True
            log.info("Initial tool load complete (source=%s): %s",
                     app_.state.tool_source, loader.stats())
            # Same task continues as the reload drain — load-then-drain is
            # sequential, so there is no race on the registry.
            await _reload_drain(loader, reload_q, mcp, ctx.import_timeout)

        worker = loop.create_task(_bootstrap())
        watcher.start()
        poller = None
        if syncer is not None:
            poller = threading.Thread(target=syncer.run, args=(stop_event,), daemon=True)
            poller.start()
        try:
            async with original_lifespan(app_):  # keep FastMCP session manager alive
                yield
        finally:
            stop_event.set()
            reload_q.put(None)
            watcher.stop()
            worker.cancel()
            # CancelledError is a BaseException (not Exception) in py3.8+, so it
            # must be suppressed explicitly or it escapes the lifespan on shutdown.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker

    app.router.lifespan_context = lifespan
    return app, mcp


# ======================================================================
# CLI utilities: --validate and --sign
# ======================================================================
def run_validate(tools_dir: Path) -> int:
    """Load a local tools directory and report results. No Azure, no server.
    Exit code 0 if all modules yield tools, 1 if any failed/empty."""
    if not tools_dir.exists():
        print(json.dumps({"error": f"directory not found: {tools_dir}"}))
        return 2
    sys.path.insert(0, str(tools_dir.resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # tools_sdk importable
    loader = ToolLoader(FastMCP(name="validate"), tools_dir)
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
        p.name: _sha256_file(p)
        for p in sorted(tools_dir.glob("*.py"))
        if p.name != "__init__.py"
    }
    manifest = {"algorithm": "sha256", "tools": tools}
    if signing_key:
        manifest["signature"] = _manifest_signature(tools, signing_key)
    out = tools_dir / manifest_name
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "written", "manifest": str(out), "tools": len(tools),
                      "signed": bool(signing_key)}))
    return 0


# ======================================================================
# Entry point
# ======================================================================
def main(argv: Optional[List[str]] = None) -> None:
    args = _make_parser().parse_args(argv)

    if args.validate is not None or args.sign is not None:
        # CLI utilities resolve env the same way the server does: OS environment
        # first, config/.env as fallback (and global_variables.env is set so tool
        # imports during --validate read the same configuration).
        env = load_environment(SRC_DIR)
        if args.validate is not None:
            raise SystemExit(run_validate(Path(args.validate)))
        raise SystemExit(run_sign(
            Path(args.sign),
            env.get("MCP_TOOL_SIGNING_KEY"),
            env.get("MCP_TOOL_MANIFEST", DEFAULT_MANIFEST),
        ))

    import uvicorn

    ctx = build_context(argv)
    validate_context(ctx)

    # Re-apply the Azure log level from config (env or config/.env), so it can be
    # tuned per-deployment. Defaults to WARNING to keep the console readable.
    _azure_level = (ctx.env.get("MCP_AZURE_LOG_LEVEL") or "WARNING").upper()
    logging.getLogger("azure").setLevel(getattr(logging, _azure_level, logging.WARNING))

    ctx.local_tools_dir.mkdir(parents=True, exist_ok=True)
    init_file = ctx.local_tools_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# Auto-generated to make this a package\n", encoding="utf-8")
    package_root = str(ctx.local_tools_dir.resolve().parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)

    # Resolve the tool source. Azure is attempted unless MCP_TOOL_SOURCE=local.
    # In 'auto' any Azure failure degrades to the local directory instead of
    # crashing; in 'azure' it is fatal (deployments that mandate Azure).
    has_creds = bool(ctx.env.get("AZURE_FILESTORE_CONNECTION_URL") and ctx.env.get("AZURE_FILESTORE_NAME"))
    if ctx.tool_source == "local" or not has_creds:
        if ctx.tool_source == "local":
            log.info("Tool source: LOCAL directory %s (Azure disabled by MCP_TOOL_SOURCE=local)", ctx.local_tools_dir)
        else:
            log.warning("Tool source: LOCAL directory %s (no Azure credentials configured)", ctx.local_tools_dir)
        ctx.azure_enabled = False
    else:
        try:
            # from_connection_string is lazy; the network call is ensure_remote_directory_hierarchy.
            ctx.share_client = ShareServiceClient.from_connection_string(
                ctx.env["AZURE_FILESTORE_CONNECTION_URL"]
            ).get_share_client(ctx.env["AZURE_FILESTORE_NAME"])
            ctx.remote_dir_client = ensure_remote_directory_hierarchy(ctx.share_client, ctx.remote_prefix)
            ctx.azure_enabled = True
            log.info("Tool source: Azure File Share '%s/%s' (sync every %ss)",
                     ctx.env["AZURE_FILESTORE_NAME"], ctx.remote_prefix, ctx.poll_interval)
        except Exception as exc:
            if ctx.tool_source == "azure":
                log.error("MCP_TOOL_SOURCE=azure but Azure is unavailable: %s", exc)
                raise
            log.warning(
                "Azure File Share unavailable (%s); falling back to LOCAL directory %s. "
                "Serving whatever tools are already mirrored there; no Azure sync this run.",
                exc, ctx.local_tools_dir,
            )
            ctx.azure_enabled = False

    app, _mcp = build_app(ctx)
    log.info("Starting MCP tool server on %s:%s (auth=%s, source=%s)",
             ctx.host, ctx.port, ctx.auth_type or "none",
             "azure" if ctx.azure_enabled else "local")
    uvicorn.run(app, host=ctx.host, port=ctx.port, log_level="info")


if __name__ == "__main__":
    main()
