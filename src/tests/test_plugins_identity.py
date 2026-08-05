"""Unit and integration tests for Phase 0 Identity propagation, TokenCache, and Supabase Auth."""
from __future__ import annotations

import time
import pytest
from starlette.testclient import TestClient

from plugins.config import build_context
from plugins.app import build_app

from plugins.identity import (
    Principal,
    TokenCache,
    derive_principal_id,
    sanitize_header_value,
    build_principal_from_claims,
    create_anonymous_principal,
    create_superadmin_principal,
)
from plugins.auth_service import _mask_email, _sanitize_supabase_error


def test_derive_principal_id_collision_prevention():
    """Verify principal_id derivation is deterministic and collision-free."""
    p1 = derive_principal_id("https://supabase.co/auth/v1", "user_123")
    p2 = derive_principal_id("https://supabase.co/auth/v1", "user_123")
    p3 = derive_principal_id("https://supabase.co/auth/v1", "user_456")
    p4 = derive_principal_id("https://other.idp.com", "user_123")

    assert p1 == p2
    assert p1 != p3
    assert p1 != p4
    assert len(p1) == 64  # sha256 hex string


def test_sanitize_header_value():
    """Verify header value sanitization prevents header injection attacks."""
    assert sanitize_header_value("org-123") == "org-123"
    assert sanitize_header_value("  workspace_A  ") == "workspace_A"
    assert sanitize_header_value("bad/header/value") == "default"
    assert sanitize_header_value("org<script>") == "default"
    assert sanitize_header_value("") == "default"
    assert sanitize_header_value(None) == "default"


def test_token_cache_hashing_and_ttl():
    """Verify TokenCache keys on token hash and enforces exp-based TTL."""
    cache = TokenCache(max_size=10, default_ttl=300)
    principal = Principal(principal_id="pid1", issuer="iss", subject="sub1")

    token = "secret_jwt_token_123"
    # Key should NOT be raw token
    assert cache._hash_token(token) != token

    # Exp in 100 seconds -> should be cached
    now = time.time()
    cache.set(token, principal, exp_timestamp=now + 100)
    cached = cache.get(token)
    assert cached is not None
    assert cached.principal_id == "pid1"

    # Expired token -> should return None
    expired_token = "expired_token_abc"
    cache.set(expired_token, principal, exp_timestamp=now - 5)
    assert cache.get(expired_token) is None


def test_mask_email():
    """Verify PII email masking for logs."""
    assert _mask_email("john.doe@example.com") == "j***@e***.com"
    assert _mask_email("a@b.org") == "a***@b***.org"
    assert _mask_email("invalidemail") == "***"


def test_build_principal_from_claims_superadmin():
    """Verify superadmin_email auto-assigns platform_superadmin role."""
    p = build_principal_from_claims(
        issuer="https://bplpycqmizyztxqwglgb.supabase.co/auth/v1",
        subject="user_123",
        email="oooosomu9@gmail.com",
        superadmin_email="oooosomu9@gmail.com",
    )
    assert "platform_superadmin" in p.roles
    assert "platform:admin" in p.permissions


def test_whoami_endpoint_anonymous():
    """Test GET /whoami without auth headers returns anonymous principal."""
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)

    res = client.get("/whoami")
    assert res.status_code == 200
    data = res.json()
    assert data["subject"] == "anonymous"
    assert data["kind"] == "user"
    assert data["org_id"] == "default"
    assert data["workspace_id"] == "default"


def test_whoami_endpoint_admin_token():
    """Test GET /whoami with Admin token returns superadmin principal."""
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)

    res = client.get("/whoami", headers={"Authorization": "Bearer mysecretadmin"})
    assert res.status_code == 200
    data = res.json()
    assert data["subject"] == "admin-token"
    assert data["kind"] == "service"
    assert "platform_superadmin" in data["roles"]


def test_whoami_tenant_and_workspace_headers():
    """Test GET /whoami propagates sanitized X-Tenant-Id and X-Workspace-Id."""
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)

    res = client.get("/whoami", headers={
        "X-Tenant-Id": "acme-corp",
        "X-Workspace-Id": "engineering-prod",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["org_id"] == "acme-corp"
    assert data["workspace_id"] == "engineering-prod"
