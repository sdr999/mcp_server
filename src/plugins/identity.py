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


def create_anonymous_principal(org_id: str = "default", workspace_id: str = "default") -> Principal:
    pid = derive_principal_id("local", "anonymous")
    return Principal(
        principal_id=pid,
        issuer="local",
        subject="anonymous",
        kind="user",
        org_id=org_id,
        workspace_id=workspace_id,
        roles=["agent_consumer"],
        permissions={"tool:list", "tool:call", "upstream:read", "upstream:call"},
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
        permissions={
            "tool:list", "tool:call", "tool:onboard", "tool:manage",
            "upstream:read", "upstream:call", "upstream:manage",
            "member:manage", "role:bind", "org:admin", "workspace:admin", "platform:admin",
        },
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
    assigned_roles = roles[:] if roles else ["developer"]
    if superadmin_email and email and email.lower() == superadmin_email.lower():
        if "platform_superadmin" not in assigned_roles:
            assigned_roles.append("platform_superadmin")

    perms = {"tool:list", "tool:call", "upstream:read", "upstream:call"}
    if "platform_superadmin" in assigned_roles or "org_admin" in assigned_roles:
        perms.update({"tool:onboard", "tool:manage", "upstream:manage", "member:manage", "role:bind", "org:admin", "workspace:admin"})
    if "platform_superadmin" in assigned_roles:
        perms.add("platform:admin")

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

        # 1. Check Authorization header (accept Bearer <token> or raw <token>)
        authz = request.headers.get("authorization", "").strip()
        bearer_token = authz[7:].strip() if authz.lower().startswith("bearer ") else authz

        if admin_token and bearer_token and hmac.compare_digest(bearer_token, admin_token):
            principal = create_superadmin_principal(org_id=active_org, workspace_id=active_ws)

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

                # Fallback to PyJWKClient verification if needed
                if not claims:
                    jwks_url = getattr(app_state, "jwks_url", "")
                    if jwks_url:
                        try:
                            import jwt
                            from jwt import PyJWKClient
                            jwk_client = PyJWKClient(jwks_url, headers={"User-Agent": "MCP-Server/1.0"})
                            signing_key = jwk_client.get_signing_key_from_jwt(bearer_token)
                            claims = jwt.decode(
                                bearer_token,
                                signing_key.key,
                                algorithms=["ES256", "RS256", "HS256"],
                                options={"verify_aud": False},
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

            if principal:
                principal.org_id = active_org
                principal.workspace_id = active_ws


        # 3. Fallback to Anonymous Principal if unassigned
        if principal is None:
            principal = create_anonymous_principal(org_id=active_org, workspace_id=active_ws)


        request.state.principal = principal
        ctx_token = current_principal_var.set(principal)

        try:
            return await call_next(request)
        finally:
            current_principal_var.reset(ctx_token)
