"""Metrics compatibility shim.

Delegates calls to OTel metrics when available and configured, or legacy in-memory
Prometheus registry otherwise. Maintains 100% backward compatibility for existing code.
"""
from __future__ import annotations

from legacy_metrics import LegacyMetrics

try:
    from plugins.telemetry import HAS_OTEL
    if HAS_OTEL:
        from plugins.telemetry.metrics import OTelMetricsShim
        METRICS = OTelMetricsShim()
    else:
        METRICS = LegacyMetrics()
except Exception:
    METRICS = LegacyMetrics()

__all__ = ["METRICS", "LegacyMetrics"]
