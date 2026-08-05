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


def _load_openapi_spec() -> dict:
    spec_path = Path(__file__).resolve().parent.parent.parent / "openapi" / "openapi.yaml"
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
    return JSONResponse({"tools": st.loader.catalog()})


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
            return JSONResponse({"tool": name, "error": f"invalid arguments: {exc}"}, status_code=400)
        # The call was well-formed but the tool raised: report it in-band (MCP
        # treats tool failures as error results, not transport errors).
        return JSONResponse({"tool": name, "is_error": True,
                             "error": f"{type(exc).__name__}: {exc}", "content": []})
    return JSONResponse(_serialize_tool_result(name, result))


def register_metrics(loader, app) -> None:
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
    onboarding = getattr(app.state, "onboarding", None)
    if onboarding is not None:
        METRICS.declare("mcp_tool_onboards_total", "Onboarding actions by result (onboarded/pending/approved/rejected)")
        METRICS.gauge("mcp_tools_pending", onboarding.pending_count, "Submissions currently held pending review")


async def _admin_resync(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    # No remote tool source: nothing to sync, the filesystem watcher already
    # picks up local edits. Kept for parity with the admin API shape.
    return JSONResponse({"status": "skipped", "reason": "no remote tool source configured"}, status_code=409)


async def _admin_reload(request):
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
        return denied
    st = request.app.state
    name = request.path_params["name"]
    if not st.loader.disable(name):
        return JSONResponse({"error": f"unknown tool {name!r}"}, status_code=404)
    await notify_tools_changed(st.mcp)
    return JSONResponse({"status": "disabled", "tool": name})


async def _admin_enable(request):
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
        return denied
    return JSONResponse({"pending": request.app.state.onboarding.list_pending()})


async def _admin_tools_pending_detail(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    name = request.path_params["name"]
    detail = request.app.state.onboarding.get_pending_detail(name)
    if detail is None:
        return JSONResponse({"error": f"no pending tool named {name!r}"}, status_code=404)
    return JSONResponse(detail)


async def _admin_tools_pending_approve(request):
    if (denied := admin_denied(request)) is not None:
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
    if (denied := admin_denied(request)) is not None:
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
        tools = await st.upstreams.list_tools(server)
    except KeyError:
        return JSONResponse({"error": f"unknown upstream {server!r}"}, status_code=404)
    except UpstreamError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
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
        result = await st.upstreams.call_tool(server, name, arguments)
    except KeyError:
        return JSONResponse({"error": f"unknown upstream {server!r}"}, status_code=404)
    except UpstreamError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse(result)


async def _admin_upstream_add(request):
    if (denied := admin_denied(request)) is not None:
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
        return JSONResponse({"error": 'expected {"name": str, "url": str, "token"?: str}'}, status_code=400)
    st.upstreams.add(name, url, body.get("token"))
    return JSONResponse({"status": "added", "upstream": name}, status_code=201)


async def _admin_upstream_remove(request):
    if (denied := admin_denied(request)) is not None:
        return denied
    st = request.app.state
    if not st.upstreams.allow_runtime:
        return JSONResponse({"error": "runtime upstream changes are disabled"}, status_code=403)
    server = request.path_params["server"]
    if not st.upstreams.remove(server):
        return JSONResponse({"error": f"unknown upstream {server!r}"}, status_code=404)
    return JSONResponse({"status": "removed", "upstream": server})


async def _admin_logs(request):
    if (denied := admin_denied(request)) is not None:
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



def feature_routes() -> List[Route]:
    return [
        Route(HEALTH_PATH, _health, methods=["GET"]),
        Route(READY_PATH, _readyz, methods=["GET"]),
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
        # Federation: remote MCP servers
        Route("/mcp/upstreams", _upstreams_list, methods=["GET"]),
        Route("/mcp/upstreams/{server}/tools", _upstream_tools, methods=["GET"]),
        Route("/mcp/upstreams/{server}/tools/{name}/call", _upstream_tool_call, methods=["POST"]),
        Route("/admin/mcp/upstreams", _admin_upstream_add, methods=["POST"]),
        Route("/admin/mcp/upstreams/{server}/remove", _admin_upstream_remove, methods=["POST"]),
    ]
