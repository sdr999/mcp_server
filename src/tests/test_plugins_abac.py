"""Unit and integration tests for Phase 4 ABAC Rules, Dynamic Tool Grants, and Admin API."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from plugins.config import build_context
from plugins.app import build_app
from plugins.identity import Principal
from plugins.tenancy.models import ToolOwnership
from plugins.rbac import ABACEvaluator


def test_abac_match_tool_patterns():
    # Exact
    assert ABACEvaluator.match_tool_pattern("exact", "web_search", "web_search") is True
    assert ABACEvaluator.match_tool_pattern("exact", "web_search", "web_search_v2") is False

    # Prefix
    assert ABACEvaluator.match_tool_pattern("prefix", "github_*", "github_create_issue") is True
    assert ABACEvaluator.match_tool_pattern("prefix", "github_", "github_create_issue") is True
    assert ABACEvaluator.match_tool_pattern("prefix", "github_*", "slack_send") is False

    # Glob
    assert ABACEvaluator.match_tool_pattern("glob", "db_*_query", "db_users_query") is True
    assert ABACEvaluator.match_tool_pattern("glob", "db_*_query", "db_users_update") is False


def test_abac_trusted_tags_validation():
    ownership = ToolOwnership(
        tool_name="financial_audit",
        owner_org="finance_org",
        trusted_tags=["pii", "finance"],
    )

    user_lacking = Principal(
        principal_id="pid_1",
        issuer="https://supabase.co/auth/v1",
        subject="user1",
        metadata={"tags": ["pii"]},
    )
    res1 = ABACEvaluator.evaluate_tool_attributes(user_lacking, "financial_audit", ownership)
    assert res1.allowed is False
    assert "lacks required trusted tags" in res1.reason

    user_matching = Principal(
        principal_id="pid_2",
        issuer="https://supabase.co/auth/v1",
        subject="user2",
        metadata={"tags": ["pii", "finance", "audit"]},
    )
    res2 = ABACEvaluator.evaluate_tool_attributes(user_matching, "financial_audit", ownership)
    assert res2.allowed is True


def test_abac_prod_only_workspace_restriction():
    ownership = ToolOwnership(
        tool_name="deploy_prod",
        owner_org="devops",
        tags=["prod_only"],
    )

    dev_user = Principal(
        principal_id="pid_dev",
        issuer="https://supabase.co/auth/v1",
        subject="dev",
        workspace_id="staging",
    )
    res_dev = ABACEvaluator.evaluate_tool_attributes(dev_user, "deploy_prod", ownership)
    assert res_dev.allowed is False
    assert "restricted to 'prod' workspace" in res_dev.reason

    prod_user = Principal(
        principal_id="pid_prod",
        issuer="https://supabase.co/auth/v1",
        subject="prod_admin",
        workspace_id="prod",
    )
    res_prod = ABACEvaluator.evaluate_tool_attributes(prod_user, "deploy_prod", ownership)
    assert res_prod.allowed is True


def test_admin_tool_grants_rest_api():
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)
    headers = {"Authorization": "Bearer mysecretadmin"}

    # Add Grant
    res = client.post(
        "/admin/orgs/acme/tool-grants",
        json={"scope_type": "org", "scope_id": "acme", "effect": "allow", "match_type": "prefix", "match_value": "github_*"},
        headers=headers,
    )
    assert res.status_code == 201
    grant_data = res.json()
    assert grant_data["match_value"] == "github_*"

    # List Grants
    res = client.get("/admin/orgs/acme/tool-grants", headers=headers)
    assert res.status_code == 200
    grants = res.json()
    assert len(grants) >= 1
    assert any(g["match_value"] == "github_*" for g in grants)
