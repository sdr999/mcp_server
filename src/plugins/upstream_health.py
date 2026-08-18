"""Active Upstream Health Prober."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

import httpx
from starlette.responses import JSONResponse
from starlette.routing import Route

from .security import admin_denied
from .upstreams import UpstreamRegistry

log = logging.getLogger("MCP_logger")


class UpstreamStatus(str, Enum):
    """Health status of an upstream."""
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


@dataclass
class UpstreamHealthState:
    """State of a single upstream's health."""
    name: str
    url: str
    status: UpstreamStatus = UpstreamStatus.UNKNOWN
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_probe_at: Optional[datetime] = None
    last_latency_ms: Optional[float] = None
    last_error: Optional[str] = None


class UpstreamHealthChecker:
    """Background prober for upstream health."""

    def __init__(
        self,
        registry: UpstreamRegistry,
        probe_interval_sec: float = 15.0,
        probe_timeout_sec: float = 3.0,
        unhealthy_threshold: int = 3,
        healthy_threshold: int = 2,
    ):
        self.registry = registry
        self.probe_interval_sec = probe_interval_sec
        self.probe_timeout_sec = probe_timeout_sec
        self.unhealthy_threshold = unhealthy_threshold
        self.healthy_threshold = healthy_threshold
        self._states: Dict[str, UpstreamHealthState] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background probe loop."""
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._probe_loop())
        log.info("UpstreamHealthChecker started.")

    async def stop(self) -> None:
        """Stop the background probe loop."""
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log.info("UpstreamHealthChecker stopped.")

    async def _probe_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._probe_all()
            except Exception as e:
                log.error(f"Error in upstream probe loop: {e}")
                
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.probe_interval_sec)
            except asyncio.TimeoutError:
                pass

    async def _probe_all(self) -> None:
        # Access the registry servers
        upstreams = self.registry._servers
        
        # Initialize missing states
        for name, spec in upstreams.items():
            if name not in self._states:
                self._states[name] = UpstreamHealthState(name=name, url=spec.get("url", ""))
            else:
                self._states[name].url = spec.get("url", "")

        async with httpx.AsyncClient(timeout=self.probe_timeout_sec) as client:
            tasks = []
            for name in list(self._states.keys()):
                if name not in upstreams:
                    self._states.pop(name, None)
                    continue
                tasks.append(self._probe_single(client, self._states[name]))
            
            if tasks:
                await asyncio.gather(*tasks)

    async def _probe_single(self, client: httpx.AsyncClient, state: UpstreamHealthState) -> None:
        url = state.url
        if not url:
            self._record_failure(state, 0.0, "No URL configured")
            return

        target_url = url.rstrip("/") + "/status"
        start_time = asyncio.get_running_loop().time()
        
        try:
            response = await client.get(target_url)
            if response.status_code == 404:
                # Fallback to HEAD / if /status is not found
                response = await client.head(url)
            response.raise_for_status()
            
            latency_ms = (asyncio.get_running_loop().time() - start_time) * 1000
            self._record_success(state, latency_ms)
        except Exception as e:
            latency_ms = (asyncio.get_running_loop().time() - start_time) * 1000
            self._record_failure(state, latency_ms, str(e))

    def _record_success(self, state: UpstreamHealthState, latency_ms: float) -> None:
        state.last_probe_at = datetime.now(timezone.utc)
        state.last_latency_ms = latency_ms
        state.last_error = None
        state.consecutive_successes += 1
        state.consecutive_failures = 0

        if state.status in (UpstreamStatus.UNHEALTHY, UpstreamStatus.UNKNOWN, UpstreamStatus.DEGRADED):
            if state.consecutive_successes >= self.healthy_threshold:
                state.status = UpstreamStatus.HEALTHY
                log.info(f"Upstream {state.name} is now HEALTHY.")
            elif state.status == UpstreamStatus.UNKNOWN:
                state.status = UpstreamStatus.DEGRADED

    def _record_failure(self, state: UpstreamHealthState, latency_ms: float, error: str) -> None:
        state.last_probe_at = datetime.now(timezone.utc)
        state.last_latency_ms = latency_ms
        state.last_error = error
        state.consecutive_failures += 1
        state.consecutive_successes = 0

        if state.status in (UpstreamStatus.HEALTHY, UpstreamStatus.UNKNOWN, UpstreamStatus.DEGRADED):
            if state.consecutive_failures >= self.unhealthy_threshold:
                state.status = UpstreamStatus.UNHEALTHY
                log.warning(f"Upstream {state.name} is now UNHEALTHY (error: {error}).")
            else:
                if state.status != UpstreamStatus.UNKNOWN:
                    state.status = UpstreamStatus.DEGRADED

    def is_healthy(self, name: str) -> bool:
        """Return True only if status is HEALTHY or UNKNOWN."""
        state = self._states.get(name)
        if not state:
            return True
        return state.status in (UpstreamStatus.HEALTHY, UpstreamStatus.UNKNOWN)

    def get_status(self, name: str) -> Optional[UpstreamHealthState]:
        """Get the health state of a specific upstream."""
        return self._states.get(name)

    def get_all_status(self) -> dict[str, dict]:
        """Return all upstream health states as dicts for JSON serialization."""
        res = {}
        for name, state in self._states.items():
            res[name] = {
                "name": state.name,
                "url": state.url,
                "status": state.status.value,
                "consecutive_failures": state.consecutive_failures,
                "consecutive_successes": state.consecutive_successes,
                "last_probe_at": state.last_probe_at.isoformat() if state.last_probe_at else None,
                "last_latency_ms": state.last_latency_ms,
                "last_error": state.last_error,
            }
        return res

    def get_stats(self) -> dict:
        """Return summary stats for the dashboard."""
        total = len(self._states)
        healthy = sum(1 for s in self._states.values() if s.status == UpstreamStatus.HEALTHY)
        unhealthy = sum(1 for s in self._states.values() if s.status == UpstreamStatus.UNHEALTHY)
        degraded = sum(1 for s in self._states.values() if s.status == UpstreamStatus.DEGRADED)
        unknown = sum(1 for s in self._states.values() if s.status == UpstreamStatus.UNKNOWN)
        return {
            "total_upstreams": total,
            "healthy_upstreams": healthy,
            "unhealthy_upstreams": unhealthy,
            "degraded_upstreams": degraded,
            "unknown_upstreams": unknown,
        }


async def health_status_handler(request) -> JSONResponse:
    """Admin-only endpoint to get all upstream health states."""
    if denied := await admin_denied(request):
        return denied
    
    st = request.app.state
    checker: Optional[UpstreamHealthChecker] = getattr(st, "upstream_health_checker", None)
    if not checker:
        return JSONResponse(
            {"error": "Service Unavailable", "message": "Upstream health checker not configured."},
            status_code=503
        )
        
    return JSONResponse(checker.get_all_status())


def upstream_health_routes() -> List[Route]:
    """Routes for upstream health monitoring."""
    return [
        Route("/admin/upstreams/health", endpoint=health_status_handler, methods=["GET"]),
    ]
