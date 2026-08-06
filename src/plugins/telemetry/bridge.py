"""Bidirectional bridge between MCP tool traces and OpenTelemetry.

Modeled after Horus ATPtoOtelBridge pattern.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("MCP_logger")


class MCPtoOtelBridge:
    def __init__(self, endpoint: str = "http://localhost:4317"):
        self.endpoint = endpoint
        self._provider: Any = None
        self._installed = False

    def install(self) -> bool:
        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=self.endpoint, insecure=True)
            self._provider = TracerProvider()
            self._provider.add_span_processor(BatchSpanProcessor(exporter))
            otel_trace.set_tracer_provider(self._provider)

            self._installed = True
            log.info("MCPtoOtelBridge successfully installed -> %s", self.endpoint)
            return True
        except ImportError as exc:
            log.warning("OTel bridge requires opentelemetry packages: %s", exc)
            return False
        except Exception as exc:
            log.error("Failed to install OTel bridge: %s", exc)
            return False

    @property
    def is_installed(self) -> bool:
        return self._installed
