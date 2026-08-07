"""Typed FastAPI routes for the admin tenancy/RBAC endpoints and tool execution.

This is the first batch converted from plain Starlette handlers to FastAPI path
operations, so they gain request validation and a documented OpenAPI schema.
They reuse the existing auth (``enforce``), cache-invalidation, and serialization
helpers, so status codes and response bodies match the original handlers exactly.
The plain equivalents are skipped in app._register_routes to avoid duplication.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from .api_models import (
    AcceptProposalRequest,
    MemberBind,
    MemberOut,
    OnboardRequest,
    OrgCreate,
    OrgOut,
    ToolCallRequest,
    ToolCallResult,
    ToolGrantCreate,
    ToolGrantOut,
    ValidateSourceRequest,
    WorkspaceCreate,
    WorkspaceOut,
)
from .security import enforce

# Paths served here — app._register_routes skips these so the plain handlers in
# routes.py don't double-register them.
TYPED_PATHS = {
    "/admin/orgs",
    "/admin/orgs/{org}",
    "/admin/orgs/{org}/workspaces",
    "/admin/orgs/{org}/members",
    "/admin/orgs/{org}/tool-grants",
    "/tools/{name}/call",
    "/admin/tools/onboard",
    "/admin/tools/onboard/accept_proposal",
    "/admin/tools/validate_source",
}

router = APIRouter()

_STORE_UNAVAILABLE = JSONResponse({"error": "TenancyStore not initialized"}, status_code=503)


def _store(request: Request):
    return getattr(request.app.state, "tenancy_store", None)


def _invalidate(request: Request, **kwargs):
    # Imported lazily to avoid a circular import at module load.
    from .routes import _invalidate_rbac_cache
    _invalidate_rbac_cache(request, **kwargs)


# --- Organizations ---------------------------------------------------------
@router.post("/admin/orgs", response_model=OrgOut, status_code=201, tags=["admin: tenancy"])
async def create_org(body: OrgCreate, request: Request):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    org = await store.create_org(body.org_id, body.name, settings=body.settings)
    return OrgOut(org_id=org.org_id, name=org.name, status=org.status, created_at=org.created_at)


@router.get("/admin/orgs", response_model=List[OrgOut], tags=["admin: tenancy"])
async def list_orgs(request: Request, limit: int = 100, offset: int = 0):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    orgs = await store.list_orgs(limit=limit, offset=offset)
    return [OrgOut(org_id=o.org_id, name=o.name, status=o.status, created_at=o.created_at) for o in orgs]


@router.delete("/admin/orgs/{org}", tags=["admin: tenancy"])
async def delete_org(org: str, request: Request):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    if not await store.delete_org(org):
        return JSONResponse({"error": "Organization not found"}, status_code=404)
    _invalidate(request, org_id=org)
    return {"message": f"Organization {org} deleted successfully"}


# --- Workspaces ------------------------------------------------------------
@router.post("/admin/orgs/{org}/workspaces", response_model=WorkspaceOut, status_code=201, tags=["admin: tenancy"])
async def create_workspace(org: str, body: WorkspaceCreate, request: Request):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    ws = await store.create_workspace(body.workspace_id, org, body.name)
    return WorkspaceOut(workspace_id=ws.workspace_id, org_id=ws.org_id, name=ws.name, created_at=ws.created_at)


@router.get("/admin/orgs/{org}/workspaces", response_model=List[WorkspaceOut], tags=["admin: tenancy"])
async def list_workspaces(org: str, request: Request, limit: int = 100, offset: int = 0):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    wss = await store.list_workspaces(org, limit=limit, offset=offset)
    return [WorkspaceOut(workspace_id=w.workspace_id, org_id=w.org_id, name=w.name, created_at=w.created_at) for w in wss]


# --- Members ---------------------------------------------------------------
@router.post("/admin/orgs/{org}/members", response_model=MemberOut, status_code=201, tags=["admin: tenancy"])
async def bind_member(org: str, body: MemberBind, request: Request):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    principal_id = body.resolved_principal()
    if not principal_id:
        return JSONResponse({"error": "principal_id (or subject) and role are required"}, status_code=400)
    mem = await store.bind_member(principal_id, org, body.role, body.workspace_id)
    _invalidate(request, principal_id=principal_id)
    return MemberOut(principal_id=mem.principal_id, org_id=mem.org_id, role=mem.role, workspace_id=mem.workspace_id)


@router.get("/admin/orgs/{org}/members", response_model=List[MemberOut], tags=["admin: tenancy"])
async def list_members(org: str, request: Request, limit: int = 100, offset: int = 0):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    mems = await store.list_org_members(org, limit=limit, offset=offset)
    return [MemberOut(principal_id=m.principal_id, org_id=m.org_id, role=m.role, workspace_id=m.workspace_id) for m in mems]


# --- Tool grants -----------------------------------------------------------
@router.post("/admin/orgs/{org}/tool-grants", response_model=ToolGrantOut, status_code=201, tags=["admin: tenancy"])
async def add_tool_grant(org: str, body: ToolGrantCreate, request: Request):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    grant = await store.add_tool_grant(
        body.scope_type, (body.scope_id or org), body.effect, body.match_type, body.match_value
    )
    _invalidate(request, full=True)
    return ToolGrantOut(
        id=grant.id, scope_type=grant.scope_type, scope_id=grant.scope_id, effect=grant.effect,
        match_type=grant.match_type, match_value=grant.match_value, created_at=grant.created_at,
    )


@router.get("/admin/orgs/{org}/tool-grants", response_model=List[ToolGrantOut], tags=["admin: tenancy"])
async def list_tool_grants(org: str, request: Request):
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    store = _store(request)
    if store is None:
        return _STORE_UNAVAILABLE
    grants = await store.list_tool_grants(scope_id=org)
    return [
        ToolGrantOut(
            id=g.id, scope_type=g.scope_type, scope_id=g.scope_id, effect=g.effect,
            match_type=g.match_type, match_value=g.match_value, created_at=g.created_at,
        )
        for g in grants
    ]


# --- Tool onboarding -------------------------------------------------------
@router.post("/admin/tools/onboard", status_code=201, tags=["admin: onboarding"])
async def onboard_tool(body: OnboardRequest, request: Request):
    """Onboard a tool from source + pip requirements. Returns 201 (installed) or
    202 (held pending review); 409 on a name conflict without overwrite."""
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    st = request.app.state
    if not st.onboarding.enabled:
        return JSONResponse(
            {"error": "tool onboarding is disabled (MCP_TOOL_ONBOARD_ENABLED=false)"}, status_code=503
        )
    from .onboarding import MAX_REQUIREMENTS, MAX_SOURCE_BYTES, OnboardingConflict
    from .notifications import notify_tools_changed

    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > MAX_SOURCE_BYTES + 65536:
        return JSONResponse({"error": "request body too large"}, status_code=413)
    if len(body.source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return JSONResponse({"error": f"source exceeds the {MAX_SOURCE_BYTES}-byte limit"}, status_code=413)
    if len(body.requirements) > MAX_REQUIREMENTS:
        return JSONResponse({"error": f"too many requirements (max {MAX_REQUIREMENTS})"}, status_code=400)

    try:
        record = await st.onboarding.onboard(
            body.name, body.source, body.requirements, overwrite=body.overwrite, auto_heal=body.auto_heal
        )
    except OnboardingConflict as exc:
        return JSONResponse(
            {"error": str(exc), "hint": "Set 'overwrite': true in your JSON request body to replace an existing tool."},
            status_code=409,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    await notify_tools_changed(st.mcp)
    return JSONResponse(record, status_code=202 if record.get("status") == "pending" else 201)


@router.post("/admin/tools/validate_source", tags=["admin: onboarding"])
async def validate_source(body: ValidateSourceRequest, request: Request):
    """Dry-run: syntax/dependency check + autofix hints without installing."""
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    res = request.app.state.onboarding.validate_source(body.source, body.requirements, name=body.name)
    return JSONResponse(res)


@router.post("/admin/tools/onboard/accept_proposal", status_code=201, tags=["admin: onboarding"])
async def accept_proposal(body: AcceptProposalRequest, request: Request):
    """Accept a dry-run proposal and onboard the tool immediately."""
    if (denied := await enforce(request, "admin")) is not None:
        return denied
    st = request.app.state
    from .notifications import notify_tools_changed
    try:
        record = await st.onboarding.onboard(
            body.name, body.source, body.requirements, overwrite=body.overwrite, auto_heal=True
        )
        await notify_tools_changed(st.mcp)
        return JSONResponse(record, status_code=201)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# --- Tool execution --------------------------------------------------------
@router.post("/tools/{name}/call", response_model=ToolCallResult, tags=["tools"])
async def call_tool(name: str, body: ToolCallRequest, request: Request):
    """Execute a registered tool. Mirrors the MCP tools/call semantics: a tool
    that raises is reported in-band (200 with is_error=true); unknown/disabled is
    404; malformed arguments are 400."""
    if (denied := await enforce(request, request.app.state.tool_call_auth)) is not None:
        return denied
    tool = request.app.state.loader.get_tool(name)
    if tool is None:
        return JSONResponse({"error": f"unknown or disabled tool {name!r}"}, status_code=404)

    from .routes import _ToolValidationError, _serialize_tool_result
    try:
        result = await tool.run(body.arguments)
    except Exception as exc:
        if _ToolValidationError is not None and isinstance(exc, _ToolValidationError):
            return JSONResponse({"tool": name, "error": f"invalid arguments: {exc}"}, status_code=400)
        return JSONResponse(
            {"tool": name, "is_error": True, "error": f"{type(exc).__name__}: {exc}", "content": []}
        )
    return _serialize_tool_result(name, result)
