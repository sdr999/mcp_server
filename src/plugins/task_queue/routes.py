"""Routes for Task Queue API endpoints."""
from __future__ import annotations

import logging
from typing import List

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..security import admin_denied
from .job_model import Job, JobStatus

log = logging.getLogger("MCP_logger")


async def submit_job_handler(request: Request) -> JSONResponse:
    tool_name = request.path_params["name"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    arguments = body.get("arguments", {})
    
    st = request.app.state
    task_queue = getattr(st, "task_queue", None)
    if not task_queue:
        return JSONResponse({"error": "TaskQueueEngine not configured"}, status_code=500)
    
    tenant_id = None
    config = getattr(st, "config", None)
    if config and hasattr(config, "tenant_header"):
        tenant_id = request.headers.get(config.tenant_header)
        
    job = await task_queue.submit_job(tool_name, arguments, tenant_id=tenant_id)
    
    return JSONResponse(
        {
            "job_id": job.job_id,
            "status": job.status.value,
            "status_url": f"/jobs/{job.job_id}"
        },
        status_code=202
    )


async def get_job_handler(request: Request) -> JSONResponse:
    job_id = request.path_params["job_id"]
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return JSONResponse({"error": "TaskQueueEngine not configured"}, status_code=500)
        
    job = await task_queue.get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
        
    return JSONResponse(job.to_dict())


async def admin_jobs_handler(request: Request) -> JSONResponse:
    if denied := await admin_denied(request):
        return denied
        
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return JSONResponse({"error": "TaskQueueEngine not configured"}, status_code=500)
        
    stats = task_queue.get_stats()
    jobs = await task_queue.list_jobs()
    
    return JSONResponse({
        "stats": stats,
        "recent_jobs": [j.to_dict() for j in jobs[:50]]
    })


def task_queue_routes() -> List[Route]:
    return [
        Route("/tools/{name}/async_call", endpoint=submit_job_handler, methods=["POST"]),
        Route("/jobs/{job_id}", endpoint=get_job_handler, methods=["GET"]),
        Route("/admin/jobs", endpoint=admin_jobs_handler, methods=["GET"]),
    ]
