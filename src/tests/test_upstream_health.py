"""Comprehensive tests for the Active Upstream Health Prober (Phase 5, Item 6).

Covers:
  - HEALTHY probing (2xx response)
  - UNHEALTHY threshold trip (3 consecutive failures)
  - HEALTHY recovery threshold (2 consecutive successes after UNHEALTHY)
  - Environment timing overrides (custom intervals)
  - is_healthy() gating behavior
  - get_all_status() JSON serialization
  - Dashboard stats integration
  - Admin route handler
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.plugins.upstream_health import (
    UpstreamHealthChecker,
    UpstreamHealthState,
    UpstreamStatus,
    upstream_health_routes,
)
from src.plugins.upstreams import UpstreamRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_registry(upstreams: dict | None = None) -> UpstreamRegistry:
    return UpstreamRegistry(upstreams or {}, timeout=5.0, allow_runtime=False)


def _make_checker(registry: UpstreamRegistry, **kwargs) -> UpstreamHealthChecker:
    defaults = dict(
        probe_interval_sec=0.1,  # fast for tests
        probe_timeout_sec=1.0,
        unhealthy_threshold=3,
        healthy_threshold=2,
    )
    defaults.update(kwargs)
    return UpstreamHealthChecker(registry=registry, **defaults)


class FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# Unit Tests: State Machine
# ---------------------------------------------------------------------------
class TestUpstreamHealthState:
    def test_default_status_is_unknown(self):
        state = UpstreamHealthState(name="server1", url="http://localhost:9000")
        assert state.status == UpstreamStatus.UNKNOWN
        assert state.consecutive_failures == 0
        assert state.consecutive_successes == 0


class TestHealthCheckerStateMachine:
    def test_record_success_transitions_to_healthy(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        state = UpstreamHealthState(name="s1", url="http://s1:9000")
        # Need healthy_threshold (2) consecutive successes
        checker._record_success(state, 10.0)
        assert state.status != UpstreamStatus.HEALTHY  # only 1 success
        checker._record_success(state, 12.0)
        assert state.status == UpstreamStatus.HEALTHY
        assert state.consecutive_successes == 2
        assert state.consecutive_failures == 0

    def test_record_failure_transitions_to_unhealthy(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        state = UpstreamHealthState(name="s1", url="http://s1:9000", status=UpstreamStatus.HEALTHY)
        # Need unhealthy_threshold (3) consecutive failures
        checker._record_failure(state, 5.0, "timeout")
        assert state.status == UpstreamStatus.DEGRADED  # 1 failure
        checker._record_failure(state, 5.0, "timeout")
        assert state.status == UpstreamStatus.DEGRADED  # 2 failures
        checker._record_failure(state, 5.0, "timeout")
        assert state.status == UpstreamStatus.UNHEALTHY  # 3 failures → threshold
        assert state.consecutive_failures == 3

    def test_recovery_from_unhealthy(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        state = UpstreamHealthState(
            name="s1", url="http://s1:9000",
            status=UpstreamStatus.UNHEALTHY, consecutive_failures=3,
        )
        checker._record_success(state, 8.0)
        assert state.status == UpstreamStatus.UNHEALTHY  # 1 success, not enough
        assert state.consecutive_failures == 0
        checker._record_success(state, 9.0)
        assert state.status == UpstreamStatus.HEALTHY  # 2 successes → recovered
        assert state.consecutive_successes == 2

    def test_failure_resets_success_counter(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        state = UpstreamHealthState(
            name="s1", url="http://s1:9000",
            status=UpstreamStatus.UNHEALTHY, consecutive_successes=1,
        )
        checker._record_failure(state, 5.0, "conn refused")
        assert state.consecutive_successes == 0
        assert state.consecutive_failures == 1


# ---------------------------------------------------------------------------
# Unit Tests: is_healthy
# ---------------------------------------------------------------------------
class TestIsHealthy:
    def test_unknown_upstream_is_healthy(self):
        checker = _make_checker(_make_registry())
        assert checker.is_healthy("nonexistent") is True

    def test_healthy_status_returns_true(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        checker._states["s1"] = UpstreamHealthState(
            name="s1", url="http://s1:9000", status=UpstreamStatus.HEALTHY)
        assert checker.is_healthy("s1") is True

    def test_unhealthy_status_returns_false(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        checker._states["s1"] = UpstreamHealthState(
            name="s1", url="http://s1:9000", status=UpstreamStatus.UNHEALTHY)
        assert checker.is_healthy("s1") is False

    def test_unknown_status_returns_true(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        checker._states["s1"] = UpstreamHealthState(
            name="s1", url="http://s1:9000", status=UpstreamStatus.UNKNOWN)
        assert checker.is_healthy("s1") is True


# ---------------------------------------------------------------------------
# Integration: Probe Loop with Mocked httpx
# ---------------------------------------------------------------------------
class TestProbeLoop:
    @pytest.mark.asyncio
    async def test_successful_probe_marks_healthy(self):
        registry = _make_registry({"backend": {"url": "http://backend:8080"}})
        checker = _make_checker(registry, probe_interval_sec=60)  # long interval, we call manually

        mock_response = FakeResponse(200)
        with patch("src.plugins.upstream_health.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.head = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            # Call probe directly (2 times for healthy threshold)
            await checker._probe_all()
            await checker._probe_all()

            state = checker.get_status("backend")
            assert state is not None
            assert state.status == UpstreamStatus.HEALTHY
            assert state.last_latency_ms is not None

    @pytest.mark.asyncio
    async def test_failed_probes_trip_unhealthy(self):
        registry = _make_registry({"backend": {"url": "http://backend:8080"}})
        checker = _make_checker(registry, unhealthy_threshold=3)

        with patch("src.plugins.upstream_health.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=Exception("connection refused"))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            await checker._probe_all()
            await checker._probe_all()
            await checker._probe_all()

            state = checker.get_status("backend")
            assert state is not None
            assert state.status == UpstreamStatus.UNHEALTHY
            assert state.last_error is not None
            assert "connection refused" in state.last_error

    @pytest.mark.asyncio
    async def test_404_fallback_to_head(self):
        """If /status returns 404, should fallback to HEAD /."""
        registry = _make_registry({"backend": {"url": "http://backend:8080"}})
        checker = _make_checker(registry)

        head_response = FakeResponse(200)
        status_response = FakeResponse(404)

        with patch("src.plugins.upstream_health.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=status_response)
            mock_instance.head = AsyncMock(return_value=head_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            await checker._probe_all()
            # HEAD succeeded so this counts as a success
            state = checker.get_status("backend")
            assert state.consecutive_successes == 1


# ---------------------------------------------------------------------------
# JSON Serialization
# ---------------------------------------------------------------------------
class TestGetAllStatus:
    def test_get_all_status_serializable(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        checker._states["s1"] = UpstreamHealthState(
            name="s1", url="http://s1:9000",
            status=UpstreamStatus.HEALTHY,
            last_probe_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            last_latency_ms=12.5,
        )
        result = checker.get_all_status()
        assert "s1" in result
        assert result["s1"]["status"] == "HEALTHY"
        assert result["s1"]["last_latency_ms"] == 12.5
        assert isinstance(result["s1"]["last_probe_at"], str)


# ---------------------------------------------------------------------------
# Stats for Dashboard
# ---------------------------------------------------------------------------
class TestGetStats:
    def test_stats_counts(self):
        checker = _make_checker(_make_registry())
        checker._states["a"] = UpstreamHealthState(name="a", url="", status=UpstreamStatus.HEALTHY)
        checker._states["b"] = UpstreamHealthState(name="b", url="", status=UpstreamStatus.UNHEALTHY)
        checker._states["c"] = UpstreamHealthState(name="c", url="", status=UpstreamStatus.UNKNOWN)
        stats = checker.get_stats()
        assert stats["total_upstreams"] == 3
        assert stats["healthy_upstreams"] == 1
        assert stats["unhealthy_upstreams"] == 1
        assert stats["unknown_upstreams"] == 1


# ---------------------------------------------------------------------------
# Environment Config Override Tests
# ---------------------------------------------------------------------------
class TestConfigOverrides:
    def test_custom_intervals(self):
        checker = _make_checker(
            _make_registry(),
            probe_interval_sec=0.5,
            probe_timeout_sec=2.0,
            unhealthy_threshold=5,
            healthy_threshold=3,
        )
        assert checker.probe_interval_sec == 0.5
        assert checker.probe_timeout_sec == 2.0
        assert checker.unhealthy_threshold == 5
        assert checker.healthy_threshold == 3


# ---------------------------------------------------------------------------
# Lifecycle Tests
# ---------------------------------------------------------------------------
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        checker = _make_checker(_make_registry({"s1": {"url": "http://s1:9000"}}))
        await checker.start()
        assert checker._task is not None
        await checker.stop()
        assert checker._task is None

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        checker = _make_checker(_make_registry())
        await checker.start()
        first_task = checker._task
        await checker.start()
        assert checker._task is first_task  # same task, not duplicated
        await checker.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop(self):
        checker = _make_checker(_make_registry())
        await checker.stop()  # should not raise


# ---------------------------------------------------------------------------
# Admin Route Test
# ---------------------------------------------------------------------------
class TestAdminRoute:
    @pytest.fixture
    def test_ctx(self, tmp_path):
        from src.plugins.config import AppContext
        tools = tmp_path / "tools"
        tools.mkdir()
        return AppContext(
            base_dir=tmp_path,
            tools_dir=tools,
            env={},
            auth_type="none",
            api_key_header="X-API-Key",
            api_key_value="secret",
            jwks_url="",
            jwt_issuer=None,
            jwt_audience=None,
            jwt_required_scopes=None,
            host="127.0.0.1",
            port=8000,
            import_timeout=5.0,
            metrics_enabled=True,
            sandbox=False,
            sandbox_timeout=5.0,
            sandbox_mem_mb=0,
            sandbox_cpu_sec=0,
            admin_token="myadmintoken",
            require_signed=False,
            manifest_name="manifest.json",
            signing_key=None,
        )

    @pytest.fixture
    def client(self, test_ctx):
        from src.plugins.app import build_app
        from starlette.testclient import TestClient
        app, _ = build_app(test_ctx)
        return TestClient(app)

    def test_upstream_health_admin_requires_token(self, client):
        resp = client.get("/admin/upstreams/health")
        assert resp.status_code in (401, 403)

    def test_upstream_health_admin_with_token(self, client):
        resp = client.get(
            "/admin/upstreams/health",
            headers={"Authorization": "Bearer myadmintoken"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
