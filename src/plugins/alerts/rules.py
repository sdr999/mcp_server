"""Alerting rules engine adapted from Horus agent-tracer-plus alerts/rules.py."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List

from .channels import AlertChannel

log = logging.getLogger("MCP_logger")


class AlertRule:
    def __init__(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        channels: List[AlertChannel],
        message_template: str,
        cooldown_seconds: float = 300.0,
    ):
        self.name = name
        self.condition = condition
        self.channels = channels
        self.message_template = message_template
        self.cooldown_seconds = cooldown_seconds
        self.last_fired: float = 0.0

    async def evaluate(self, stats: Dict[str, Any]) -> None:
        if self.condition(stats):
            now = time.monotonic()
            if now - self.last_fired < self.cooldown_seconds:
                log.debug("Alert rule %r met but in cooldown", self.name)
                return

            self.last_fired = now
            message = self.message_template.format(**stats)
            for channel in self.channels:
                try:
                    await channel.send(f"Alert Triggered: {self.name}", message, stats)
                except Exception as exc:
                    log.error("Failed to send alert via %r: %s", channel, exc)


class AlertEngine:
    def __init__(self):
        self.rules: List[AlertRule] = []

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)

    async def evaluate(self, stats: Dict[str, Any]) -> None:
        for rule in self.rules:
            await rule.evaluate(stats)
