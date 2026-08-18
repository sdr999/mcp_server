"""Identity representation, context propagation, and token caching for Multi-Tenancy & RBAC.

Provides:
- Principal data model and collision-free principal_id derivation.
- ContextVar for request-scoped principal access across async tasks.
- Thread-safe TokenCache with token hashing and dynamic exp-based TTL.
- IdentityMiddleware for Starlette/FastAPI request pipeline.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("MCP_logger")

HEADER_SAFE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def sanitize_header_value(value: Optional[str], default: str = "default") -> str:
    """Sanitize tenant and workspace headers against injection attacks."""
    if not value or not isinstance(value, str):
        return default
    val = value.strip()
    if HEADER_SAFE_RE.match(val):
        return val
    log.warning("Invalid tenant/workspace header value %r; falling back to %r", value, default)
    return default


def derive_principal_id(issuer: str, subject: str) -> str:
    """Compute a collision-free principal_id using canonical JSON sha256."""
    canonical = json.dumps([issuer or "local", subject or "anonymous"], sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def select_tenant_context(
    memberships,
    active_org: Optional[str],
    active_ws: Optional[str] = None,
    default_org: str = "default",
    default_ws: str = "default",
):
    """Resolve the caller's active (org, workspace) from their store memberships.

    A tenant header (``X-Tenant-Id`` / ``X-Workspace-Id``) is a *request*, not a
    fact: it is honored **only** when the caller actually holds a membership in
    that org (the §9 / §17.8 anti-spoofing rule). A header naming a non-member org
    is ignored, never trusted. Callers with no memberships collapse to the default
    (public) org, so an unauthenticated/first-seen principal can never assert
    another tenant's context. Returns ``(org_id, workspace_id)``.
    """
    member_orgs = [m.org_id for m in memberships]
    if active_org and active_org in member_orgs:
        org_id = active_org
    elif memberships:
        org_id = memberships[0].org_id
    else:
        org_id = default_org

    # Workspace is honored only within the resolved org's memberships; otherwise
    # fall back to a membership workspace or the default. (Org is the isolation
    # boundary; workspace is a sub-partition.)
    org_workspaces = [m.workspace_id for m in memberships if m.org_id == org_id and m.workspace_id]
    if active_ws and active_ws in org_workspaces:
        workspace_id = active_ws
    elif org_workspaces:
        workspace_id = org_workspaces[0]
    else:
        workspace_id = (active_ws or default_ws) if not member_orgs else default_ws
    return org_id, workspace_id


@dataclass
class Principal:
    principal_id: str
    issuer: str
    subject: str
    kind: str = "user"  # user | service | agent
    org_id: str = "default"
    workspace_id: Optional[str] = "default"
    roles: List[str] = field(default_factory=list)
    permissions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "principal_id": self.principal_id,
            "issuer": self.issuer,
            "subject": self.subject,
            "kind": self.kind,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "roles": self.roles,
            "permissions": sorted(list(self.permissions)),
            "metadata": self.metadata,
        }


# Request-scoped ContextVar
current_principal_var: ContextVar[Optional[Principal]] = ContextVar("current_principal", default=None)


def get_current_principal() -> Optional[Principal]:
    return current_principal_var.get()


class TokenCache:
    """Thread-safe LRU token verification cache.
    Keyed on sha256(token) to prevent raw tokens in heap/core dumps.
    Enforces dynamic TTL = min(max_ttl, exp_timestamp - now).
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Principal, float]] = OrderedDict()
        self._lock = threading.Lock()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def get(self, token: str) -> Optional[Principal]:
        if not token:
            return None
        key = self._hash_token(token)
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            principal, expiry = entry
            if time.monotonic() > expiry:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return principal

    def set(
        self,
        token: str,
        principal: Principal,
        exp_timestamp: Optional[float] = None,
        max_ttl: int = 300,
    ) -> None:
        if not token or not principal:
            return
        key = self._hash_token(token)
        now_mono = time.monotonic()
        now_wall = time.time()

        ttl = float(max_ttl)
        if exp_timestamp is not None:
            remaining = float(exp_timestamp) - now_wall
            if remaining <= 0:
                with self._lock:
                    self._cache.pop(key, None)
                return
            ttl = min(ttl, remaining)


        expiry = now_mono + ttl
        with self._lock:
            self._cache[key] = (principal, expiry)
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# Global shared token cache instance
token_cache = TokenCache()


# Canonical role -> permission matrix (§5). SINGLE source of truth: the store's
# `roles` table is seeded from this (see tenancy.seeder) and it is authoritative
# at runtime via resolve_principal(); this in-code copy is the seed and the
# RBAC-off / store-unavailable fallback derivation, so the two never drift (H1).
BUILTIN_ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "platform_superadmin": {
        "tool:list", "tool:call", "tool:onboard", "tool:manage",
        "upstream:read", "upstream:call", "upstream:manage",
        "member:manage", "role:bind", "org:admin", "workspace:admin", "platform:admin",
        # analytics: global aggregate dashboards + kill-switch, org-scoped rows, bodies
        "analytics:admin", "analytics:read", "analytics:read_content",
    },
    "org_admin": {
        "tool:list", "tool:call", "tool:onboard", "tool:manage",
        "upstream:read", "upstream:call", "upstream:manage",
        "member:manage", "role:bind", "org:admin", "workspace:admin",
        # analytics: own-org result rows incl. captured bodies (NOT global dashboards)
        "analytics:read", "analytics:read_content",
    },
    "developer": {
        "tool:list", "tool:call", "tool:onboard", "tool:manage",
        "upstream:read", "upstream:call",
        # analytics: own-org result metadata only (no captured bodies)
        "analytics:read",
    },
    "agent_consumer": {
        "tool:list", "tool:call", "upstream:read", "upstream:call",
    },
}

# The least-privilege default for an authenticated principal with no role binding
# (deny-by-default, §6). NOT 'developer' — a bare signed token must not inherit
# tool:onboard / tool:manage (H3, §17.4).
DEFAULT_ROLE = "agent_consumer"

# Back-compat alias used by the identity middleware's superadmin-email bootstrap.
SUPERADMIN_PERMISSIONS = BUILTIN_ROLE_PERMISSIONS["platform_superadmin"]


def permissions_for_roles(roles: List[str]) -> Set[str]:
    """Union of the permissions of the given roles per the built-in matrix.

    Unknown roles contribute nothing (deny-by-default). This is the fallback
    derivation; when RBAC is enabled the store's role definitions win via
    resolve_principal().
    """
    perms: Set[str] = set()
    for r in roles:
        perms |= BUILTIN_ROLE_PERMISSIONS.get(r, set())
    return perms


def create_anonymous_principal(org_id: str = "default", workspace_id: str = "default") -> Principal:
    pid = derive_principal_id("local", "anonymous")
    return Principal(
        principal_id=pid,
        issuer="local",
        subject="anonymous",
        kind="user",
        org_id=org_id,
        workspace_id=workspace_id,
        roles=[DEFAULT_ROLE],
        permissions=permissions_for_roles([DEFAULT_ROLE]),
    )


def create_superadmin_principal(org_id: str = "default", workspace_id: str = "default") -> Principal:
    pid = derive_principal_id("local", "admin-token")
    return Principal(
        principal_id=pid,
        issuer="local",
        subject="admin-token",
        kind="service",
        org_id=org_id,
        workspace_id=workspace_id,
        roles=["platform_superadmin"],
        permissions=permissions_for_roles(["platform_superadmin"]),
    )


def build_principal_from_claims(
    issuer: str,
    subject: str,
    org_id: str = "default",
    workspace_id: str = "default",
    email: str = "",
    roles: Optional[List[str]] = None,
    superadmin_email: str = "",
) -> Principal:
    pid = derive_principal_id(issuer, subject)
    # Floor at the least-privilege default, not 'developer' (H3).
    assigned_roles = roles[:] if roles else [DEFAULT_ROLE]
    if superadmin_email and email and email.lower() == superadmin_email.lower():
        if "platform_superadmin" not in assigned_roles:
            assigned_roles.append("platform_superadmin")

    perms = permissions_for_roles(assigned_roles)

    metadata = {}
    if email:
        metadata["email"] = email

    return Principal(
        principal_id=pid,
        issuer=issuer,
        subject=subject,
        kind="user",
        org_id=org_id,
        workspace_id=workspace_id,
        roles=assigned_roles,
        permissions=perms,
        metadata=metadata,
    )


class IdentityMiddleware(BaseHTTPMiddleware):
    """Middleware that resolves caller identity, attaches request.state.principal,
    and sets current_principal_var with leak-free ContextVar token cleanup.
    """

    async def dispatch(self, request: Request, call_next):
        app_state = getattr(request.app, "state", None)

        tenant_header_name = getattr(app_state, "tenant_header", "X-Tenant-Id") if app_state else "X-Tenant-Id"
        workspace_header_name = getattr(app_state, "workspace_header", "X-Workspace-Id") if app_state else "X-Workspace-Id"

        active_org = sanitize_header_value(request.headers.get(tenant_header_name), "default")
        active_ws = sanitize_header_value(request.headers.get(workspace_header_name), "default")

        admin_token = getattr(app_state, "admin_token", "") if app_state else ""
        auth_type = getattr(app_state, "auth_type", "none") if app_state else "none"
        superadmin_email = getattr(app_state, "superadmin_email", "") if app_state else ""

        principal: Optional[Principal] = None
        is_admin_token = False

        # 1. Check Authorization header (accept Bearer <token> or raw <token>)
        authz = request.headers.get("authorization", "").strip()
        bearer_token = authz[7:].strip() if authz.lower().startswith("bearer ") else authz

        if admin_token and bearer_token and hmac.compare_digest(bearer_token, admin_token):
            principal = create_superadmin_principal(org_id=active_org, workspace_id=active_ws)
            is_admin_token = True  # bootstrap superadmin; not subject to store overlay

        # 2. Check LRU Cache / Verify JWT Token if present
        if principal is None and bearer_token:
            principal = token_cache.get(bearer_token)
            if not principal:
                claims = None
                verifier = getattr(app_state, "jwt_verifier", None)
                if verifier:
                    try:
                        verified_token = await verifier.verify_token(bearer_token)
                        if verified_token:
                            claims = getattr(verified_token, "claims", {}) or {}
                    except Exception as exc:
                        log.debug("Verifier error: %s", exc)

                # Fallback to PyJWKClient verification if needed. Asymmetric
                # algorithms only — HS256 with a JWKS public key would allow a
                # key-confusion attack (§9, M3). Audience is verified whenever an
                # expected audience is configured.
                if not claims:
                    jwks_url = getattr(app_state, "jwks_url", "")
                    if jwks_url:
                        try:
                            import jwt
                            from jwt import PyJWKClient
                            expected_aud = getattr(app_state, "jwt_audience", None) or None
                            jwk_client = PyJWKClient(jwks_url, headers={"User-Agent": "MCP-Server/1.0"})
                            signing_key = jwk_client.get_signing_key_from_jwt(bearer_token)
                            claims = jwt.decode(
                                bearer_token,
                                signing_key.key,
                                algorithms=["ES256", "RS256"],
                                audience=expected_aud,
                                options={"verify_aud": expected_aud is not None},
                            )
                        except Exception as exc:
                            log.debug("PyJWKClient fallback error: %s", exc)

                if claims:
                    sub = claims.get("sub", "anonymous")
                    iss = claims.get("iss") or getattr(app_state, "jwt_issuer", "") or "local"
                    email = claims.get("email") or claims.get("user_metadata", {}).get("email", "")
                    exp = claims.get("exp")
                    principal = build_principal_from_claims(
                        issuer=iss,
                        subject=sub,
                        org_id=active_org,
                        workspace_id=active_ws,
                        email=email,
                        superadmin_email=superadmin_email,
                    )
                    token_cache.set(bearer_token, principal, exp_timestamp=exp)

        # 3. Store-authoritative overlay (§4 hybrid, §9/§17.8 anti-spoofing).
        # When RBAC is enabled, org/workspace/roles/permissions come from the
        # tenancy store keyed on the *verified* (issuer, subject) — never from the
        # raw tenant header. resolve_principal() validates the requested org
        # against the caller's memberships. The admin bootstrap token is exempt.
        rbac_enabled = getattr(app_state, "rbac_enabled", False) if app_state else False
        store = getattr(app_state, "tenancy_store", None) if app_state else None
        if principal is not None and not is_admin_token and rbac_enabled and store is not None:
            resolved = None
            try:
                resolved = await store.resolve_principal(
                    principal.issuer, principal.subject, active_org, active_ws
                )
            except Exception as exc:
                # Fail-closed, security-relevant: log at WARNING so it lands in the
                # rotating file handler (INFO level) rather than being swallowed at
                # DEBUG. The caller keeps its pre-overlay (claim-derived) principal.
                log.warning("tenancy resolve_principal failed for %s: %s", principal.principal_id[:12], exc)
            if resolved is not None:
                resolved.kind = principal.kind
                resolved.metadata = dict(principal.metadata or {})
                # Bootstrap: the configured platform-admin email stays superadmin
                # even before an explicit store binding exists.
                email = (principal.metadata or {}).get("email", "")
                if superadmin_email and email and email.lower() == superadmin_email.lower():
                    if "platform_superadmin" not in resolved.roles:
                        resolved.roles.append("platform_superadmin")
                    resolved.permissions = set(resolved.permissions) | SUPERADMIN_PERMISSIONS
                principal = resolved

        # 4. Fallback to Anonymous Principal if unassigned. Anonymous callers hold
        # no memberships, so they are pinned to the default (public) org and can
        # never assert another tenant's context via a header.
        if principal is None:
            principal = create_anonymous_principal(org_id="default", workspace_id="default")


        request.state.principal = principal
        ctx_token = current_principal_var.set(principal)

        try:
            return await call_next(request)
        finally:
            current_principal_var.reset(ctx_token)
