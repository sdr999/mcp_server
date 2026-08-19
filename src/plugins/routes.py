"""HTTP routes: liveness, readiness, status, tool catalog, metrics, admin API.

Auth summary (see docs/MCP_AUTH_GUIDE.md):
  /healthz, /readyz            -- always open (probes).
  /status, /tools, /metrics    -- open in `none`; api-key in `api_key`; JWT in `bearer_jwt`.
  /admin/*                     -- always gated by MCP_ADMIN_TOKEN; 503 if unset.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import List


from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from metrics import METRICS
from .notifications import notify_tools_changed
from .onboarding import MAX_REQUIREMENTS, MAX_SOURCE_BYTES, OnboardingConflict
from .security import HEALTH_PATH, READY_PATH, admin_denied, enforce
from .upstreams import UpstreamError

log = logging.getLogger("MCP_logger")

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MCP Tool Server - Swagger UI</title>
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


def _load_openapi_spec(request=None) -> dict:
    spec_path = Path(__file__).resolve().parent.parent.parent / "openapi" / "openapi.yaml"
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "MCP Tool Server API", "version": "1.0.0"},
        "paths": {},
        "tags": [],
        "components": {"schemas": {}, "securitySchemes": {}},
    }
    if spec_path.exists():
        try:
            import yaml
            loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                spec = loaded
        except Exception as exc:
            log.error("Failed to parse openapi.yaml: %s", exc)

    if "paths" not in spec or not isinstance(spec["paths"], dict):
        spec["paths"] = {}

    # Dynamic Route Inspection & Auto-Discovery
    if request is not None and hasattr(request, "app") and hasattr(request.app, "router"):
        routes = getattr(request.app.router, "routes", [])
        for r in routes:
            path = getattr(r, "path", None)
            methods = getattr(r, "methods", None)
            if not path or not methods:
                continue

            openapi_path = path
            if openapi_path not in spec["paths"]:
                spec["paths"][openapi_path] = {}

            tag = "System"
            if openapi_path.startswith("/auth") or openapi_path == "/whoami":
                tag = "Authentication & Identity"
            elif openapi_path.startswith("/tools") or openapi_path == "/mcp" or openapi_path.startswith("/mcp"):
                tag = "Tools"

            elif openapi_path.startswith("/admin"):
                tag = "Onboarding & Admin"
            elif openapi_path.startswith("/mcp/upstreams"):
                tag = "Federation"

            for method in methods:
                m_lower = method.lower()
                if m_lower == "head":
                    continue
                if m_lower not in spec["paths"][openapi_path]:

                    op_id = f"auto_{m_lower}_{openapi_path.strip('/').replace('/', '_').replace('{', '').replace('}', '')}"
                    sec = [{"AdminTokenAuth": []}, {"XAdminTokenAuth": []}, {"BearerAuth": []}, {"ApiKeyAuth": []}] if tag in ("Onboarding & Admin", "Authentication & Identity", "Tools", "Federation") else []
                    spec["paths"][openapi_path][m_lower] = {
                        "tags": [tag],
                        "summary": f"{method.upper()} {openapi_path}",
                        "description": f"Auto-discovered route for {method.upper()} {openapi_path}",
                        "operationId": op_id,
                        "security": sec,
                        "responses": {
                            "200": {"description": "Successful operation"}
                        },
                    }


    return spec


async def _openapi_json(request):
    spec = _load_openapi_spec(request)
    return JSONResponse(spec)


async def _openapi_yaml(request):
    spec = _load_openapi_spec(request)
    try:
        import yaml
        content = yaml.dump(spec, sort_keys=False)
        return PlainTextResponse(content, media_type="text/yaml")
    except Exception:
        spec_path = Path(__file__).resolve().parent.parent.parent / "openapi" / "openapi.yaml"
        content = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
        return PlainTextResponse(content, media_type="text/yaml")



async def _health(_request):

    return JSONResponse({"status": "ok"})


async def _readyz(request):
    ready = bool(getattr(request.app.state, "ready", False))
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)


async def _status(request):
    st = request.app.state
    if (denied := await enforce(request, st.read_auth)) is not None:
        return denied
    return JSONResponse({
        "ready": bool(getattr(st, "ready", False)),
        "auth": st.auth_type,
        "transport": getattr(st, "mcp_transport", "http"),
        "source": "local",
        "stats": st.loader.stats(),
    })


async def _tools_catalog(request):
    st = request.app.state
    if (denied := await enforce(request, st.read_auth)) is not None:
        return denied
    tools = st.loader.catalog()
    store = getattr(st, "tenancy_store", None)
    evaluator = getattr(st, "policy_evaluator", None)
    principal = getattr(request.state, "principal", None)
    if store is not None:
        from .tenancy.scoping import filter_tools_for_principal
        tools = await filter_tools_for_principal(store, evaluator, principal, tools)
    return JSONResponse({"tools": tools})



async def _metrics(request):
    if (denied := await enforce(request, request.app.state.metrics_auth)) is not None:
        return denied
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")


# fastmcp raises its own ValidationError for bad tool arguments; import lazily so
# a fastmcp version without it degrades gracefully (bad args → generic 400).
try:
    from fastmcp.exceptions import ValidationError as _ToolValidationError
except Exception:  # pragma: no cover
    _ToolValidationError = None


def _serialize_tool_result(name: str, result) -> dict:
    """Turn a FastMCP ToolResult into a JSON envelope mirroring an MCP tools/call
    result: the structured value plus the content blocks."""
    content = [{"type": getattr(c, "type", None), "text": getattr(c, "text", None)}
               for c in (getattr(result, "content", None) or [])]
    return {
        "tool": name,
        "is_error": bool(getattr(result, "is_error", False)),
        "structured_content": getattr(result, "structured_content", None),
        "content": content,
    }


async def _tool_call(request):
    """Execute a registered tool by name over plain HTTP -- the direct-call
    equivalent of an MCP ``tools/call``. Gated by the same MCP credential as
    ``/tools`` and ``/sse`` (it exposes no capability an MCP client lacks), and
    it runs through the same metrics/sandbox wrapper."""
    if (denied := await enforce(request, request.app.state.tool_call_auth)) is not None:
        return denied
    name = request.path_params["name"]
    tool = request.app.state.loader.get_tool(name)
    if tool is None:
        return JSONResponse({"error": f"unknown or disabled tool {name!r}"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        body = {}
    arguments = body.get("arguments", {}) if isinstance(body, dict) else {}
    if not isinstance(arguments, dict):
        return JSONResponse({"error": '"arguments" must be a JSON object'}, status_code=400)

    try:
        result = await tool.run(arguments)
    except Exception as exc:
        if _ToolValidationError is not None and isinstance(exc, _ToolValidationError):
            # Phase E: validation is a route-level concern (the wrapper never runs
            # for a schema failure), so count it here -> completes the error
            # taxonomy without double-counting.
            METRICS.inc("mcp_tool_errors_total", tool=name, reason="validation")
            return JSONResponse({"tool": name, "error": f"invalid arguments: {exc}"}, status_code=400)
        # The call was well-formed but the tool raised: report it in-band (MCP
        # treats tool failures as error results, not transport errors).
        return JSONResponse({"tool": name, "is_error": True,
                             "error": f"{type(exc).__name__}: {exc}", "content": []})
    return JSONResponse(_serialize_tool_result(name, result))


def register_metrics(loader, app) -> None:
    """Declare counters and scrape-time gauges backed by loader/app state."""
    METRICS.declare("mcp_tool_calls_total", "Total tool invocations")
    METRICS.declare("mcp_tool_errors_total", "Tool invocations that raised (by reason)")
    # Phase E: a real histogram (explicit buckets) so the TSDB computes p50/p95/p99
    # via histogram_quantile, instead of a percentile faked in-process.
    if hasattr(METRICS, "declare_histogram"):
        METRICS.declare_histogram(
            "mcp_tool_duration_seconds",
            (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            "Tool execution wall-time")
    else:
        METRICS.declare("mcp_tool_duration_seconds", "Tool execution wall-time")
    METRICS.declare("mcp_reloads_total", "Module (re)loads that registered tools")
    METRICS.declare("mcp_load_failures_total", "Module loads that failed or yielded no tools")
    METRICS.declare("mcp_authz_evaluations_total", "Total authorization policy evaluations")
    METRICS.declare("mcp_authz_denials_total", "Total authorization policy denials")
    METRICS.declare("mcp_authz_shadow_denials_total", "Authorization would-denials in shadow mode (§19)")
    METRICS.gauge("mcp_ready", lambda: 1.0 if getattr(app.state, "ready", False) else 0.0,

                  "1 once the initial tool load has completed")
    METRICS.gauge("mcp_tools_loaded", lambda: loader.stats()["total_tools"], "Currently registered tools")
    METRICS.gauge("mcp_modules_failed", lambda: loader.stats()["failed_modules"], "Modules currently failing to load")
    METRICS.gauge("mcp_tools_disabled", lambda: loader.stats()["disabled_tools"], "Disabled tools")
    onboarding = getattr(app.state, "onboarding", None)
    if onboarding is not None:
        METRICS.declare("mcp_tool_onboards_total", "Onboarding actions by result (onboarded/pending/approved/rejected)")
        METRICS.gauge("mcp_tools_pending", onboarding.pending_count, "Submissions currently held pending review")

    # Phase E: analytics plugin self-metrics as scrapable series, so silent data
    # loss (dropped events, drain lag, tripped breaker) is alertable, not just
    # visible on the dashboard JSON.
    analytics = getattr(app.state, "analytics", None)
    if analytics is not None:
        METRICS.gauge("mcp_analytics_queue_depth", lambda: float(analytics.queue_depth),
                      "Analytics event queue depth (success + error lanes)")
        METRICS.gauge("mcp_analytics_events_dropped_total",
                      lambda: float(analytics.dropped_success + analytics.dropped_error),
                      "Analytics events dropped under backpressure")
        METRICS.gauge("mcp_analytics_drain_lag_seconds", lambda: float(analytics.drain_lag),
                      "Analytics background-drain lag")
        METRICS.gauge("mcp_analytics_sink_errors_total", lambda: float(analytics.sink_errors),
                      "Analytics sink write failures")
        METRICS.gauge("mcp_analytics_breaker_open", lambda: 1.0 if analytics.breaker_open else 0.0,
                      "1 when the analytics sink breaker is open")


async def _admin_resync(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    # No remote tool source: nothing to sync, the filesystem watcher already
    # picks up local edits. Kept for parity with the admin API shape.
    return JSONResponse({"status": "skipped", "reason": "no remote tool source configured"}, status_code=409)


async def _admin_reload(request):
    if (denied := await admin_denied(request)) is not None:

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
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    name = request.path_params["name"]
    if not st.loader.disable(name):
        return JSONResponse({"error": f"unknown tool {name!r}"}, status_code=404)
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "disabled", "tool": name})


async def _admin_enable(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    name = request.path_params["name"]
    module = st.loader.enable(name)
    if module:
        st.loader.load_path(st.loader.file_for_module(module))
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "enabled", "tool": name, "reloaded": bool(module)})


# -- tool onboarding: the replacement for the removed Azure sync path -------
async def _admin_tools_onboard(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    if not st.onboarding.enabled:
        return JSONResponse({"error": "tool onboarding is disabled (MCP_TOOL_ONBOARD_ENABLED=false)"},
                            status_code=503)

    # Guard against an oversized body before buffering the whole thing.
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > MAX_SOURCE_BYTES + 65536:
        return JSONResponse({"error": "request body too large"}, status_code=413)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "request body must be JSON"}, status_code=400)

    name = body.get("name")
    source = body.get("source")
    requirements = body.get("requirements") or []
    overwrite = bool(body.get("overwrite", False))
    auto_heal = bool(body.get("auto_heal", True))
    if not isinstance(name, str) or not isinstance(source, str) or not isinstance(requirements, list):
        return JSONResponse(
            {"error": "expected {\"name\": str, \"source\": str, \"requirements\"?: [str, ...], \"overwrite\"?: bool, \"auto_heal\"?: bool}"},
            status_code=400,
        )
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return JSONResponse({"error": f"source exceeds the {MAX_SOURCE_BYTES}-byte limit"}, status_code=413)
    if len(requirements) > MAX_REQUIREMENTS:
        return JSONResponse({"error": f"too many requirements (max {MAX_REQUIREMENTS})"}, status_code=400)

    try:
        record = await st.onboarding.onboard(name, source, requirements, overwrite=overwrite, auto_heal=auto_heal)
    except OnboardingConflict as exc:
        return JSONResponse({"error": str(exc), "hint": "Set 'overwrite': true in your JSON request body to replace an existing tool."}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    await notify_tools_changed(st.mcp)
    return JSONResponse(record, status_code=202 if record["status"] == "pending" else 201)


async def _admin_tools_validate_source(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "request body must be JSON"}, status_code=400)
    name = body.get("name")
    source = body.get("source")
    requirements = body.get("requirements") or []
    if not isinstance(source, str) or not isinstance(requirements, list):
        return JSONResponse({"error": "expected {\"source\": str, \"requirements\"?: [str, ...]}"}, status_code=400)
    res = st.onboarding.validate_source(source, requirements, name=name)
    return JSONResponse(res)


async def _admin_tools_revert(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    name = request.path_params["name"]
    try:
        record = await st.onboarding.revert(name)
        await notify_tools_changed(st.mcp)
        return JSONResponse(record)
    except KeyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def _admin_tools_accept_proposal(request):

    """Accept a dry-run proposal and onboard the tool immediately."""
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "request body must be JSON"}, status_code=400)
    name = body.get("name")
    source = body.get("source")
    requirements = body.get("requirements") or []
    overwrite = bool(body.get("overwrite", True))
    if not isinstance(name, str) or not isinstance(source, str):
        return JSONResponse({"error": "expected {\"name\": str, \"source\": str}"}, status_code=400)

    try:
        record = await st.onboarding.onboard(name, source, requirements, overwrite=overwrite, auto_heal=True)
        await notify_tools_changed(st.mcp)
        return JSONResponse(record, status_code=201)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def _admin_tools_auto_patch(request):
    """Auto-patch a tool that experienced a runtime error or syntax issue."""
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    name = request.path_params["name"]
    try:
        record = await st.onboarding.auto_patch_tool(name)
        await notify_tools_changed(st.mcp)
        return JSONResponse(record)
    except KeyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)





async def _admin_tools_pending_list(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    return JSONResponse({"pending": request.app.state.onboarding.list_pending()})


async def _admin_tools_pending_detail(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    name = request.path_params["name"]
    detail = request.app.state.onboarding.get_pending_detail(name)
    if detail is None:
        return JSONResponse({"error": f"no pending tool named {name!r}"}, status_code=404)
    return JSONResponse(detail)


async def _admin_tools_pending_approve(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    name = request.path_params["name"]
    try:
        record = await st.onboarding.approve(name)
    except KeyError:
        return JSONResponse({"error": f"no pending tool named {name!r}"}, status_code=404)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    await notify_tools_changed(st.mcp)
    return JSONResponse(record)


async def _admin_tools_pending_reject(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    name = request.path_params["name"]
    if not request.app.state.onboarding.reject(name):
        return JSONResponse({"error": f"no pending tool named {name!r}"}, status_code=404)
    return JSONResponse({"status": "rejected", "tool": name})


# -- federation: list / call tools on remote MCP servers ---------------------
async def _upstreams_list(request):
    st = request.app.state
    if (denied := await enforce(request, st.upstream_auth)) is not None:
        return denied
    return JSONResponse({"upstreams": st.upstreams.list()})


async def _upstream_tools(request):
    st = request.app.state
    if (denied := await enforce(request, st.upstream_auth)) is not None:
        return denied
    server = request.path_params["server"]
    try:
        tools = await st.upstreams.list_tools(server, health_checker=getattr(st, "upstream_health_checker", None))
    except KeyError:
        return JSONResponse({"error": f"unknown upstream {server!r}"}, status_code=404)
    except UpstreamError as exc:
        sc = 503 if "UNHEALTHY" in str(exc) else 502
        return JSONResponse({"error": str(exc)}, status_code=sc)

    store = getattr(st, "tenancy_store", None)
    evaluator = getattr(st, "policy_evaluator", None)
    principal = getattr(request.state, "principal", None)
    if store is not None:
        from .tenancy.scoping import filter_tools_for_principal
        tools = await filter_tools_for_principal(store, evaluator, principal, tools)

    return JSONResponse({"upstream": server, "tools": tools})



async def _upstream_tool_call(request):
    st = request.app.state
    if (denied := await enforce(request, st.upstream_auth)) is not None:
        return denied
    server = request.path_params["server"]
    name = request.path_params["name"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    arguments = body.get("arguments", {}) if isinstance(body, dict) else {}
    if not isinstance(arguments, dict):
        return JSONResponse({"error": '"arguments" must be a JSON object'}, status_code=400)
    try:
        result = await st.upstreams.call_tool(server, name, arguments, health_checker=getattr(st, "upstream_health_checker", None))
    except KeyError:
        return JSONResponse({"error": f"unknown upstream {server!r}"}, status_code=404)
    except UpstreamError as exc:
        sc = 503 if "UNHEALTHY" in str(exc) else 502
        return JSONResponse({"error": str(exc)}, status_code=sc)
    return JSONResponse(result)


async def _admin_upstream_add(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    if not st.upstreams.allow_runtime:
        return JSONResponse({"error": "runtime upstream changes are disabled (MCP_UPSTREAM_ALLOW_RUNTIME=false)"},
                            status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "request body must be JSON"}, status_code=400)
    name, url = body.get("name"), body.get("url")
    if not isinstance(name, str) or not isinstance(url, str) or not name or not url:
        return JSONResponse({"error": 'expected {"name": str, "url": str}'}, status_code=400)
    st.upstreams.add(
        name,
        url,
        token=body.get("token"),
        api_key=body.get("api_key"),
        header_name=body.get("header_name"),
        auth_type=body.get("auth_type"),
        headers=body.get("headers"),

        token_url=body.get("token_url"),
        client_id=body.get("client_id"),
        client_secret=body.get("client_secret"),
    )
    return JSONResponse({"status": "added", "upstream": name}, status_code=201)




async def _admin_upstream_remove(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    if not st.upstreams.allow_runtime:
        return JSONResponse({"error": "runtime upstream changes are disabled"}, status_code=403)
    server = request.path_params["server"]
    if not st.upstreams.remove(server):
        return JSONResponse({"error": f"unknown upstream {server!r}"}, status_code=404)
    return JSONResponse({"status": "removed", "upstream": server})


# -- OpenAPI Plugin management endpoints ------------------------------------
async def _admin_openapi_register(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    mgr = getattr(st, "openapi_manager", None)
    if not mgr:
        return JSONResponse({"error": "OpenAPI plugin manager is not enabled"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "request body must be JSON"}, status_code=400)

    collection_id = body.get("collection_id")
    spec_input = body.get("spec")
    if not isinstance(collection_id, str) or not isinstance(spec_input, str) or not collection_id or not spec_input:
        return JSONResponse({"error": 'expected {"collection_id": str, "spec": str}'}, status_code=400)

    auth_config = {
        "auth_type": body.get("auth_type"),
        "api_key": body.get("api_key"),
        "header_name": body.get("header_name"),
        "token": body.get("token"),
        "headers": body.get("headers") or {},
    }


    try:
        res = mgr.register_spec_collection(
            collection_id,
            spec_input,
            base_url_override=body.get("base_url"),
            auth_config=auth_config,
        )
        await notify_tools_changed(st.mcp)
        return JSONResponse(res, status_code=201)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def _admin_openapi_specs(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    mgr = getattr(st, "openapi_manager", None)
    if not mgr:
        return JSONResponse({"collections": []})
    cols = []
    for col_id, record in mgr.collections.items():
        cols.append({
            "collection_id": col_id,
            "base_url": record.get("base_url"),
            "tools_count": len(record.get("tool_names", [])),
            "tool_names": record.get("tool_names", []),
        })
    return JSONResponse({"collections": cols})


async def _admin_openapi_remove(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    mgr = getattr(st, "openapi_manager", None)
    if not mgr:
        return JSONResponse({"error": "OpenAPI plugin manager is not enabled"}, status_code=503)
    collection_id = request.path_params["collection_id"]
    if not mgr.remove_spec_collection(collection_id):
        return JSONResponse({"error": f"unknown OpenAPI collection {collection_id!r}"}, status_code=404)
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "removed", "collection_id": collection_id})



async def _admin_logs(request):
    if (denied := await admin_denied(request)) is not None:

        return denied
    st = request.app.state
    category_param = request.path_params.get("log_category")
    log_type = (category_param or request.query_params.get("type") or "server").lower()
    try:
        limit = min(int(request.query_params.get("limit", 100)), 1000)
    except ValueError:
        limit = 100



    level_filter = request.query_params.get("level", "").upper()
    trace_filter = request.query_params.get("trace_id", "")
    search = request.query_params.get("search", "").lower()
    base_dir = getattr(st.onboarding, "tools_dir", Path(".")).parent
    logs_dir = base_dir / "logs"
    server_log_path = getattr(st, "log_file_path", None) or (logs_dir / "mcp_server.json.log")


    files_to_read = []
    if log_type in {"server", "all"}:
        files_to_read.append(("server", server_log_path))
    if log_type in {"audit", "all"}:
        audit_path = getattr(st.onboarding, "audit_log_path", None)
        if not audit_path or not Path(audit_path).exists():
            audit_path = logs_dir / "onboard_audit.jsonl"
        else:
            audit_path = Path(audit_path)
        files_to_read.append(("audit", audit_path))
    if log_type in {"unauthorized", "all"}:
        unauth_path = getattr(st, "unauthorized_log_path", None) or (logs_dir / "unauthorized_access.json.log")
        files_to_read.append(("unauthorized", unauth_path))




    results = []
    for category, file_path in files_to_read:
        if not file_path or not file_path.exists():
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").strip().splitlines()
            for idx, line in enumerate(reversed(lines)):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    record = {"raw": line}

                if isinstance(record.get("raw"), str) and record["raw"].startswith("{"):
                    with contextlib.suppress(Exception):
                        record = json.loads(record["raw"])

                rec_level = str(record.get("level", "")).upper()
                rec_trace = str(record.get("trace_id", ""))

                if level_filter and rec_level != level_filter:
                    continue
                if trace_filter and rec_trace != trace_filter:
                    continue
                if search and search not in line.lower():
                    continue

                record.setdefault("log_type", category)
                results.append(record)

                if len(results) >= limit:
                    break

        except Exception as exc:
            results.append({"error": f"failed to read {category} log: {exc}"})

    return JSONResponse({
        "log_type": log_type,
        "count": len(results),
        "logs": results
    })



async def _whoami(request):
    denied = await enforce(request, "none")
    if denied:
        return denied
    principal = getattr(request.state, "principal", None)
    if principal is None:
        from .identity import create_anonymous_principal
        principal = create_anonymous_principal()
    return JSONResponse(principal.to_dict())


async def _auth_signup(request):
    auth_service = getattr(request.app.state, "supabase_auth", None)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    email = (body.get("email") or body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    metadata = body.get("metadata") or body.get("data")
    if not email or not password:
        return JSONResponse({"error": "Email and password are required"}, status_code=400)

    if auth_service:
        try:
            res = await auth_service.sign_up(email, password, metadata=metadata)
            return JSONResponse(res, status_code=201)
        except Exception as exc:
            log.warning("Supabase signup failed/unreachable (%s), using local dev fallback", exc)

    # Local Dev Mode Fallback (when Supabase is unconfigured or unreachable)
    admin_token = getattr(request.app.state, "admin_token", "") or "mysecretadmin"
    username = email.split("@")[0] if "@" in email else email
    return JSONResponse({
        "message": "User registered (Local Dev Mode)",
        "access_token": admin_token,
        "refresh_token": f"refresh-{username}",
        "user": {
            "sub": username,
            "username": username,
            "email": email,
            "roles": ["guild_master", "admin"]
        }
    }, status_code=201)


async def _auth_signin(request):
    auth_service = getattr(request.app.state, "supabase_auth", None)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    username = (body.get("username") or body.get("email") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not password:
        return JSONResponse({"error": "Email/username and password are required"}, status_code=400)

    if auth_service:
        try:
            res = await auth_service.sign_in(username, password)
            return JSONResponse(res, status_code=200)
        except Exception as exc:
            log.warning("Supabase signin failed/unreachable (%s), using local dev fallback", exc)

    # Local Dev Mode Fallback (when Supabase is unconfigured or unreachable)
    admin_token = getattr(request.app.state, "admin_token", "") or "mysecretadmin"
    return JSONResponse({
        "access_token": admin_token,
        "refresh_token": f"refresh-{username}",
        "user": {
            "sub": username,
            "username": username,
            "email": f"{username}@citadel.local",
            "roles": ["guild_master", "admin"],
            "permissions": ["*"]
        }
    }, status_code=200)



async def _auth_refresh(request):
    auth_service = getattr(request.app.state, "supabase_auth", None)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    refresh_token = (body.get("refresh_token") or "").strip()
    if not refresh_token:
        return JSONResponse({"error": "refresh_token is required"}, status_code=400)

    if auth_service:
        try:
            res = await auth_service.refresh_token(refresh_token)
            return JSONResponse(res, status_code=200)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    admin_token = getattr(request.app.state, "admin_token", "") or "mysecretadmin"
    return JSONResponse({
        "access_token": admin_token,
        "refresh_token": refresh_token
    }, status_code=200)



async def _auth_forgot_password(request):
    auth_service = getattr(request.app.state, "supabase_auth", None)
    if not auth_service:
        return JSONResponse({"error": "Supabase Auth not configured"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    email = (body.get("email") or "").strip()
    if not email:
        return JSONResponse({"error": "email is required"}, status_code=400)
    res = await auth_service.recover_password(email)
    return JSONResponse(res, status_code=200)


def _invalidate_rbac_cache(request, *, principal_id=None, org_id=None, full=False):
    """Bust cached authorization decisions after a tenancy mutation (§18.2/§21.4).

    A stale decision must not outlive the write that changed it. Membership
    changes target one principal; grant/role changes are broad (clear all).
    """
    evaluator = getattr(request.app.state, "policy_evaluator", None)
    cache = getattr(evaluator, "cache", None) if evaluator else None
    if cache is None:
        return
    if full or (principal_id is None and org_id is None):
        cache.clear()
    else:
        cache.invalidate(principal_id=principal_id, org_id=org_id)


async def _admin_create_org(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    org_id = (body.get("org_id") or "").strip()
    name = (body.get("name") or "").strip()
    if not org_id or not name:
        return JSONResponse({"error": "org_id and name are required"}, status_code=400)
    org = await store.create_org(org_id, name, settings=body.get("settings"))
    return JSONResponse({"org_id": org.org_id, "name": org.name, "status": org.status, "created_at": org.created_at}, status_code=201)


async def _admin_list_orgs(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    orgs = await store.list_orgs()
    return JSONResponse([{"org_id": o.org_id, "name": o.name, "status": o.status, "created_at": o.created_at} for o in orgs])


async def _admin_delete_org(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    if not org_id:
        return JSONResponse({"error": "org parameter required"}, status_code=400)
    ok = await store.delete_org(org_id)
    if not ok:
        return JSONResponse({"error": "Organization not found"}, status_code=404)
    # Deleting an org cascades memberships -> drop cached decisions for that org.
    _invalidate_rbac_cache(request, org_id=org_id)
    return JSONResponse({"message": f"Organization {org_id} deleted successfully"})


async def _admin_create_workspace(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    workspace_id = (body.get("workspace_id") or "").strip()
    name = (body.get("name") or "").strip()
    if not workspace_id or not name or not org_id:
        return JSONResponse({"error": "workspace_id, org_id, and name are required"}, status_code=400)
    ws = await store.create_workspace(workspace_id, org_id, name)
    return JSONResponse({"workspace_id": ws.workspace_id, "org_id": ws.org_id, "name": ws.name, "created_at": ws.created_at}, status_code=201)


async def _admin_list_workspaces(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    if not org_id:
        return JSONResponse({"error": "org parameter required"}, status_code=400)
    wss = await store.list_workspaces(org_id)
    return JSONResponse([{"workspace_id": w.workspace_id, "org_id": w.org_id, "name": w.name, "created_at": w.created_at} for w in wss])


async def _admin_bind_member(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    principal_id = (body.get("principal_id") or body.get("subject") or "").strip()
    role = (body.get("role") or "").strip()
    workspace_id = body.get("workspace_id")
    if not principal_id or not role or not org_id:
        return JSONResponse({"error": "principal_id, org_id, and role are required"}, status_code=400)
    mem = await store.bind_member(principal_id, org_id, role, workspace_id)
    # A role change alters this principal's permissions -> drop their cached decisions.
    _invalidate_rbac_cache(request, principal_id=principal_id)
    return JSONResponse({"principal_id": mem.principal_id, "org_id": mem.org_id, "role": mem.role, "workspace_id": mem.workspace_id}, status_code=201)


async def _admin_list_members(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    if not org_id:
        return JSONResponse({"error": "org parameter required"}, status_code=400)
    mems = await store.list_org_members(org_id)
    return JSONResponse([{"principal_id": m.principal_id, "org_id": m.org_id, "role": m.role, "workspace_id": m.workspace_id} for m in mems])


async def _admin_add_tool_grant(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    scope_type = (body.get("scope_type") or "org").strip()
    scope_id = (body.get("scope_id") or org_id).strip()
    effect = (body.get("effect") or "allow").strip()
    match_type = (body.get("match_type") or "exact").strip()
    match_value = (body.get("match_value") or "").strip()
    if not match_value:
        return JSONResponse({"error": "match_value is required"}, status_code=400)
    grant = await store.add_tool_grant(scope_type, scope_id, effect, match_type, match_value)
    # Grants can affect many principals (org/role/tag scope) -> clear all decisions.
    _invalidate_rbac_cache(request, full=True)
    return JSONResponse({
        "id": grant.id,
        "scope_type": grant.scope_type,
        "scope_id": grant.scope_id,
        "effect": grant.effect,
        "match_type": grant.match_type,
        "match_value": grant.match_value,
        "created_at": grant.created_at,
    }, status_code=201)


async def _admin_list_tool_grants(request):
    denied = await enforce(request, "admin")
    if denied:
        return denied
    store = getattr(request.app.state, "tenancy_store", None)
    if not store:
        return JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)
    org_id = request.path_params.get("org")
    grants = await store.list_tool_grants(scope_id=org_id)
    return JSONResponse([{
        "id": g.id,
        "scope_type": g.scope_type,
        "scope_id": g.scope_id,
        "effect": g.effect,
        "match_type": g.match_type,
        "match_value": g.match_value,
        "created_at": g.created_at,
    } for g in grants])




def feature_routes() -> List[Route]:
    return [
        Route(HEALTH_PATH, _health, methods=["GET"]),
        Route(READY_PATH, _readyz, methods=["GET"]),
        Route("/whoami", _whoami, methods=["GET"]),
        Route("/auth/signup", _auth_signup, methods=["POST"]),
        Route("/auth/signin", _auth_signin, methods=["POST"]),
        Route("/auth/refresh", _auth_refresh, methods=["POST"]),
        Route("/auth/forgot-password", _auth_forgot_password, methods=["POST"]),
        Route("/docs", _swagger_ui, methods=["GET"]),
        Route("/swagger", _swagger_ui, methods=["GET"]),
        Route("/openapi.json", _openapi_json, methods=["GET"]),
        Route("/openapi.yaml", _openapi_yaml, methods=["GET"]),
        Route("/status", _status, methods=["GET"]),
        Route("/tools", _tools_catalog, methods=["GET"]),
        Route("/tools/{name}/call", _tool_call, methods=["POST"]),
        Route("/metrics", _metrics, methods=["GET"]),
        Route("/admin/resync", _admin_resync, methods=["POST"]),
        Route("/admin/logs", _admin_logs, methods=["GET"]),
        Route("/admin/logs/{log_category}", _admin_logs, methods=["GET"]),

        Route("/admin/reload/{name}", _admin_reload, methods=["POST"]),

        Route("/admin/tool/{name}/disable", _admin_disable, methods=["POST"]),
        Route("/admin/tool/{name}/enable", _admin_enable, methods=["POST"]),
        Route("/admin/tools/onboard", _admin_tools_onboard, methods=["POST"]),
        Route("/admin/tools/onboard/accept_proposal", _admin_tools_accept_proposal, methods=["POST"]),
        Route("/admin/tools/validate_source", _admin_tools_validate_source, methods=["POST"]),
        Route("/admin/tools/{name}/revert", _admin_tools_revert, methods=["POST"]),
        Route("/admin/tools/{name}/auto_patch", _admin_tools_auto_patch, methods=["POST"]),
        Route("/admin/tools/pending", _admin_tools_pending_list, methods=["GET"]),



        Route("/admin/tools/pending/{name}", _admin_tools_pending_detail, methods=["GET"]),
        Route("/admin/tools/pending/{name}/approve", _admin_tools_pending_approve, methods=["POST"]),
        Route("/admin/tools/pending/{name}/reject", _admin_tools_pending_reject, methods=["POST"]),
        # OpenAPI Spec plugin management
        Route("/admin/openapi/register", _admin_openapi_register, methods=["POST"]),
        Route("/admin/openapi/specs", _admin_openapi_specs, methods=["GET"]),
        Route("/admin/openapi/{collection_id}/remove", _admin_openapi_remove, methods=["POST"]),
        # Federation: remote MCP servers
        Route("/mcp/upstreams", _upstreams_list, methods=["GET"]),
        Route("/mcp/upstreams/{server}/tools", _upstream_tools, methods=["GET"]),
        Route("/mcp/upstreams/{server}/tools/{name}/call", _upstream_tool_call, methods=["POST"]),
        Route("/admin/mcp/upstreams", _admin_upstream_add, methods=["POST"]),
        Route("/admin/mcp/upstreams/{server}/remove", _admin_upstream_remove, methods=["POST"]),
        # Admin Tenancy & RBAC (Phase 1)
        Route("/admin/orgs", _admin_create_org, methods=["POST"]),
        Route("/admin/orgs", _admin_list_orgs, methods=["GET"]),
        Route("/admin/orgs/{org}", _admin_delete_org, methods=["DELETE"]),
        Route("/admin/orgs/{org}/workspaces", _admin_create_workspace, methods=["POST"]),
        Route("/admin/orgs/{org}/workspaces", _admin_list_workspaces, methods=["GET"]),
        Route("/admin/orgs/{org}/members", _admin_bind_member, methods=["POST"]),
        Route("/admin/orgs/{org}/members", _admin_list_members, methods=["GET"]),
        Route("/admin/orgs/{org}/tool-grants", _admin_add_tool_grant, methods=["POST"]),
        Route("/admin/orgs/{org}/tool-grants", _admin_list_tool_grants, methods=["GET"]),
    ]




