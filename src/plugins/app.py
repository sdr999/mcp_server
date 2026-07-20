"""Assembles the FastMCP ASGI app from the plugin components.

No remote tool source (Azure or otherwise): tools are always served from a
local directory. A background task performs the initial load, then drains a
reload queue fed by the local filesystem watcher, applying imports off-loop
(bounded by a timeout) and registry mutations on-loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading

from . import dependency_risk as risk
from .notifications import notify_tools_changed
from .onboarding import OnboardingManager
from .routes import feature_routes, register_metrics
from .security import ApiKeyMiddleware, build_mcp
from .signing import ToolVerifier
from .tool_loader import ToolLoader, initial_load, prepare_with_timeout
from .watcher import ToolDirectoryWatcher

log = logging.getLogger("MCP_logger")


async def _reload_drain(loader: ToolLoader, reload_q: "queue.Queue", mcp, import_timeout: float):
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
            from pathlib import Path
            if action == "unload":
                loader.unload_path(Path(path))       # on-loop, fast
            else:
                plan = await prepare_with_timeout(loader, Path(path), import_timeout)
                loader.commit(plan)                  # on-loop, fast
            if loader.pop_changed():
                await notify_tools_changed(mcp)
        except Exception as exc:
            log.error("Reload error for %s: %s", path, exc)


def build_app(ctx):
    """Construct the FastMCP ASGI app with the background load/reload loop wired
    into a lifespan that also preserves FastMCP's own session-manager lifespan."""
    mcp, jwt_verifier = build_mcp(ctx)
    verifier = ToolVerifier(ctx.tools_dir, ctx.manifest_name, ctx.signing_key, ctx.require_signed)
    sandbox_limits = {}
    if ctx.sandbox_mem_mb:
        sandbox_limits["mem"] = ctx.sandbox_mem_mb * 1024 * 1024
    if ctx.sandbox_cpu_sec:
        sandbox_limits["cpu"] = ctx.sandbox_cpu_sec
    loader = ToolLoader(
        mcp, ctx.tools_dir, verifier=verifier,
        wrap_execution=ctx.metrics_enabled, sandbox=ctx.sandbox,
        sandbox_timeout=ctx.sandbox_timeout, sandbox_limits=sandbox_limits,
        src_dir=ctx.base_dir,
    )
    reload_q: "queue.Queue" = queue.Queue()
    watcher = ToolDirectoryWatcher(reload_q, ctx.tools_dir)

    onboarding = OnboardingManager(
        ctx.tools_dir, ctx.tools_dir.parent / f"{ctx.tools_dir.name}_pending", loader,
        allowlist=risk.load_name_set(ctx.onboard_allowlist_path, risk.DEFAULT_ALLOWLIST),
        denylist=risk.load_name_set(ctx.onboard_denylist_path, risk.DEFAULT_DENYLIST),
        network_check=ctx.onboard_network_check, network_timeout=ctx.onboard_network_timeout,
        autoinstall=ctx.onboard_autoinstall, install_timeout=ctx.onboard_install_timeout,
        enabled=ctx.onboard_enabled,
    )

    app = mcp.http_app(transport="sse")
    if ctx.auth_type == "api_key":
        app.add_middleware(ApiKeyMiddleware, header=ctx.api_key_header, value=ctx.api_key_value)
    for route in feature_routes():
        app.router.routes.append(route)

    app.state.ready = False
    app.state.loader = loader
    app.state.mcp = mcp
    app.state.auth_type = ctx.auth_type or "none"
    app.state.admin_token = ctx.admin_token
    app.state.jwt_verifier = jwt_verifier
    app.state.onboarding = onboarding
    register_metrics(loader, app)

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
            await initial_load(loader, ctx.import_timeout)
            app_.state.ready = True
            log.info("Initial tool load complete (source=local): %s", loader.stats())
            # Same task continues as the reload drain -- load-then-drain is
            # sequential, so there is no race on the registry.
            await _reload_drain(loader, reload_q, mcp, ctx.import_timeout)

        worker = loop.create_task(_bootstrap())
        watcher.start()
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
