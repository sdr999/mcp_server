"""OpenTelemetry integration package for MCP Server Gateway.

Provides trace instrumentation, meter instruments, bidirectional OTel bridge,
and fallback logic for environments where opentelemetry packages are not installed.
"""
from __future__ import annotations

import logging

log = logging.getLogger("MCP_logger")

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry import metrics as otel_metrics
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

from .config import TelemetryConfig
from .bootstrap import init_telemetry, shutdown_telemetry, get_tracer, get_meter
from .spans import tool_execution_span, upstream_call_span

__all__ = [
    "HAS_OTEL",
    "TelemetryConfig",
    "init_telemetry",
    "shutdown_telemetry",
    "get_tracer",
    "get_meter",
    "tool_execution_span",
    "upstream_call_span",
]
