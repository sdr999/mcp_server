"""Comprehensive tests for the Async Task Queue engine (Phase 5, Item 2).

Covers:
  - in_memory backend: submit, lifecycle transitions, success/failure, job listing
  - celery backend: mocked adapter dispatch and status polling
  - Unknown backend fallback to in_memory with warning
  - Route handlers: POST /tools/{name}/async_call, GET /jobs/{id}, GET /admin/jobs
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.plugins.task_queue.job_model import Job, JobStatus
from src.plugins.task_queue.queue_engine import (
    InMemoryTaskQueue,
    TaskQueueBackend,
    TaskQueueEngine,
)


# ---------------------------------------------------------------------------
# Job Model Tests
# ---------------------------------------------------------------------------
class TestJobModel:
    def test_job_defaults(self):
        job = Job(tool_name="echo", input_payload={"text": "hi"})
        assert job.status == JobStatus.QUEUED
        assert job.result is None
        assert job.error is None
        assert job.job_id  # non-empty uuid
        assert isinstance(job.created_at, datetime)

    def test_job_to_dict(self):
        job = Job(tool_name="echo", input_payload={"x": 1}, tenant_id="t1")
        d = job.to_dict()
        assert d["tool_name"] == "echo"
        assert d["status"] == "QUEUED"
        assert d["tenant_id"] == "t1"
        assert isinstance(d["created_at"], str)  # ISO string

    def test_job_status_enum(self):
        assert JobStatus.QUEUED.value == "QUEUED"
        assert JobStatus.RUNNING.value == "RUNNING"
        assert JobStatus.COMPLETED.value == "COMPLETED"
        assert JobStatus.FAILED.value == "FAILED"


# ---------------------------------------------------------------------------
# InMemoryTaskQueue Backend Tests
# ---------------------------------------------------------------------------
class TestInMemoryTaskQueue:
    @pytest.fixture
    def success_callback(self):
        async def cb(tool_name: str, arguments: dict) -> dict:
            return {"output": f"ran {tool_name}"}
        return cb

    @pytest.fixture
    def fail_callback(self):
        async def cb(tool_name: str, arguments: dict) -> dict:
            raise RuntimeError("tool explosion")
        return cb

    @pytest.mark.asyncio
    async def test_submit_and_complete(self, success_callback):
        q = InMemoryTaskQueue(success_callback, worker_count=1)
        await q.start()
        try:
            job = Job(tool_name="echo", input_payload={"text": "hi"})
            await q.submit(job)
            await asyncio.sleep(0.2)  # let worker process
            result = await q.get_status(job.job_id)
            assert result is not None
            assert result.status == JobStatus.COMPLETED
            assert result.result == {"output": "ran echo"}
            assert result.execution_time_sec is not None
            assert result.execution_time_sec >= 0
            assert result.finished_at is not None
            assert result.started_at is not None
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_submit_failure(self, fail_callback):
        q = InMemoryTaskQueue(fail_callback, worker_count=1)
        await q.start()
        try:
            job = Job(tool_name="bad_tool", input_payload={})
            await q.submit(job)
            await asyncio.sleep(0.2)
            result = await q.get_status(job.job_id)
            assert result is not None
            assert result.status == JobStatus.FAILED
            assert "tool explosion" in result.error
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_list_jobs_sorted(self, success_callback):
        q = InMemoryTaskQueue(success_callback, worker_count=1)
        await q.start()
        try:
            j1 = Job(tool_name="a", input_payload={})
            j2 = Job(tool_name="b", input_payload={})
            # Force distinct timestamps to avoid timing ambiguity
            from datetime import timedelta
            j1.created_at = j1.created_at - timedelta(seconds=1)
            await q.submit(j1)
            await q.submit(j2)
            await asyncio.sleep(0.3)
            jobs = q.list_jobs()
            assert len(jobs) == 2
            # Most recent first (j2 has later created_at)
            assert jobs[0].tool_name == "b"
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self, success_callback):
        q = InMemoryTaskQueue(success_callback)
        result = await q.get_status("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# TaskQueueEngine Facade Tests
# ---------------------------------------------------------------------------
class TestTaskQueueEngine:
    @pytest.fixture
    def callback(self):
        async def cb(tool_name: str, arguments: dict) -> dict:
            return {"ok": True}
        return cb

    @pytest.mark.asyncio
    async def test_in_memory_default(self, callback):
        engine = TaskQueueEngine("in_memory", callback)
        await engine.start()
        try:
            job = await engine.submit_job("echo", {"x": 1}, tenant_id="t1")
            assert job.status == JobStatus.QUEUED
            assert job.tenant_id == "t1"
            await asyncio.sleep(0.2)
            fetched = await engine.get_job(job.job_id)
            assert fetched.status == JobStatus.COMPLETED
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_unknown_backend_fallback(self, callback):
        """Unknown backend name should fall back to in_memory with a warning."""
        with patch("src.plugins.task_queue.queue_engine.log") as mock_log:
            engine = TaskQueueEngine("invalid_backend_xyz", callback)
            assert isinstance(engine.backend, InMemoryTaskQueue)
            mock_log.warning.assert_called()

    @pytest.mark.asyncio
    async def test_get_stats(self, callback):
        engine = TaskQueueEngine("in_memory", callback)
        await engine.start()
        try:
            await engine.submit_job("a", {})
            await engine.submit_job("b", {})
            await asyncio.sleep(0.3)
            stats = engine.get_stats()
            assert stats["completed"] == 2
            assert stats["failed"] == 0
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_list_jobs(self, callback):
        engine = TaskQueueEngine("in_memory", callback)
        await engine.start()
        try:
            await engine.submit_job("tool1", {})
            await asyncio.sleep(0.2)
            jobs = await engine.list_jobs()
            assert len(jobs) == 1
            assert jobs[0].tool_name == "tool1"
        finally:
            await engine.stop()


# ---------------------------------------------------------------------------
# Celery Adapter Tests (Mocked - Celery not required)
# ---------------------------------------------------------------------------
class TestCeleryAdapter:
    @pytest.mark.asyncio
    async def test_celery_submit_dispatches(self):
        """When Celery is available, submit should dispatch via send_task."""
        mock_celery_cls = MagicMock()
        mock_app = MagicMock()
        mock_celery_cls.return_value = mock_app

        with patch.dict("sys.modules", {"celery": MagicMock(Celery=mock_celery_cls)}):
            # Re-import to pick up patched celery
            from importlib import reload
            import src.plugins.task_queue.celery_adapter as ca_mod
            reload(ca_mod)

            adapter = ca_mod.CeleryTaskQueueAdapter("redis://localhost:6379/0", "redis://localhost:6379/1")
            job = Job(tool_name="echo", input_payload={"text": "hi"})
            await adapter.submit(job)
            mock_app.send_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_celery_not_installed_raises(self):
        """When Celery is not installed, adapter init should raise ImportError."""
        with patch.dict("sys.modules", {"celery": None}):
            from importlib import reload
            import src.plugins.task_queue.celery_adapter as ca_mod
            reload(ca_mod)
            with pytest.raises(ImportError, match="[Cc]elery"):
                ca_mod.CeleryTaskQueueAdapter("redis://localhost:6379/0", "redis://localhost:6379/1")


# ---------------------------------------------------------------------------
# Route Handler Tests (via Starlette TestClient)
# ---------------------------------------------------------------------------
class TestTaskQueueRoutes:
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
            task_queue_backend="in_memory",
        )

    @pytest.fixture
    def client(self, test_ctx):
        from src.plugins.app import build_app
        from starlette.testclient import TestClient
        app, _ = build_app(test_ctx)
        return TestClient(app)

    def test_submit_job_returns_202(self, client):
        resp = client.post("/tools/echo/async_call", json={"arguments": {"text": "hello"}})
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "QUEUED"
        assert data["status_url"].startswith("/jobs/")

    def test_get_job_status(self, client):
        resp = client.post("/tools/echo/async_call", json={"arguments": {}})
        job_id = resp.json()["job_id"]
        resp2 = client.get(f"/jobs/{job_id}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["job_id"] == job_id
        assert data["tool_name"] == "echo"

    def test_get_job_not_found(self, client):
        resp = client.get("/jobs/nonexistent-uuid")
        assert resp.status_code == 404

    def test_admin_jobs_requires_token(self, client):
        resp = client.get("/admin/jobs")
        assert resp.status_code in (401, 403)

    def test_admin_jobs_with_token(self, client):
        resp = client.get("/admin/jobs", headers={"Authorization": "Bearer myadmintoken"})
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "recent_jobs" in data
