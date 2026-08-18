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
        self.dlq_registry: Dict[str, Job] = {}
        self.workers: List[asyncio.Task] = []
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.job_timeout_sec = 300
        self.zombie_reaper_task: Optional[asyncio.Task] = None

    async def submit(self, job: Job) -> None:
        self.registry[job.job_id] = job
        await self.queue.put(job)

    async def get_status(self, job_id: str) -> Optional[Job]:
        return self.registry.get(job_id)

    async def start(self) -> None:
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker_loop(), name=f"TaskWorker-{i}")
            task.add_done_callback(self._worker_crash_supervisor)
            self.workers.append(task)
        self.zombie_reaper_task = asyncio.create_task(self._zombie_reaper_loop())
        log.info("InMemoryTaskQueue started with %d workers", self.worker_count)

    def _worker_crash_supervisor(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Worker task crashed: %s", e)
            if self.zombie_reaper_task and not self.zombie_reaper_task.done():
                new_task = asyncio.create_task(self._worker_loop())
                new_task.add_done_callback(self._worker_crash_supervisor)
                if task in self.workers:
                    self.workers.remove(task)
                self.workers.append(new_task)

    async def stop(self) -> None:
        if self.zombie_reaper_task:
            self.zombie_reaper_task.cancel()
        for task in self.workers:
            task.cancel()
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        log.info("InMemoryTaskQueue stopped")

    async def _zombie_reaper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                self._check_zombies()
        except asyncio.CancelledError:
            pass

    def _check_zombies(self) -> None:
        now = datetime.now(timezone.utc)
        for job in list(self.registry.values()):
            if job.status == JobStatus.RUNNING and job.started_at:
                elapsed = (now - job.started_at).total_seconds()
                if elapsed > self.job_timeout_sec:
                    if task := self.active_tasks.get(job.job_id):
                        task.cancel()
                    job.status = JobStatus.FAILED
                    job.error = "Job execution timed out (zombie reaper)"
                    job.finished_at = now
                    log.warning("Zombie job %s timed out after %ds and was reclaimed", job.job_id, self.job_timeout_sec)

    async def _worker_loop(self) -> None:
        try:
            while True:
                job = await self.queue.get()
                self.active_tasks[job.job_id] = asyncio.current_task()
                try:
                    job.status = JobStatus.RUNNING
                    job.started_at = datetime.now(timezone.utc)
                    result = await self.execute_callback(job.tool_name, job.input_payload)
                    job.result = result
                    job.status = JobStatus.COMPLETED
                    job.finished_at = datetime.now(timezone.utc)
                    job.execution_time_sec = (job.finished_at - job.started_at).total_seconds()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.exception("Task job %s failed", job.job_id)
                    job.error = str(e)
                    job.last_error = str(e)
                    
                    if job.retries_count < job.max_retries:
                        job.retries_count += 1
                        job.status = JobStatus.QUEUED
                        delay = 2 ** job.retries_count
                        log.info("Retrying job %s (attempt %d/%d)", job.job_id, job.retries_count, job.max_retries)
                        asyncio.create_task(self._delayed_requeue(job, delay))
                    else:
                        job.status = JobStatus.FAILED
                        job.is_dlq = True
                        job.finished_at = datetime.now(timezone.utc)
                        if job.started_at:
                            job.execution_time_sec = (job.finished_at - job.started_at).total_seconds()
                        if len(self.dlq_registry) >= 1000:
                            oldest_key = next(iter(self.dlq_registry))
                            self.dlq_registry.pop(oldest_key)
                        self.dlq_registry[job.job_id] = job
                finally:
                    self.active_tasks.pop(job.job_id, None)
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _delayed_requeue(self, job: Job, delay: float) -> None:
        await asyncio.sleep(delay)
        await self.queue.put(job)

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

    def get_dlq_jobs(self) -> List[Job]:
        if hasattr(self.backend, 'dlq_registry'):
            return list(self.backend.dlq_registry.values())
        return []

    async def retry_dlq_job(self, job_id: str) -> Optional[Job]:
        if hasattr(self.backend, 'dlq_registry'):
            job = self.backend.dlq_registry.pop(job_id, None)
            if job:
                job.retries_count = 0
                job.is_dlq = False
                job.error = None
                job.last_error = None
                job.status = JobStatus.QUEUED
                await self.backend.submit(job)
                return job
        return None
