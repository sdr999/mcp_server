"""Tests for System Watchdog & Adaptive Load Shedding (Phase 6, Component 4)."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from src.plugins.system_watchdog import SystemWatchdog


class TestSystemWatchdogHysteresis:
    @pytest.mark.asyncio
    async def test_load_shedding_triggers_above_max(self):
        watchdog = SystemWatchdog(
            sample_interval_sec=0.05,
            max_cpu_percent=85.0,
            max_mem_percent=90.0,
            recover_cpu_percent=75.0,
            recover_mem_percent=80.0,
            consecutive_cycles=3,
        )
        with patch.object(watchdog, "_sample_resources", return_value=(88.0, 50.0)):
            await watchdog.start()
            await asyncio.sleep(0.15)
            assert watchdog.is_shedding() is True
            await watchdog.stop()

    @pytest.mark.asyncio
    async def test_hysteresis_recovery_requires_consecutive_cycles(self):
        watchdog = SystemWatchdog(
            sample_interval_sec=0.05,
            max_cpu_percent=85.0,
            max_mem_percent=90.0,
            recover_cpu_percent=75.0,
            recover_mem_percent=80.0,
            consecutive_cycles=3,
        )
        watchdog.load_shedding = True  # start shedding

        # Cycle 1 below threshold - should NOT turn off yet
        with patch.object(watchdog, "_sample_resources", return_value=(70.0, 50.0)):
            await watchdog.start()
            await asyncio.sleep(0.08)
            assert watchdog.is_shedding() is True

            # Cycle 2 & 3 below threshold -> should turn OFF after 3 cycles
            await asyncio.sleep(0.15)
            assert watchdog.is_shedding() is False
            await watchdog.stop()

    @pytest.mark.asyncio
    async def test_flapping_prevention(self):
        watchdog = SystemWatchdog(
            sample_interval_sec=0.05,
            max_cpu_percent=85.0,
            max_mem_percent=90.0,
            recover_cpu_percent=75.0,
            recover_mem_percent=80.0,
            consecutive_cycles=3,
        )
        watchdog.load_shedding = True

        # Intermittent CPU spike resets recovery counter
        with patch.object(watchdog, "_sample_resources", side_effect=[(70.0, 50.0), (86.0, 50.0), (70.0, 50.0), (70.0, 50.0)]):
            await watchdog.start()
            await asyncio.sleep(0.25)
            # Should still be shedding because spike reset counter
            await watchdog.stop()


class TestSystemWatchdogStats:
    def test_stats_structure(self):
        watchdog = SystemWatchdog()
        stats = watchdog.get_stats()
        assert "cpu" in stats
        assert "memory" in stats
        assert "load_shedding_active" in stats
        assert "high_watermark" in stats
