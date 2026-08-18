"""Engine and backends for the Task Queue."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Coroutine, Dict, List, Optional, Any

from .job_model import Job, JobStatus

log = logging.getLogger("MCP_logger")


class TaskQueueBackend(ABC):
    @abstractmethod
    async def submit(self, job: Job) -> None:
        pass

    @abstractmethod
    async def get_status(self, job_id: str) -> Optional[Job]:
        pass

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass


class InMemoryTaskQueue(TaskQueueBackend):
    def __init__(self, execute_callback: Callable[[str, dict], Coroutine[Any, Any, dict]], worker_count: int = 4):
        self.execute_callback = execute_callback
        self.worker_count = worker_count
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.registry: Dict[str, Job] = {}
        self.workers: List[asyncio.Task] = []

    async def submit(self, job: Job) -> None:
        self.registry[job.job_id] = job
        await self.queue.put(job)

    async def get_status(self, job_id: str) -> Optional[Job]:
        return self.registry.get(job_id)

    async def start(self) -> None:
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker_loop(), name=f"TaskWorker-{i}")
            self.workers.append(task)
        log.info("InMemoryTaskQueue started with %d workers", self.worker_count)

    async def stop(self) -> None:
        for task in self.workers:
            task.cancel()
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        log.info("InMemoryTaskQueue stopped")

    async def _worker_loop(self) -> None:
        try:
            while True:
                job = await self.queue.get()
                try:
                    job.status = JobStatus.RUNNING
                    job.started_at = datetime.now(timezone.utc)
                    result = await self.execute_callback(job.tool_name, job.input_payload)
                    job.result = result
                    job.status = JobStatus.COMPLETED
                except Exception as e:
                    log.exception("Task job %s failed", job.job_id)
                    job.error = str(e)
                    job.status = JobStatus.FAILED
                finally:
                    job.finished_at = datetime.now(timezone.utc)
                    if job.started_at:
                        job.execution_time_sec = (job.finished_at - job.started_at).total_seconds()
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass

    def list_jobs(self) -> List[Job]:
        return sorted(self.registry.values(), key=lambda j: j.created_at, reverse=True)


class TaskQueueEngine:
    def __init__(self, backend_name: str, execute_callback: Callable[[str, dict], Coroutine[Any, Any, dict]], app_context=None):
        self.backend_name = (backend_name or "in_memory").lower()
        if self.backend_name == "celery":
            try:
                from .celery_adapter import CeleryTaskQueueAdapter
                broker_url = app_context.celery_broker_url if app_context else "redis://localhost:6379/0"
                result_backend = app_context.celery_result_backend if app_context else "redis://localhost:6379/1"
                self.backend: TaskQueueBackend = CeleryTaskQueueAdapter(broker_url, result_backend)
            except ImportError as e:
                log.warning("Failed to load Celery adapter: %s. Falling back to in_memory.", e)
                self.backend = InMemoryTaskQueue(execute_callback)
        elif self.backend_name == "arq":
            log.warning("ARQ backend not implemented yet. Falling back to in_memory.")
            self.backend = InMemoryTaskQueue(execute_callback)
        else:
            if self.backend_name != "in_memory":
                log.warning("Unknown backend %r, falling back to in_memory", self.backend_name)
            self.backend = InMemoryTaskQueue(execute_callback)

    async def submit_job(self, tool_name: str, arguments: dict, tenant_id: Optional[str] = None) -> Job:
        job = Job(tool_name=tool_name, input_payload=arguments, tenant_id=tenant_id)
        await self.backend.submit(job)
        return job

    async def get_job(self, job_id: str) -> Optional[Job]:
        return await self.backend.get_status(job_id)

    async def list_jobs(self) -> List[Job]:
        if isinstance(self.backend, InMemoryTaskQueue):
            return self.backend.list_jobs()
        return []

    async def start(self) -> None:
        await self.backend.start()

    async def stop(self) -> None:
        await self.backend.stop()

    def get_stats(self) -> dict:
        if not isinstance(self.backend, InMemoryTaskQueue):
            return {"status": f"stats_unsupported_for_{self.backend_name}"}
        
        queued = running = completed = failed = 0
        for j in self.backend.registry.values():
            if j.status == JobStatus.QUEUED:
                queued += 1
            elif j.status == JobStatus.RUNNING:
                running += 1
            elif j.status == JobStatus.COMPLETED:
                completed += 1
            elif j.status == JobStatus.FAILED:
                failed += 1
                
        return {
            "queued": queued,
            "running": running,
            "completed": completed,
            "failed": failed
        }
