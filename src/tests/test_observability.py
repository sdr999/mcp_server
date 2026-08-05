"""Unit tests for production-grade Smart Observability system.

Run: pytest src/tests/test_observability.py
"""
import json
import logging
import sys
from pathlib import Path

# Ensure src directory is in sys.path
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from starlette.testclient import TestClient
from plugins.config import build_context
from plugins.app import build_app
from plugins.observability import (
    SecretMaskingFilter,
    StructuredJsonFormatter,
    ProbeLogSampler,
    parse_w3c_traceparent,
    trace_id_ctx,
)


def test_w3c_traceparent_parser():
    valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    res = parse_w3c_traceparent(valid)
    assert res is not None
    trace_id, span_id = res
    assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert span_id == "00f067aa0ba902b7"

    assert parse_w3c_traceparent("invalid-header") is None


def test_secret_masking_filter():
    filt = SecretMaskingFilter()
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Connecting with Authorization: Bearer secret_token_12345",
        args=(),
        exc_info=None,
    )
    filt.filter(rec)
    assert "Bearer [REDACTED]" in rec.msg
    assert "secret_token_12345" not in rec.msg


def test_structured_json_formatter():
    formatter = StructuredJsonFormatter(service_name="test-mcp")
    t_token = trace_id_ctx.set("abc123traceid")
    try:
        rec = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="User action occurred",
            args=(),
            exc_info=None,
        )
        rec.event = "user_login"
        formatted = formatter.format(rec)
        data = json.loads(formatted)
        assert data["level"] == "INFO"
        assert data["service"] == "test-mcp"
        assert data["trace_id"] == "abc123traceid"
        assert data["event"] == "user_login"
        assert data["message"] == "User action occurred"
    finally:
        trace_id_ctx.reset(t_token)


def test_probe_log_sampler():
    sampler = ProbeLogSampler()
    rec_probe = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Probe response",
        args=(),
        exc_info=None,
    )
    rec_probe.path = "/healthz"
    rec_probe.status_code = 200
    assert sampler.filter(rec_probe) is False  # Suppressed

    rec_error = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Probe failed",
        args=(),
        exc_info=None,
    )
    rec_error.path = "/healthz"
    rec_error.status_code = 500
    assert sampler.filter(rec_error) is True  # Kept on error


def test_trace_correlation_middleware_integration(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    ctx = build_context([], base_dir=SRC_DIR)
    ctx.tools_dir = tools_dir
    app, _mcp = build_app(ctx)
    client = TestClient(app)

    # 1. Custom X-Trace-ID propagation
    resp = client.get("/healthz", headers={"X-Trace-ID": "custom-trace-999"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Trace-ID") == "custom-trace-999"

    # 2. W3C traceparent header propagation
    w3c_header = "00-11223344556677889900aabbccddeeff-1234567890abcdef-01"
    resp_w3c = client.get("/healthz", headers={"traceparent": w3c_header})
    assert resp_w3c.status_code == 200
    assert resp_w3c.headers.get("X-Trace-ID") == "11223344556677889900aabbccddeeff"

    # 3. Auto-generated trace ID
    resp_auto = client.get("/healthz")
    assert resp_auto.status_code == 200
    assert "X-Trace-ID" in resp_auto.headers
    assert len(resp_auto.headers["X-Trace-ID"]) >= 16


def test_admin_logs_endpoint(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    ctx = build_context([], base_dir=tmp_path)
    ctx.tools_dir = tools_dir
    ctx.admin_token = "admintoken"
    app, _mcp = build_app(ctx)
    client = TestClient(app)

    # Emit logs through logger
    logger = logging.getLogger("MCP_logger")
    logger.info("Server started", extra={"trace_id": "tr111"})
    logger.error("Database timeout", extra={"trace_id": "tr222"})
    for h in logger.handlers:
        h.flush()


    audit_log = logs_dir / "onboard_audit.jsonl"
    audit_log.write_text(
        json.dumps({"action": "onboard", "tool": "calculator", "status": "approved"}) + "\n"
    )

    headers = {"Authorization": "Bearer admintoken"}

    # 1. Fetch server logs
    resp_server = client.get("/admin/logs?type=server", headers=headers)
    assert resp_server.status_code == 200
    data_server = resp_server.json()
    assert data_server["log_type"] == "server"
    assert data_server["count"] >= 2



    # 2. Fetch server logs filtered by level=ERROR
    resp_err = client.get("/admin/logs?type=server&level=ERROR", headers=headers)
    assert resp_err.status_code == 200
    assert resp_err.json()["count"] >= 1
    assert any(item.get("message") == "Database timeout" for item in resp_err.json()["logs"])

    # 3. Fetch audit logs
    resp_audit = client.get("/admin/logs/audit", headers=headers)
    assert resp_audit.status_code == 200
    assert len(resp_audit.json()["logs"]) >= 1
    assert resp_audit.json()["logs"][0]["tool"] == "calculator"


