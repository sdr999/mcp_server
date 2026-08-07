"""Production-Grade Smart Observability System.

Includes:
- Tracing & W3C Trace Context propagation (TraceCorrelationMiddleware)
- Structured JSON Logging (StructuredJsonFormatter)
- Security & Privacy Redaction (SecretMaskingFilter)
- Health-Probe Log Sampling (ProbeLogSampler)
- Log File Rotation & Disk Safety (RotatingFileHandler)
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Context variables for request-bound Trace ID and Span ID tracking
trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="system")
span_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="system")

# Sensitive key patterns for automatic redaction
SECRET_KEY_PATTERN = re.compile(
    r"(authorization|api_key|admin_token|token|password|secret|bearer|jwt|key)",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)


def get_current_trace_id() -> str:
    return trace_id_ctx.get()


def get_current_span_id() -> str:
    return span_id_ctx.get()


def parse_w3c_traceparent(header_val: str) -> Optional[Tuple[str, str]]:
    """Parse W3C traceparent header format: 00-trace_id-span_id-flags."""
    if not header_val:
        return None
    parts = header_val.strip().split("-")
    if len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
        return parts[1], parts[2]
    return None


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def generate_span_id() -> str:
    return uuid.uuid4().hex[:16]



class SecretMaskingFilter(logging.Filter):

    """Filter that masks sensitive tokens, passwords, and authorization headers."""

    def mask_text(self, text: str) -> str:
        if not isinstance(text, str):
            text = str(text or "")
        return BEARER_PATTERN.sub(r"\1[REDACTED]", text)


    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_text(record.msg)
        if isinstance(record.args, dict):
            record.args = self._redact_dict(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(
                self.mask_text(str(arg)) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


    def _redact_dict(self, data: dict) -> dict:
        redacted = {}
        for k, v in data.items():
            if SECRET_KEY_PATTERN.search(str(k)):
                redacted[k] = "[REDACTED]"
            elif isinstance(v, dict):
                redacted[k] = self._redact_dict(v)
            elif isinstance(v, str):
                redacted[k] = BEARER_PATTERN.sub(r"\1[REDACTED]", v)
            else:
                redacted[k] = v
        return redacted


class ProbeLogSampler(logging.Filter):
    """Filters out 200 OK liveness/readiness probe log spam from INFO level."""

    def filter(self, record: logging.LogRecord) -> bool:
        path = getattr(record, "path", "")
        status = getattr(record, "status_code", 200)
        if path in {"/healthz", "/readyz"} and status < 400 and record.levelno == logging.INFO:
            return False
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as clean, database-queryable JSON key-value objects."""

    def __init__(self, service_name: str = "mcp-tool-server"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": self.service_name,
            "trace_id": getattr(record, "trace_id", None) or get_current_trace_id(),
            "span_id": getattr(record, "span_id", None) or get_current_span_id(),
            "event": getattr(record, "event", "log_event"),
            "module": record.module,
            "message": record.getMessage(),
        }

        # Contextual metadata
        for field in ("http_method", "path", "status_code", "duration_ms", "tool", "hints"):
            if hasattr(record, field):
                log_obj[field] = getattr(record, field)

        # Exception formatting
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            log_obj["exception"] = [
                line.strip() for line in record.exc_text.split("\n") if line.strip()
            ]

        return json.dumps(log_obj)


class TraceCorrelationMiddleware(BaseHTTPMiddleware):
    """ASGI Middleware for W3C & X-Trace-ID propagation and span timing."""

    def __init__(self, app, service_name: str = "mcp-tool-server"):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request, call_next) -> Response:
        w3c_parent = parse_w3c_traceparent(request.headers.get("traceparent", ""))
        if w3c_parent:
            trace_id, span_id = w3c_parent
        else:
            trace_id = request.headers.get("x-trace-id") or request.headers.get("x-request-id") or generate_trace_id()
            span_id = generate_span_id()

        t_token = trace_id_ctx.set(trace_id)
        s_token = span_id_ctx.set(span_id)

        start_time = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log = logging.getLogger("MCP_logger")
            log.info(
                "HTTP request processed",
                extra={
                    "event": "http_request_completed",
                    "http_method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "trace_id": trace_id,
                    "span_id": span_id,
                },
            )
            trace_id_ctx.reset(t_token)
            span_id_ctx.reset(s_token)


def setup_observability(
    app=None,
    log_level: int = logging.INFO,
    structured_json: bool = True,
    log_file: Optional[Path] = None,
    service_name: str = "mcp-tool-server",
) -> None:
    """Configures structured JSON logging, secret masking, log sampling, and file rotation."""
    logger = logging.getLogger("MCP_logger")
    logger.setLevel(log_level)
    logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    if structured_json:
        console_handler.setFormatter(StructuredJsonFormatter(service_name=service_name))
    else:
        console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
        )

    console_handler.addFilter(SecretMaskingFilter())
    console_handler.addFilter(ProbeLogSampler())
    logger.addHandler(console_handler)

    # Rotating File Handler (20 MB max, 5 backups)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_file), maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        if structured_json:
            file_handler.setFormatter(StructuredJsonFormatter(service_name=service_name))
        else:
            file_handler.setFormatter(
                logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
            )
        file_handler.addFilter(SecretMaskingFilter())
        file_handler.addFilter(ProbeLogSampler())
        logger.addHandler(file_handler)

    # Attach Middleware if Starlette/FastAPI app is provided
    if app is not None and hasattr(app, "add_middleware"):
        app.add_middleware(TraceCorrelationMiddleware, service_name=service_name)
