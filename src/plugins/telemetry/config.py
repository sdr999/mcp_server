"""Telemetry configuration dataclass (Horus TracerConfig pattern)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class TelemetryConfig:
    service_name: str = "mcp-server"
    otlp_endpoint: str = "http://localhost:4317"
    enabled: bool = True
    sampling_rate: float = 1.0
    batch_size: int = 100
    flush_interval_seconds: float = 5.0
    max_queue_size: int = 10_000
    export_to_console: bool = False
    prometheus_enabled: bool = True

    @classmethod
    def from_env(cls) -> TelemetryConfig:
        return cls(
            service_name=os.getenv("MCP_OTEL_SERVICE_NAME", "mcp-server"),
            otlp_endpoint=os.getenv("MCP_OTEL_ENDPOINT", "http://localhost:4317"),
            enabled=os.getenv("MCP_OTEL_ENABLED", "true").lower() in ("1", "true", "yes"),
            sampling_rate=float(os.getenv("MCP_OTEL_SAMPLING_RATE", "1.0")),
            batch_size=int(os.getenv("MCP_OTEL_BATCH_SIZE", "100")),
            flush_interval_seconds=float(os.getenv("MCP_OTEL_FLUSH_INTERVAL", "5.0")),
            max_queue_size=int(os.getenv("MCP_OTEL_MAX_QUEUE_SIZE", "10000")),
            export_to_console=os.getenv("MCP_OTEL_CONSOLE", "false").lower() in ("1", "true", "yes"),
            prometheus_enabled=os.getenv("MCP_OTEL_PROMETHEUS", "true").lower() in ("1", "true", "yes"),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TelemetryConfig:
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
