"""Alert delivery channels using non-blocking httpx with backoff."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger("MCP_logger")


class AlertChannel(ABC):
    @abstractmethod
    async def send(self, subject: str, message: str, context_data: Optional[Dict[str, Any]] = None) -> None:
        pass


class WebhookChannel(AlertChannel):
    """Sends alerts to a generic HTTP Webhook asynchronously with exponential backoff (M3 fix)."""

    def __init__(self, url: str, timeout: float = 5.0, max_retries: int = 3):
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries

    async def send(self, subject: str, message: str, context_data: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "subject": subject,
            "message": message,
            "context": context_data or {},
        }
        backoff = 1.0
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.post(self.url, json=payload)
                    resp.raise_for_status()
                    log.info("Webhook alert delivered to %s", self.url)
                    return
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    if attempt == self.max_retries:
                        log.error("Webhook alert failed after %d retries to %s: %s", self.max_retries, self.url, exc)
                        return
                    await asyncio.sleep(backoff)
                    backoff *= 2.0  # 1s -> 2s -> 4s
