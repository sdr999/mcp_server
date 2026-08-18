"""Tests for Upstream Failover Groups & Rerouting (Phase 6, Component 1)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.plugins.upstreams import UpstreamRegistry, UpstreamError
from src.plugins.upstream_health import UpstreamStatus, UpstreamHealthState


class FakeHealthChecker:
    def __init__(self, healthy_servers: set[str]):
        self.healthy_servers = healthy_servers

    def is_healthy(self, name: str) -> bool:
        return name in self.healthy_servers


class TestUpstreamFailover:
    @pytest.mark.asyncio
    async def test_failover_to_healthy_backup(self):
        reg = UpstreamRegistry()
        reg.add("primary", "http://primary:8000", failover_group=["backup1", "backup2"])
        reg.add("backup1", "http://backup1:8000")
        reg.add("backup2", "http://backup2:8000")

        # Primary is UNHEALTHY, backup1 is HEALTHY
        checker = FakeHealthChecker(healthy_servers={"backup1"})

        with patch.object(reg, "_client") as mock_client:
            mock_c = AsyncMock()
            mock_c.call_tool = AsyncMock(return_value=MagicMock(content=[], is_error=False, structured_content=None))
            mock_c.__aenter__ = AsyncMock(return_value=mock_c)
            mock_c.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_c

            # Call on primary should auto-reroute to backup1
            res = await reg.call_tool("primary", "echo", {"x": 1}, health_checker=checker)
            assert res["upstream"] == "backup1"

    @pytest.mark.asyncio
    async def test_failover_hop_limit(self):
        reg = UpstreamRegistry()
        reg.add("primary", "http://primary:8000", failover_group=["backup1"])
        reg.add("backup1", "http://backup1:8000", failover_group=["backup2"])
        reg.add("backup2", "http://backup2:8000")

        # All servers UNHEALTHY
        checker = FakeHealthChecker(healthy_servers=set())

        with pytest.raises(UpstreamError, match="UNHEALTHY"):
            await reg.call_tool("primary", "echo", {}, health_checker=checker)
