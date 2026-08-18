"""System Watchdog for Load Shedding."""
from __future__ import annotations

import asyncio
import logging
from typing import Tuple

try:
    import psutil
except ImportError:
    psutil = None

log = logging.getLogger("MCP_logger")

class SystemWatchdog:
    def __init__(
        self,
        sample_interval_sec: float = 5.0,
        max_cpu_percent: float = 85.0,
        max_mem_percent: float = 90.0,
        recover_cpu_percent: float = 75.0,
        recover_mem_percent: float = 80.0,
        consecutive_cycles: int = 3,
    ):
        self.sample_interval_sec = sample_interval_sec
        self.max_cpu_percent = max_cpu_percent
        self.max_mem_percent = max_mem_percent
        self.recover_cpu_percent = recover_cpu_percent
        self.recover_mem_percent = recover_mem_percent
        self.consecutive_cycles = consecutive_cycles

        self.load_shedding: bool = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._recovery_counter = 0

        self._high_watermark_cpu = 0.0
        self._high_watermark_mem = 0.0

    def _sample_resources(self) -> Tuple[float, float]:
        if psutil:
            return psutil.cpu_percent(), psutil.virtual_memory().percent
        return 0.0, 0.0

    async def _watchdog_loop(self):
        while not self._stop_event.is_set():
            try:
                cpu, mem = self._sample_resources()
                self._high_watermark_cpu = max(self._high_watermark_cpu, cpu)
                self._high_watermark_mem = max(self._high_watermark_mem, mem)

                if cpu > self.max_cpu_percent or mem > self.max_mem_percent:
                    if not self.load_shedding:
                        log.warning(f"System overloaded (CPU: {cpu}%, Mem: {mem}%). Enabling load shedding.")
                        self.load_shedding = True
                    self._recovery_counter = 0
                elif self.load_shedding and cpu < self.recover_cpu_percent and mem < self.recover_mem_percent:
                    self._recovery_counter += 1
                    if self._recovery_counter >= self.consecutive_cycles:
                        log.warning(f"System recovered (CPU: {cpu}%, Mem: {mem}%). Disabling load shedding.")
                        self.load_shedding = False
                        self._recovery_counter = 0
                else:
                    self._recovery_counter = 0

            except Exception as e:
                log.error(f"Error in watchdog loop: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.sample_interval_sec)
            except asyncio.TimeoutError:
                pass

    def is_shedding(self) -> bool:
        return self.load_shedding

    async def start(self):
        self._stop_event.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watchdog_loop())

    async def stop(self):
        self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def get_stats(self) -> dict:
        cpu, mem = self._sample_resources()
        return {
            "cpu": cpu,
            "memory": mem,
            "load_shedding_active": self.load_shedding,
            "high_watermark": {
                "cpu": self._high_watermark_cpu,
                "memory": self._high_watermark_mem,
            },
        }
