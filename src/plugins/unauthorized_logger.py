"""Dedicated Unauthorized Request Audit Logger.

Logs every 401 Unauthorized and 403 Forbidden HTTP request into a separate,
structured log file (``logs/unauthorized_access.json.log``).

Captures:
- Timestamp (ISO 8601 UTC)
- Client IP (accounting for proxies / X-Forwarded-For)
- HTTP Method & Path
- Query Parameters
- Filtered/Sanitized Headers (Authorization/API keys masked)
- Request Payload (Sanitized JSON/text, capped at 8 KB)
- HTTP Status Code (401/403) and Failure Reason
- Correlated W3C Trace & Span IDs
"""
from __future__ import annotations

import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .observability import BEARER_PATTERN, SECRET_KEY_PATTERN, get_current_span_id, get_current_trace_id

log = logging.getLogger("MCP_logger")

MAX_PAYLOAD_BYTES = 8192  # 8 KB limit for logged payloads


def sanitize_data(data: Any) -> Any:
    """Recursively sanitize dictionaries, lists, or strings to mask sensitive keys/tokens."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if SECRET_KEY_PATTERN.search(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str):
        return BEARER_PATTERN.sub(r"\1[REDACTED]", data)
    return data


class UnauthorizedLogger:
    """Manages writing JSON-formatted unauthorized attempt records to a rotating log file."""

    def __init__(self, log_file_path: Path):
        self.log_file_path = log_file_path
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger("MCP_unauthorized_audit_logger")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._logger.handlers.clear()

        handler = RotatingFileHandler(
            str(self.log_file_path),
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def log_unauthorized_event(self, event: Dict[str, Any]) -> None:
        try:
            line = json.dumps(event, default=str)
            self._logger.info(line)
        except Exception as exc:
            log.error("Failed to write unauthorized access log: %s", exc)


class UnauthorizedLoggingMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that intercepts 401/403 responses and records request details."""

    def __init__(self, app, logger: UnauthorizedLogger):
        super().__init__(app)
        self.unauthorized_logger = logger

    async def dispatch(self, request: Request, call_next) -> Response:
        # Buffer request body safely before processing downstream
        body_bytes = b""
        try:
            body_bytes = await request.body()
            # Restore _body so downstream handlers/FastMCP can still read request.body()
            request._body = body_bytes
        except Exception as exc:
            log.debug("Could not read request body for audit logger: %s", exc)

        response = await call_next(request)

        # Only record 401 Unauthorized and 403 Forbidden responses
        if response.status_code in (401, 403):
            try:
                await self._record_unauthorized_attempt(request, response, body_bytes)
            except Exception as exc:
                log.error("Error logging unauthorized request: %s", exc)

        return response

    async def _record_unauthorized_attempt(
        self, request: Request, response: Response, body_bytes: bytes
    ) -> None:
        # Resolve client IP (check X-Forwarded-For first)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif request.client and request.client.host:
            client_ip = request.client.host
        else:
            client_ip = "unknown"

        # Sanitize headers (mask Authorization, x-api-key, admin-token, etc.)
        sanitized_headers = {}
        for k, v in request.headers.items():
            k_lower = k.lower()
            if SECRET_KEY_PATTERN.search(k_lower):
                if k_lower == "authorization" and v.lower().startswith("bearer "):
                    sanitized_headers[k] = "Bearer [REDACTED]"
                else:
                    sanitized_headers[k] = "[REDACTED]"
            else:
                sanitized_headers[k] = v

        # Parse & sanitize request payload
        payload: Any = None
        if body_bytes:
            if len(body_bytes) > MAX_PAYLOAD_BYTES:
                payload = f"<payload truncated: {len(body_bytes)} bytes exceeds {MAX_PAYLOAD_BYTES} byte limit>"
            else:
                try:
                    decoded = body_bytes.decode("utf-8")
                    try:
                        parsed_json = json.loads(decoded)
                        payload = sanitize_data(parsed_json)
                    except Exception:
                        payload = sanitize_data(decoded)
                except Exception:
                    payload = f"<binary data: {len(body_bytes)} bytes>"

        # Determine failure reason attached to state or headers
        reason = getattr(request.state, "auth_failure_reason", None)
        if not reason:
            reason = response.headers.get("x-auth-failure-reason")
        if not reason:
            reason = "Unauthorized access attempt" if response.status_code == 401 else "Forbidden access attempt"

        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            + f".{int(time.time() * 1000) % 1000:03d}Z",
            "log_type": "unauthorized",
            "status_code": response.status_code,
            "client_ip": client_ip,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "reason": reason,
            "trace_id": get_current_trace_id(),
            "span_id": get_current_span_id(),
            "headers": sanitized_headers,
            "payload": payload,
        }

        self.unauthorized_logger.log_unauthorized_event(event)
