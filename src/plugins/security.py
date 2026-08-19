"""Authentication & authorization plumbing.

Three MCP auth modes (``MCP_AUTH_TYPE``): ``none`` | ``api_key`` | ``bearer_jwt``.
The admin API (``/admin/*``) is independently gated by ``MCP_ADMIN_TOKEN``
regardless of the MCP auth mode, and is disabled entirely when that token is
unset. All secret comparisons use ``hmac.compare_digest`` (constant-time).
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional, Tuple

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = logging.getLogger("MCP_logger")

HEALTH_PATH = "/healthz"
READY_PATH = "/readyz"
DOCS_PATHS = {"/docs", "/swagger", "/openapi.json", "/openapi.yaml", "/ui", "/static_ui", "/assets"}
EXEMPT_PATHS = {HEALTH_PATH, READY_PATH} | DOCS_PATHS




def build_mcp(ctx) -> Tuple[FastMCP, Optional[JWTVerifier]]:
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
            algorithm=getattr(ctx, "jwt_algorithm", "ES256"),
        )

        return FastMCP(name="Tool Server", auth=auth), auth
    return FastMCP(name="Tool Server"), None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Constant-time API-key check for the **MCP protocol endpoints** only
    (``/sse``, ``/messages``). FastMCP auths those itself in ``bearer_jwt`` mode
    but not in ``api_key`` mode, so this fills that gap. Every other route
    (health, admin, and the custom read/exec/upstream routes) enforces its own
    configurable policy via :func:`enforce`, so the middleware does not touch
    them — that's what makes per-route auth configurable."""

    def __init__(self, app, header: str, value: str, protected_prefixes=("/sse", "/messages")):
        super().__init__(app)
        self._header = header.lower()
        self._value = value
        # The MCP protocol path(s) depend on the transport: /sse + /messages for
        # SSE, /mcp for streamable HTTP. build_app passes the right ones.
        self._protected = tuple(protected_prefixes)

    async def dispatch(self, request, call_next):
        if request.url.path.startswith(self._protected):
            provided = request.headers.get(self._header, "").strip()
            if provided.lower().startswith("bearer "):
                provided = provided[7:].strip()
            admin_token = getattr(request.app.state, "admin_token", "")
            x_admin = request.headers.get("x-admin-token", "").strip()

            key_ok = self._value and hmac.compare_digest(provided, self._value)
            admin_ok = admin_token and (
                hmac.compare_digest(provided, admin_token)
                or (x_admin and hmac.compare_digest(x_admin, admin_token))
            )

            if not (key_ok or admin_ok):
                request.state.auth_failure_reason = "Invalid API Key header"
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def _api_key_ok(request) -> bool:
    principal = getattr(request.state, "principal", None)
    if principal is not None and (
        getattr(principal, "subject", "") == "admin-token"
        or "platform_superadmin" in getattr(principal, "roles", [])
    ):
        return True

    st = request.app.state
    header_name = getattr(st, "api_key_header", "authorization")
    provided = request.headers.get(header_name, "").strip()
    if provided.lower().startswith("bearer "):
        provided = provided[7:].strip()

    api_key_val = getattr(st, "api_key_value", "")
    if api_key_val and hmac.compare_digest(provided, api_key_val):
        return True

    admin_token = getattr(st, "admin_token", "")
    if admin_token and hmac.compare_digest(provided, admin_token):
        return True

    x_admin = request.headers.get("x-admin-token", "").strip()
    if admin_token and x_admin and hmac.compare_digest(x_admin, admin_token):
        return True

    request.state.auth_failure_reason = "Invalid API Key header"
    return False


async def _jwt_ok(request) -> bool:
    # 0. Fast-path: Return True if IdentityMiddleware already resolved an authenticated principal
    principal = getattr(request.state, "principal", None)
    if principal is not None and getattr(principal, "subject", "anonymous") != "anonymous":
        return True

    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        request.state.auth_failure_reason = "bearer_jwt mode active but JWT verifier not configured"
        return False                          # bearer_jwt configured but no verifier → fail closed
    authz = request.headers.get("authorization", "")
    token = authz[7:].strip() if authz.lower().startswith("bearer ") else ""
    if not token:
        request.state.auth_failure_reason = "Missing or malformed Authorization Bearer token"
        return False


    from .identity import token_cache, build_principal_from_claims, current_principal_var

    # 1. Check LRU Cache
    cached_principal = token_cache.get(token)
    if cached_principal is not None:
        request.state.principal = cached_principal
        current_principal_var.set(cached_principal)
        return True

    # 2. Verify via FastMCP / PyJWKClient verifier
    verified_token = await verifier.verify_token(token)
    if verified_token is None:
        request.state.auth_failure_reason = "Invalid or expired JWT token signature/claims"
        return False

    # Extract claims
    claims = getattr(verified_token, "claims", {}) or {}
    sub = getattr(verified_token, "subject", "") or claims.get("sub", "anonymous")
    iss = claims.get("iss") or getattr(request.app.state, "jwt_issuer", "") or "local"
    email = claims.get("email") or claims.get("user_metadata", {}).get("email", "")
    exp = claims.get("exp")
    superadmin_email = getattr(request.app.state, "superadmin_email", "")

    tenant_header_name = getattr(request.app.state, "tenant_header", "X-Tenant-Id")
    workspace_header_name = getattr(request.app.state, "workspace_header", "X-Workspace-Id")
    from .identity import sanitize_header_value
    active_org = sanitize_header_value(request.headers.get(tenant_header_name), "default")
    active_ws = sanitize_header_value(request.headers.get(workspace_header_name), "default")

    principal = build_principal_from_claims(
        issuer=iss,
        subject=sub,
        org_id=active_org,
        workspace_id=active_ws,
        email=email,
        superadmin_email=superadmin_email,
    )

    # Store in LRU cache with dynamic TTL (min(300, exp - now))
    token_cache.set(token, principal, exp_timestamp=exp)

    request.state.principal = principal
    current_principal_var.set(principal)
    return True



async def enforce(request, policy: str):
    """Apply a per-route auth policy. Returns a 401/403/503 JSONResponse when denied, else None."""
    if policy == "none":
        return None
    if policy == "admin":
        return await admin_denied(request)


    mode = getattr(request.app.state, "auth_type", "none")
    if mode == "api_key" and not _api_key_ok(request):
        request.state.auth_failure_reason = getattr(request.state, "auth_failure_reason", "Invalid API key")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if mode == "bearer_jwt" and not await _jwt_ok(request):
        request.state.auth_failure_reason = getattr(request.state, "auth_failure_reason", "Invalid or missing JWT token")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # Phase 2: RBAC Policy Engine Check if enabled
    rbac_enabled = getattr(request.app.state, "rbac_enabled", False)
    evaluator = getattr(request.app.state, "policy_evaluator", None)
    principal = getattr(request.state, "principal", None)

    if rbac_enabled and evaluator and principal:
        from metrics import METRICS
        METRICS.inc("mcp_authz_evaluations_total")

        path = request.url.path
        if "/call" in path:
            action = "tool:call"
            resource = request.path_params.get("name", "")
        elif "/tools" in path:
            action = "tool:list"
            resource = ""
        elif "/upstreams" in path:
            action = "upstream:call"
            resource = request.path_params.get("server", "")
        else:
            action = "tool:call"
            resource = ""

        eval_res = await evaluator.evaluate(principal, action, resource)
        if not eval_res.allowed:
            rbac_mode = getattr(request.app.state, "rbac_mode", "enforce")
            if rbac_mode == "shadow":
                # §19: shadow mode evaluates and records but never blocks, so
                # operators can seed grants from the would-deny log before
                # flipping to enforce. The warning reaches the rotating file
                # handler; the audit row is decision='shadow_deny'.
                METRICS.inc("mcp_authz_shadow_denials_total")
                log.warning(
                    "RBAC shadow would-deny: principal=%s action=%s resource=%s decision=%s reason=%s",
                    principal.principal_id[:12], action, resource, eval_res.decision, eval_res.reason,
                )
                store = getattr(request.app.state, "tenancy_store", None)
                if store is not None:
                    try:
                        await store.log_audit(
                            actor_principal=principal.principal_id, issuer=principal.issuer,
                            org_id=principal.org_id, action=action, resource=resource,
                            decision="shadow_deny", detail=eval_res.reason,
                        )
                    except Exception as exc:
                        log.warning("shadow audit write failed: %s", exc)
                return None
            METRICS.inc("mcp_authz_denials_total")
            # §17.7: don't let error codes confirm another tenant's tools exist.
            # For a specific tool the caller may not see, answer 404 with the same
            # body an unknown tool returns; the real reason is logged server-side
            # only. Non-resource denials (e.g. list) stay 403 but without leaking
            # the internal decision label.
            log.info(
                "RBAC deny: principal=%s action=%s resource=%s decision=%s reason=%s",
                principal.principal_id[:12], action, resource, eval_res.decision, eval_res.reason,
            )
            request.state.auth_failure_reason = f"RBAC permission denied: {eval_res.reason}"
            if action in ("tool:call", "tool:manage") and resource:
                return JSONResponse(
                    {"error": f"unknown or disabled tool {resource!r}"}, status_code=404
                )
            return JSONResponse({"error": "forbidden"}, status_code=403)


    return None



async def read_guard(request):
    """Back-compat alias for ``enforce(request, "mcp")``."""
    return await enforce(request, "mcp")


async def require_permission(request, permission: str):
    """Gate an endpoint on a specific RBAC permission. The static admin token
    (platform_superadmin) always passes; otherwise the resolved principal must
    carry the permission. Returns a 401/403 JSONResponse when denied, else None."""
    token = getattr(request.app.state, "admin_token", "")
    authz = request.headers.get("authorization", "")
    provided = (authz[7:].strip() if authz.lower().startswith("bearer ")
                else request.headers.get("x-admin-token", "").strip()) or request.query_params.get("token", "").strip()
    if token and provided and hmac.compare_digest(provided, token):
        principal = getattr(request.state, "principal", None)
        if principal is None or getattr(principal, "subject", "anonymous") == "anonymous":
            from .identity import create_superadmin_principal, current_principal_var, sanitize_header_value
            app_state = getattr(request.app, "state", None)
            tenant_header_name = getattr(app_state, "tenant_header", "X-Tenant-Id") if app_state else "X-Tenant-Id"
            workspace_header_name = getattr(app_state, "workspace_header", "X-Workspace-Id") if app_state else "X-Workspace-Id"
            active_org = sanitize_header_value(request.headers.get(tenant_header_name), "default")
            active_ws = sanitize_header_value(request.headers.get(workspace_header_name), "default")
            principal = create_superadmin_principal(org_id=active_org, workspace_id=active_ws)
            request.state.principal = principal
            current_principal_var.set(principal)
        return None  # static admin token == platform_superadmin

    principal = getattr(request.state, "principal", None)
    if principal is None or getattr(principal, "subject", "anonymous") == "anonymous":
        try:
            if await _jwt_ok(request):
                principal = getattr(request.state, "principal", None)
        except Exception:
            # a misconfigured verifier must deny, never 500 the endpoint
            log.debug("require_permission: _jwt_ok raised (treated as unauth)", exc_info=True)

    perms = getattr(principal, "permissions", None) or set()
    if permission in perms:
        return None
    request.state.auth_failure_reason = f"requires {permission}"
    if principal is None or getattr(principal, "subject", "anonymous") == "anonymous":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse({"error": "forbidden", "detail": f"requires {permission}"}, status_code=403)


async def admin_denied(request):
    """Return a JSONResponse if the admin request is unauthorized, else None.
    Allows:
    1. Static MCP_ADMIN_TOKEN via Authorization: Bearer <admin_token> or x-admin-token
    2. Verified JWT Bearer token with platform_superadmin role or admin permissions
    """
    token = getattr(request.app.state, "admin_token", "")
    authz = request.headers.get("authorization", "")
    provided = (authz[7:].strip() if authz.lower().startswith("bearer ") else request.headers.get("x-admin-token", "").strip()) or request.query_params.get("token", "").strip()

    # 1. Match static MCP_ADMIN_TOKEN
    if token and provided and hmac.compare_digest(provided, token):
        principal = getattr(request.state, "principal", None)
        if principal is None or getattr(principal, "subject", "anonymous") == "anonymous":
            from .identity import create_superadmin_principal, current_principal_var, sanitize_header_value
            app_state = getattr(request.app, "state", None)
            tenant_header_name = getattr(app_state, "tenant_header", "X-Tenant-Id") if app_state else "X-Tenant-Id"
            workspace_header_name = getattr(app_state, "workspace_header", "X-Workspace-Id") if app_state else "X-Workspace-Id"
            active_org = sanitize_header_value(request.headers.get(tenant_header_name), "default")
            active_ws = sanitize_header_value(request.headers.get(workspace_header_name), "default")
            principal = create_superadmin_principal(org_id=active_org, workspace_id=active_ws)
            request.state.principal = principal
            current_principal_var.set(principal)
        return None


    # 2. Check principal attached by IdentityMiddleware
    principal = getattr(request.state, "principal", None)
    if principal is None or getattr(principal, "subject", "anonymous") == "anonymous":
        if await _jwt_ok(request):
            principal = getattr(request.state, "principal", None)

    if principal and getattr(principal, "subject", "anonymous") != "anonymous":
        admin_perms = {"platform:admin", "org:admin", "admin:all", "member:manage"}
        if "platform_superadmin" in principal.roles or any(p in principal.permissions for p in admin_perms):
            return None
        request.state.auth_failure_reason = "Insufficient admin role/permissions"
        return JSONResponse({"error": "forbidden"}, status_code=403)

    if not token:
        request.state.auth_failure_reason = "Admin API disabled (MCP_ADMIN_TOKEN unset)"
        return JSONResponse({"error": "admin API disabled (set MCP_ADMIN_TOKEN)"}, status_code=503)

    request.state.auth_failure_reason = "Invalid admin token"
    return JSONResponse({"error": "unauthorized"}, status_code=401)


