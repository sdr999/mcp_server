"""Asynchronous Audit Logging Engine for Tenancy & Security (Phase 5)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from .base import TenancyStore
from .models import AuditEntry

log = logging.getLogger("MCP_logger")


class AsyncAuditLogger:
    """Non-blocking background audit logger.
    Queues AuditEntry events and flushes them to logs/audit.log (JSONL) and TenancyStore.
    """

    def __init__(self, store: Optional[TenancyStore] = None, log_file: Optional[Path] = None):
        self.store = store
        self.log_file = log_file or Path("logs/audit.log")
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_queue())

    async def log_event(
        self,
        actor_principal: str,
        issuer: str,
        org_id: str,
        action: str,
        resource: str,
        decision: str,
        detail: str = "",
    ) -> None:
        event = {
            "ts": time.time(),
            "actor_principal": actor_principal,
            "issuer": issuer,
            "org_id": org_id,
            "action": action,
            "resource": resource,
            "decision": decision,
            "detail": detail,
        }
        await self._queue.put(event)

    async def _process_queue(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                event = await self._queue.get()
                # 1. Write to JSONL file
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")

                # 2. Write to TenancyStore if available
                if self.store:
                    await self.store.log_audit(
                        actor_principal=event["actor_principal"],
                        issuer=event["issuer"],
                        org_id=event["org_id"],
                        action=event["action"],
                        resource=event["resource"],
                        decision=event["decision"],
                        detail=event["detail"],
                    )
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Failed to process audit event: %s", exc)

    async def stop(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
