"""Unit tests for the Unauthorized Logger and Middleware."""
import json
import pytest
from pathlib import Path
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from plugins.unauthorized_logger import (
    UnauthorizedLogger,
    UnauthorizedLoggingMiddleware,
    sanitize_data,
)


@pytest.fixture
def temp_log_file(tmp_path):
    return tmp_path / "unauthorized_access.json.log"


def test_sanitize_data():
    raw_data = {
        "user": "alice",
        "password": "my_secret_password",
        "api_key": "key_12345",
        "nested": {
            "token": "Bearer eyJhbGciOi...",
            "valid_field": "hello",
        },
        "list_items": ["item1", "authorization: Bearer secret_token"],
    }
    sanitized = sanitize_data(raw_data)
    assert sanitized["user"] == "alice"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["valid_field"] == "hello"
    assert "Bearer [REDACTED]" in sanitized["list_items"][1]


def test_unauthorized_logger_file_creation(temp_log_file):
    logger = UnauthorizedLogger(temp_log_file)
    event = {
        "timestamp": "2026-08-06T21:00:00.000Z",
        "status_code": 401,
        "path": "/test",
        "reason": "Invalid token",
    }
    logger.log_unauthorized_event(event)

    assert temp_log_file.exists()
    lines = temp_log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["status_code"] == 401
    assert record["reason"] == "Invalid token"


def test_unauthorized_middleware_captures_401(temp_log_file):
    async def sample_unauthorized_route(request):
        request.state.auth_failure_reason = "Missing bearer token"
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    async def sample_ok_route(request):
        return JSONResponse({"status": "ok"}, status_code=200)

    app = Starlette(
        routes=[
            Route("/protected", sample_unauthorized_route, methods=["POST"]),
            Route("/public", sample_ok_route, methods=["GET"]),
        ]
    )
    logger = UnauthorizedLogger(temp_log_file)
    app.add_middleware(UnauthorizedLoggingMiddleware, logger=logger)

    client = TestClient(app)

    # 1. Call 200 route -> should NOT produce an entry in unauthorized log
    res_ok = client.get("/public")
    assert res_ok.status_code == 200
    if temp_log_file.exists():
        assert len(temp_log_file.read_text(encoding="utf-8").strip()) == 0

    # 2. Call 401 route with payload -> should produce structured log entry
    res_unauth = client.post(
        "/protected?foo=bar",
        json={"city": "Paris", "password": "supersecretpassword"},
        headers={"User-Agent": "TestAgent/1.0", "Authorization": "Bearer secret_jwt"},
    )
    assert res_unauth.status_code == 401

    assert temp_log_file.exists()
    lines = temp_log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    log_entry = json.loads(lines[0])

    assert log_entry["status_code"] == 401
    assert log_entry["method"] == "POST"
    assert log_entry["path"] == "/protected"
    assert log_entry["query_params"] == {"foo": "bar"}
    assert log_entry["reason"] == "Missing bearer token"
    assert log_entry["payload"] == {"city": "Paris", "password": "[REDACTED]"}
    assert log_entry["headers"]["authorization"] == "Bearer [REDACTED]"


def test_unauthorized_middleware_truncates_oversized_payload(temp_log_file):
    async def sample_unauthorized_route(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    app = Starlette(routes=[Route("/protected", sample_unauthorized_route, methods=["POST"])])
    logger = UnauthorizedLogger(temp_log_file)
    app.add_middleware(UnauthorizedLoggingMiddleware, logger=logger)

    client = TestClient(app)
    large_payload = "A" * 10000

    res = client.post("/protected", content=large_payload)
    assert res.status_code == 401

    lines = temp_log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    log_entry = json.loads(lines[0])
    assert "<payload truncated:" in str(log_entry["payload"])
