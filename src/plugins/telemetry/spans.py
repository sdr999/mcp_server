"""Context manager span instrumentation for tools and upstream calls."""
from __future__ import annotations

import contextlib
import time
from typing import Any, Dict, Generator, Optional


@contextlib.contextmanager
def tool_execution_span(
    tool_name: str,
    tenant_id: str = "",
    sandbox_engine: str = "none",
) -> Generator[Optional[Any], None, None]:
    """Context manager for tracing tool executions with span events and attributes."""
    try:
        from opentelemetry import trace
        from opentelemetry.trace import StatusCode

        tracer = trace.get_tracer("mcp-server.tools")
        with tracer.start_as_current_span(f"tool.call:{tool_name}") as span:
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("tenant.id", tenant_id or "default")
            span.set_attribute("sandbox.engine", sandbox_engine)
            span.add_event("tool.start", {"timestamp": time.time()})
            try:
                yield span
                span.set_status(StatusCode.OK)
                span.add_event("tool.end", {"status": "ok"})
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                span.add_event("tool.error", {"error": str(exc)})
                raise
    except ImportError:
        yield None


@contextlib.contextmanager
def upstream_call_span(
    upstream_name: str,
    url: str = "",
) -> Generator[Optional[Any], None, None]:
    """Context manager for tracing upstream federation calls."""
    try:
        from opentelemetry import trace
        from opentelemetry.trace import StatusCode

        tracer = trace.get_tracer("mcp-server.upstreams")
        with tracer.start_as_current_span(f"upstream.call:{upstream_name}") as span:
            span.set_attribute("upstream.name", upstream_name)
            if url:
                span.set_attribute("upstream.url", url)
            try:
                yield span
                span.set_status(StatusCode.OK)
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise
    except ImportError:
        yield None
