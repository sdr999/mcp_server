"""Celery backend adapter for the Task Queue."""
from __future__ import annotations

import logging
from typing import Optional

from .job_model import Job, JobStatus
from .queue_engine import TaskQueueBackend

log = logging.getLogger("MCP_logger")


class CeleryTaskQueueAdapter(TaskQueueBackend):
    def __init__(self, broker_url: str, result_backend: str):
        try:
            from celery import Celery
        except ImportError:
            raise ImportError("Celery is not installed. Run `pip install celery` to use the Celery backend.")

        self.app = Celery("mcp_tasks", broker=broker_url, backend=result_backend)
        self.app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")

    async def submit(self, job: Job) -> None:
        # Fire and forget; state is tracked by Celery
        self.app.send_task(
            "mcp_server.plugins.task_queue.tasks.execute_tool",
            args=[job.tool_name, job.input_payload],
            task_id=job.job_id,
        )

    async def get_status(self, job_id: str) -> Optional[Job]:
        try:
            from celery.result import AsyncResult
        except ImportError:
            return None

        result = AsyncResult(job_id, app=self.app)
        if not result:
            return None

        job = Job(tool_name="unknown", input_payload={})
        job.job_id = job_id
        
        state = result.state
        if state == "PENDING":
            job.status = JobStatus.QUEUED
        elif state == "STARTED":
            job.status = JobStatus.RUNNING
        elif state == "SUCCESS":
            job.status = JobStatus.COMPLETED
            job.result = result.result
        elif state == "FAILURE":
            job.status = JobStatus.FAILED
            job.error = str(result.result)
        else:
            job.status = JobStatus.FAILED

        return job

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
