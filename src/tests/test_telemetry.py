"""Unit tests for telemetry package (bootstrap, config, spans, metrics, bridge)."""
from __future__ import annotations

import pytest

from src.plugins.telemetry import (
    HAS_OTEL,
    TelemetryConfig,
    get_meter,
    get_tracer,
    init_telemetry,
    shutdown_telemetry,
    tool_execution_span,
    upstream_call_span,
)


def test_telemetry_config_defaults():
    config = TelemetryConfig.from_dict({"service_name": "test-service", "unknown_key": "ignore"})
    assert config.service_name == "test-service"
    assert config.otlp_endpoint == "http://localhost:4317"


def test_telemetry_bootstrap_lifecycle():
    config = TelemetryConfig(enabled=True, service_name="test-mcp")
    initialized = init_telemetry(config)
    if HAS_OTEL:
        assert initialized is True
        tracer = get_tracer("test")
        assert tracer is not None
    else:
        assert initialized is False

    shutdown_telemetry()


def test_tool_execution_span_context_manager():
    with tool_execution_span("test_tool", tenant_id="tenant_a", sandbox_engine="none") as span:
        pass  # Executed cleanly


def test_upstream_call_span_context_manager():
    with upstream_call_span("github_upstream", url="https://api.github.com") as span:
        pass  # Executed cleanly
