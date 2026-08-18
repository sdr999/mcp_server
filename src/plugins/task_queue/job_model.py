"""Job model and status for async task queue."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


class JobStatus(Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    tool_name: str
    input_payload: dict
    job_id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: Optional[str] = None
    status: JobStatus = JobStatus.QUEUED
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    execution_time_sec: Optional[float] = None
    retries_count: int = 0
    max_retries: int = 3
    is_dlq: bool = False
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        if self.created_at:
            d["created_at"] = self.created_at.isoformat()
        if self.started_at:
            d["started_at"] = self.started_at.isoformat()
        if self.finished_at:
            d["finished_at"] = self.finished_at.isoformat()
        d["retries_count"] = self.retries_count
        d["max_retries"] = self.max_retries
        d["is_dlq"] = self.is_dlq
        d["last_error"] = self.last_error
        return d
