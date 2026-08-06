"""Unit and integration tests for Phase 5 Production Hardening, Audit Trail & Metrics."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from plugins.config import build_context
from plugins.app import build_app
from plugins.tenancy import MemoryTenancyStore
from plugins.tenancy.audit import AsyncAuditLogger


@pytest.mark.anyio
async def test_async_audit_logger_queue_flushing():
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_file = Path(tmpdir) / "audit.log"
        store = MemoryTenancyStore()
        await store.init_db()

        logger = AsyncAuditLogger(store=store, log_file=audit_file)
        logger.start()

        # Log audit event
        await logger.log_event(
            actor_principal="pid_admin",
            issuer="https://supabase.co/auth/v1",
            org_id="acme",
            action="tool:call",
            resource="greet",
            decision="ALLOW_SUPERADMIN",
            detail="Test audit log",
        )

        # Wait deterministically for worker loop to process queue
        await logger._queue.join()
        await logger.stop()

        # Verify JSONL file content
        assert audit_file.exists()
        content = audit_file.read_text(encoding="utf-8")
        assert "pid_admin" in content
        assert "ALLOW_SUPERADMIN" in content

        # Verify DB audit entry
        entries = await store.query_audit("acme")
        assert len(entries) >= 1
        assert entries[0].actor_principal == "pid_admin"


def test_prometheus_security_metrics():
    from metrics import METRICS
    METRICS.inc("mcp_authz_evaluations_total")
    METRICS.inc("mcp_authz_denials_total")


    ctx = build_context([])
    ctx.metrics_auth = "none"
    app, _ = build_app(ctx)
    client = TestClient(app)


    res = client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "mcp_authz_evaluations_total" in body
    assert "mcp_authz_denials_total" in body



def test_openapi_spec_admin_orgs_endpoints():
    ctx = build_context([])
    app, _ = build_app(ctx)
    client = TestClient(app)

    res = client.get("/openapi.json")
    assert res.status_code == 200
    data = res.json()
    assert "/admin/orgs" in data["paths"]
