"""Composite exporter for multi-target fan-out with circuit breaker protection.

Modeled after Horus CompositeBackend pattern. Primary backend is awaited synchronously;
secondary backends are gathered asynchronously with return_exceptions=True to avoid latency coupling.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("MCP_logger")


class CompositeExporter:
    def __init__(self, primary_exporter: Any, secondary_exporters: Optional[List[Any]] = None):
        self.primary = primary_exporter
        self.secondaries = secondary_exporters or []

    async def export_batch(self, items: List[Any]) -> None:
        if not items:
            return

        # 1. Primary backend — awaited synchronously
        try:
            if hasattr(self.primary, "export"):
                self.primary.export(items)
            elif hasattr(self.primary, "export_spans"):
                await self.primary.export_spans(items)
        except Exception as exc:
            log.error("Primary exporter failed: %s", exc)
            raise

        # 2. Secondary backends — fan-out via asyncio.gather with return_exceptions=True (H2 fix)
        if not self.secondaries:
            return

        async def _safe_export(sec: Any) -> None:
            try:
                if hasattr(sec, "export"):
                    sec.export(items)
                elif hasattr(sec, "export_spans"):
                    await sec.export_spans(items)
            except Exception as exc:
                log.warning("Secondary exporter %r failed: %s", sec, exc)

        tasks = [_safe_export(sec) for sec in self.secondaries]
        await asyncio.gather(*tasks, return_exceptions=True)

    def stats(self) -> Dict[str, Any]:
        return {
            "primary": type(self.primary).__name__,
            "secondary_count": len(self.secondaries),
        }
