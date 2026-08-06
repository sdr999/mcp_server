"""Async batch processor for metrics and span processing."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, List, Optional

log = logging.getLogger("MCP_logger")


class MetricsBatchProcessor:
    def __init__(
        self,
        exporter_fn: Callable[[List[Any]], Any],
        batch_size: int = 100,
        flush_interval: float = 5.0,
        max_queue_size: int = 10000,
    ):
        self.exporter_fn = exporter_fn
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._worker_loop())
        except RuntimeError:
            pass

    async def _worker_loop(self) -> None:
        batch: List[Any] = []
        last_flush = asyncio.get_event_loop().time()

        while self._running:
            try:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                    batch.append(item)
                    self.queue.task_done()
                except asyncio.TimeoutError:
                    pass

                now = asyncio.get_event_loop().time()
                if len(batch) >= self.batch_size or (batch and (now - last_flush) >= self.flush_interval):
                    await self._flush_batch(batch)
                    batch = []
                    last_flush = now
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("BatchProcessor worker error: %s", exc)

        if batch:
            await self._flush_batch(batch)

    async def _flush_batch(self, batch: List[Any]) -> None:
        try:
            res = self.exporter_fn(batch)
            if asyncio.iscoroutine(res):
                await res
        except Exception as exc:
            log.error("Failed to flush batch of %d items: %s", len(batch), exc)

    async def enqueue(self, item: Any) -> bool:
        try:
            self.queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            log.warning("BatchProcessor queue full — dropping item")
            return False

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
