"""AlertManager evaluating metrics with debounce support."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .channels import WebhookChannel
from .rules import AlertEngine, AlertRule

log = logging.getLogger("MCP_logger")


class AlertManager:
    def __init__(self, webhook_url: Optional[str] = None):
        self.engine = AlertEngine()
        self.webhook_url = webhook_url
        if webhook_url:
            self._setup_default_rules(webhook_url)

    def _setup_default_rules(self, webhook_url: str) -> None:
        channel = WebhookChannel(webhook_url)
        # 1. High Error Rate Rule
        self.engine.add_rule(
            AlertRule(
                name="High Tool Error Rate",
                condition=lambda s: s.get("failed_modules", 0) > 0,
                channels=[channel],
                message_template="MCP Server detected {failed_modules} failed modules during runtime.",
                cooldown_seconds=300.0,
            )
        )

    async def process_metrics(self, stats_dict: Dict[str, Any]) -> None:
        await self.engine.evaluate(stats_dict)
