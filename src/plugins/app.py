"""Assembles the server as a **FastAPI** app from the plugin components.

The top-level application is FastAPI (a Starlette subclass); the FastMCP protocol
app is built via ``mcp.http_app(...)`` and **mounted** at "/" so it keeps serving
the protocol endpoints (``/mcp`` for streamable HTTP, or ``/sse`` + ``/messages``
for SSE). FastAPI provides auto Swagger UI at ``/docs`` and a generated schema at
``/openapi.json``. The FastMCP session-manager lifespan is entered explicitly
inside our lifespan (mounted sub-app lifespans do not run automatically).

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

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route

from . import dependency_risk as risk
from .notifications import notify_tools_changed
from .observability import TraceCorrelationMiddleware, setup_observability
from .onboarding import OnboardingManager
from .routes import feature_routes, register_metrics
from .security import ApiKeyMiddleware, build_mcp
from .signing import ToolVerifier
from .tool_loader import ToolLoader, initial_load, prepare_with_timeout
from .upstreams import UpstreamRegistry
from .watcher import ToolDirectoryWatcher

log = logging.getLogger("MCP_logger")

# FastAPI owns these paths (auto Swagger UI + generated schema); the hand-built
# equivalents in feature_routes() are skipped so they don't clash.
_FASTAPI_OWNED_DOCS = {"/docs", "/redoc", "/openapi.json", "/swagger", "/openapi.yaml"}
_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


def _as_request_endpoint(endpoint):
    """Wrap a Starlette-style ``async def h(request)`` handler so FastAPI injects
    the Request (via the annotation) and includes the route in its OpenAPI schema,
    instead of mistaking the unannotated ``request`` param for a query field."""
    async def _endpoint(request: Request):
        return await endpoint(request)
    _endpoint.__name__ = getattr(endpoint, "__name__", "endpoint")
    _endpoint.__doc__ = getattr(endpoint, "__doc__", None)
    return _endpoint


def _register_routes(app: FastAPI, routes, skip_paths=frozenset()) -> None:
    """Attach Starlette Route objects to a FastAPI app. Plain routes become
    documented API routes (auto /docs); Mounts/others are appended as-is. The
    hand-built docs routes, and any path in ``skip_paths`` (served by a typed
    router instead), are skipped."""
    for r in routes:
        if isinstance(r, Route):
            if r.path in _FASTAPI_OWNED_DOCS or r.path in skip_paths:
                continue
            methods = sorted((set(r.methods or {"GET"})) & _HTTP_METHODS) or ["GET"]
            app.add_api_route(r.path, _as_request_endpoint(r.endpoint), methods=methods, name=r.name)
        else:
            app.router.routes.append(r)



async def _reload_drain(loader: ToolLoader, reload_q: "queue.Queue", mcp, import_timeout: float,
                        loader_lock: asyncio.Lock):
    """Apply reload events. Imports run OFF the loop (bounded by import_timeout);
    only the fast registry mutation (commit / unload) runs on-loop. A None item
    stops the drain. The shared ``loader_lock`` serializes these imports against
    tool onboarding so the two never import the same module concurrently."""
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, reload_q.get)
        if item is None:
            return
        action, path = item
        try:
            from pathlib import Path
            async with loader_lock:
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

    # Shared across the reload drain and onboarding so tool imports (which run in
    # executor threads) never race importlib for the same module.
    loader_lock = asyncio.Lock()

    onboarding = OnboardingManager(
        ctx.tools_dir, ctx.tools_dir.parent / f"{ctx.tools_dir.name}_pending", loader,
        allowlist=risk.load_name_set(ctx.onboard_allowlist_path, risk.DEFAULT_ALLOWLIST),
        denylist=risk.load_name_set(ctx.onboard_denylist_path, risk.DEFAULT_DENYLIST),
        network_check=ctx.onboard_network_check, network_timeout=ctx.onboard_network_timeout,
        autoinstall=ctx.onboard_autoinstall, install_timeout=ctx.onboard_install_timeout,
        import_timeout=ctx.import_timeout, enabled=ctx.onboard_enabled,
        only_binary=ctx.onboard_only_binary, audit_log_path=ctx.onboard_audit_log,
        require_explicit=ctx.onboard_require_explicit, max_tools=ctx.onboard_max_tools,
        loader_lock=loader_lock,
    )

    # MCP protocol transport. "http"/"streamable-http" → a single /mcp endpoint;
    # "sse" → the legacy /sse + /messages pair. stateless_http applies to the
    # streamable-HTTP transport only.
    transport = ctx.mcp_transport
    if transport == "sse":
        mcp_app = mcp.http_app(transport="sse")
        protocol_prefixes = ("/sse", "/messages")
    else:
        mcp_app = mcp.http_app(transport=transport, stateless_http=ctx.mcp_stateless)
        protocol_prefixes = ("/mcp",)

    # Top-level app is now **FastAPI** (a Starlette subclass). The FastMCP
    # protocol app (``mcp_app``) is mounted at "/" at the end so it keeps serving
    # the protocol endpoints (/mcp or /sse + /messages); its session-manager
    # lifespan is entered explicitly inside our lifespan below (mounted sub-app
    # lifespans do not run automatically). FastAPI provides auto /docs +
    # /openapi.json from the routes registered via _register_routes().
    app = FastAPI(
        title="MCP Tool Server",
        version="1.0.0",
        description="Secure, plugin-based MCP tool server (FastAPI).",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    # --- Phase 3 Reliability & Telemetry Setup ---
    from .reliability import (
        CircuitBreakerRegistry,
        RateLimitConfig,
        RateLimiterRegistry,
        ReliabilityMiddleware,
    )
    from .alerts import AlertManager
    from .dashboard import dashboard_routes

    rate_limit_cfg = RateLimitConfig(
        max_requests_per_minute=getattr(ctx, "rate_limit_default_rpm", 600),
        on_exceed="reject",
    )
    rate_limiter_registry = RateLimiterRegistry(rate_limit_cfg)
    circuit_breakers = CircuitBreakerRegistry()
    alert_manager = AlertManager(getattr(ctx, "alert_webhook_url", None))

    app.state.rate_limiters = rate_limiter_registry
    app.state.circuit_breakers = circuit_breakers
    app.state.alert_manager = alert_manager

    # Unauthorized Access Logger
    from .unauthorized_logger import UnauthorizedLogger, UnauthorizedLoggingMiddleware
    unauthorized_log_path = (ctx.tools_dir.parent if ctx.tools_dir else ctx.base_dir) / "logs" / "unauthorized_access.json.log"
    unauthorized_logger = UnauthorizedLogger(unauthorized_log_path)
    app.add_middleware(UnauthorizedLoggingMiddleware, logger=unauthorized_logger)

    # Middleware LIFO ordering (C2 fix): ReliabilityMiddleware registered FIRST -> runs innermost (after IdentityMiddleware)
    app.add_middleware(ReliabilityMiddleware, rate_limiter_registry=rate_limiter_registry)
    app.add_middleware(TraceCorrelationMiddleware)
    from .identity import IdentityMiddleware
    app.add_middleware(IdentityMiddleware)
    if ctx.auth_type == "api_key":
        app.add_middleware(ApiKeyMiddleware, header=ctx.api_key_header, value=ctx.api_key_value,
                           protected_prefixes=protocol_prefixes)
    # Typed FastAPI routes (validated bodies + documented schema) take over the
    # admin tenancy/RBAC endpoints and tool-call; the plain equivalents are
    # skipped below so they don't double-register.
    from .api_routes import router as typed_router, TYPED_PATHS
    app.include_router(typed_router)

    _register_routes(app, feature_routes(), skip_paths=TYPED_PATHS)
    _register_routes(app, dashboard_routes(), skip_paths=TYPED_PATHS)

    # Back-compat convenience endpoints backed by FastAPI's generated schema.
    async def _swagger_alias(request: Request):
        return RedirectResponse(url="/docs")

    async def _openapi_yaml(request: Request):
        import yaml
        return Response(yaml.safe_dump(request.app.openapi(), sort_keys=False),
                        media_type="application/yaml")

    app.add_api_route("/swagger", _swagger_alias, methods=["GET"], include_in_schema=False)
    app.add_api_route("/openapi.yaml", _openapi_yaml, methods=["GET"], include_in_schema=False)

    log_file_path = (ctx.tools_dir.parent if ctx.tools_dir else ctx.base_dir) / "logs" / "mcp_server.json.log"
    setup_observability(app=app, log_file=log_file_path)
    app.state.log_file_path = log_file_path
    app.state.unauthorized_log_path = unauthorized_log_path
    app.state.unauthorized_logger = unauthorized_logger

    app.state.ready = False
    app.state.loader = loader
    app.state.mcp = mcp
    app.state.auth_type = ctx.auth_type or "none"
    app.state.admin_token = ctx.admin_token
    app.state.jwt_verifier = jwt_verifier
    app.state.onboarding = onboarding

    # --- Supabase & RBAC Phase 0 context state ---
    app.state.supabase_url = ctx.supabase_url
    app.state.supabase_key = ctx.supabase_key
    app.state.superadmin_email = ctx.superadmin_email
    app.state.rbac_enabled = ctx.rbac_enabled
    app.state.rbac_mode = ctx.rbac_mode
    app.state.tenant_header = ctx.tenant_header
    app.state.workspace_header = ctx.workspace_header
    app.state.jwks_url = ctx.jwks_url
    app.state.jwt_issuer = ctx.jwt_issuer
    app.state.jwt_audience = ctx.jwt_audience
    app.state.jwt_algorithm = ctx.jwt_algorithm

    if ctx.supabase_url and ctx.supabase_key:
        from .auth_service import SupabaseAuthService
        app.state.supabase_auth = SupabaseAuthService(ctx.supabase_url, ctx.supabase_key)
    else:
        app.state.supabase_auth = None

    # Credentials + per-route auth policies (read by security.enforce)
    app.state.api_key_header = ctx.api_key_header
    app.state.api_key_value = ctx.api_key_value
    app.state.read_auth = ctx.read_auth
    app.state.metrics_auth = ctx.metrics_auth
    app.state.tool_call_auth = ctx.tool_call_auth
    app.state.upstream_auth = ctx.upstream_auth
    # OpenAPI Plugin Manager
    from .openapi_plugin import OpenAPIToolManager
    openapi_dir = ctx.openapi_specs_dir or ((ctx.tools_dir.parent if ctx.tools_dir else ctx.base_dir) / "logs" / "openapi_specs")
    openapi_manager = OpenAPIToolManager(mcp_server=mcp, loader=loader, storage_dir=openapi_dir)

    openapi_manager.load_saved_collections_from_disk()
    app.state.openapi_manager = openapi_manager

    # Federation registry
    app.state.upstreams = UpstreamRegistry(
        ctx.upstreams, timeout=ctx.upstream_timeout, allow_runtime=ctx.upstream_allow_runtime)
    app.state.mcp_transport = transport
    register_metrics(loader, app)

    # --- Tenancy Store & RBAC Engine (Phase 1 & 2) ---
    from .tenancy import create_tenancy_store
    from .tenancy.seeder import seed_tenancy_store_if_empty
    from .rbac import DecisionCache, PolicyEvaluator

    tenancy_store = create_tenancy_store(ctx)
    app.state.tenancy_store = tenancy_store

    rbac_cache = DecisionCache(maxsize=getattr(ctx, "rbac_cache_size", 10000), ttl_sec=getattr(ctx, "rbac_cache_ttl", 300.0))
    policy_evaluator = PolicyEvaluator(store=tenancy_store, cache=rbac_cache)
    app.state.policy_evaluator = policy_evaluator

    # The FastMCP session-manager lifespan lives on the mounted sub-app; enter it
    # explicitly (mounted sub-app lifespans are not run by Starlette otherwise).
    original_lifespan = mcp_app.router.lifespan_context
    stop_event = threading.Event()

    @contextlib.asynccontextmanager
    async def lifespan(app_):
        loop = asyncio.get_running_loop()

        # OTel lifespan bootstrap (C3 fix: safe for multi-worker Gunicorn fork)
        from .telemetry import HAS_OTEL, TelemetryConfig, init_telemetry, shutdown_telemetry
        if HAS_OTEL and getattr(ctx, "otel_enabled", True):
            init_telemetry(TelemetryConfig.from_env())

        rate_limiter_registry.start_cleanup_task()

        async def _bootstrap():
            # Initialize tenancy DB and first-start self-seeding
            try:
                await tenancy_store.init_db()
                await seed_tenancy_store_if_empty(tenancy_store, ctx)
            except Exception as exc:
                log.error("Failed to initialize or seed tenancy store: %s", exc)

            # Runs as a background task so the server accepts requests immediately:
            await initial_load(loader, ctx.import_timeout)
            app_.state.ready = True
            log.info("Initial tool load complete (source=local): %s", loader.stats())
            await _reload_drain(loader, reload_q, mcp, ctx.import_timeout, loader_lock)

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
            rate_limiter_registry.stop()
            if HAS_OTEL:
                shutdown_telemetry()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker
            with contextlib.suppress(Exception):
                await tenancy_store.close()

    app.router.lifespan_context = lifespan

    # Mount the FastMCP protocol app LAST so explicit FastAPI routes (and auto
    # /docs) win; this catch-all handles /mcp (or /sse + /messages).
    app.router.routes.append(Mount("/", app=mcp_app))
    return app, mcp

