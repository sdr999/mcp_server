"""Smart Alerting Engine (Phase 3 Webhook Edition).

Modeled after Horus agent-tracer-plus alerts/ package.
"""
from __future__ import annotations

from .channels import AlertChannel, WebhookChannel
from .rules import AlertRule, AlertEngine
from .manager import AlertManager

__all__ = [
    "AlertChannel",
    "WebhookChannel",
    "AlertRule",
    "AlertEngine",
    "AlertManager",
]
