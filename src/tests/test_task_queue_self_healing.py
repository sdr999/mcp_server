"""Tests for Task Queue Zombie Reaper, Worker Respawning, Retries & DLQ (Phase 6, Component 2)."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from src.plugins.task_queue.job_model import Job, JobStatus
from src.plugins.task_queue.queue_engine import InMemoryTaskQueue, TaskQueueEngine


class TestZombieReaper:
    @pytest.mark.asyncio
    async def test_zombie_job_cancellation(self):
        async def slow_callback(tool_name: str, args: dict):
            await asyncio.sleep(10)  # hangs
            return {}

        q = InMemoryTaskQueue(slow_callback, worker_count=1)
        q.job_timeout_sec = 0.1  # fast timeout for test
        await q.start()
        try:
            job = Job(tool_name="slow_tool", input_payload={})
            await q.submit(job)
            await asyncio.sleep(0.05)
            assert job.status == JobStatus.RUNNING

            # Trigger zombie reaper check manually
            now = datetime.now(timezone.utc)
            job.started_at = now - timedelta(seconds=1)
            q._check_zombies()

            assert job.status == JobStatus.FAILED
            assert "zombie reaper" in job.error
        finally:
            await q.stop()


class TestWorkerAutoRespawn:
    @pytest.mark.asyncio
    async def test_worker_respawn_on_crash(self):
        call_count = 0

        async def crashing_callback(tool_name: str, args: dict):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("fatal worker crash")
            return {"ok": True}

        q = InMemoryTaskQueue(crashing_callback, worker_count=1)
        await q.start()
        try:
            j1 = Job(tool_name="crash", input_payload={})
            await q.submit(j1)
            await asyncio.sleep(0.1)

            # Worker crashed, supervisor should auto-respawn worker
            j2 = Job(tool_name="good", input_payload={})
            await q.submit(j2)
            await asyncio.sleep(0.1)

            assert len(q.workers) == 1  # replacement worker alive
        finally:
            await q.stop()


class TestRetriesAndDLQ:
    @pytest.mark.asyncio
    async def test_max_retries_moves_to_dlq(self):
        async def failing_callback(tool_name: str, args: dict):
            raise ValueError("persistent failure")

        engine = TaskQueueEngine("in_memory", failing_callback)
        await engine.start()
        try:
            job = Job(tool_name="fail", input_payload={}, max_retries=0)
            await engine.backend.submit(job)
            await asyncio.sleep(0.1)

            # Max retries exhausted -> moved to DLQ
            dlq_jobs = engine.get_dlq_jobs()
            assert len(dlq_jobs) == 1
            assert dlq_jobs[0].is_dlq is True

            # Test retry_dlq_job
            retried = await engine.retry_dlq_job(job.job_id)
            assert retried is not None
            assert retried.is_dlq is False
            assert retried.retries_count == 0
        finally:
            await engine.stop()
