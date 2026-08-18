# MCP Tool Server

A production-grade, enterprise-ready Model Context Protocol (MCP) Tool Server featuring dynamic tool onboarding, self-healing code resolution, OpenTelemetry trace context propagation, sliding-window rate limiting, 3-state circuit breakers, real-time SSE admin dashboard, and administrative log streaming.

## Feature Overview

- **Distributed Observability & OpenTelemetry Tracing**: Full OpenTelemetry SDK integration (`opentelemetry-api`/`opentelemetry-sdk`), OTLP gRPC export (`http://localhost:4317`), bidirectional `MCPtoOtelBridge`, and backward-compatible Prometheus metrics shim (`src/metrics.py`).
- **Resilience Engine & Fault Tolerance**: Per-tenant sliding-window rate limiting with automated stale bucket eviction, 3-state circuit breakers (`CLOSED` $\rightarrow$ `OPEN` $\rightarrow$ `HALF_OPEN`), and retry ratio budgets.
- **Live Admin Reliability Dashboard**: Single-page dark-themed dashboard (`/admin/dashboard`) with real-time SSE metric stream (`/admin/dashboard/stream`) capped at 10 active connections with Bearer token authentication.
- **Interactive API Documentation & OpenAPI 3.0**: Interactive Swagger UI served at `/docs` (or `/swagger`). Full spec at [`openapi/openapi.yaml`](openapi/openapi.yaml).
- **OpenAPI Spec Native Plugin**: Dynamically converts any OpenAPI 3.0/3.1 REST API spec into live MCP tools (`POST /admin/openapi/register`, `GET /admin/openapi/specs`, `POST /admin/openapi/{id}/remove`). See [`docs/OPENAPI_PLUGIN_GUIDE.md`](docs/OPENAPI_PLUGIN_GUIDE.md).
- **Self-Healing Tool Onboarding Engine**: Submits tools over HTTP, auto-fixes missing imports (`from tools_sdk import tool`), missing `@tool` decorators + docstring extraction, PyPI requirements (`yaml` ➔ `pyyaml`, `PIL` ➔ `pillow`, `cv2` ➔ `opencv-python`), and untyped parameters (`src/plugins/auto_healer.py`).
- **One-Click Tool Reversion**: Restores auto-healed tools back to original source code (`POST /admin/tools/{name}/revert`).
- **Asynchronous Task Queue Engine (Phase 5)**: Decouples long-running tool execution into async jobs (`POST /tools/{name}/async_call` $\rightarrow$ `202 Accepted`). Features pluggable backends (`in_memory` 4-worker pool with zero external dependencies, Celery RabbitMQ/Redis adapter, and ARQ adapter).
- **Active Upstream Health Engine (Phase 5)**: Active background prober (`UpstreamHealthChecker`) running periodic health checks against federated MCP upstreams. Provides 503 fast short-circuiting to prevent network timeout latency on unhealthy upstreams.
- **Enterprise Self-Healing Infrastructure Suite (Phase 6)**:
  - **Adaptive Load Shedding & Hysteresis Watchdog**: Automatically sheds low-priority load with hysteresis thresholds (ON at >85% CPU / >90% Mem, OFF when CPU <75% / Mem <80% for 3 cycles) to prevent server OOM crashes while protecting `/status`, `/metrics`, and `/health`.
  - **Upstream Failover Rerouting**: Dynamic 1-hop failover to healthy backup upstreams when primary upstreams fail.
  - **Task Queue Zombie Reaper & Bounded DLQ**: Reclaims tasks hanging past 300s (`task.cancel()`), auto-spawns crashed worker threads, retries transient errors with exponential backoff, and routes dead jobs to a bounded DLQ (max 1,000 items) with retry capability (`POST /admin/jobs/dlq/{id}/retry`).
  - **SQLite WAL Checkpoint & Read-Only Auto-Recovery**: Non-blocking `PRAGMA wal_checkpoint(PASSIVE)` lock recovery on database busy errors, with graceful `READ_ONLY` degradation to keep auth queries serving during disk I/O errors.
  - **OpenAPI Schema Auto-Coercion**: Safe whitelisted parameter coercion (stringified numbers/booleans, scalar-to-array) with 1-shot execution retry on downstream HTTP 400 Bad Request.

## Documentation Index

- **[Distributed Task Queue & Enterprise Self-Healing Guide](docs/SELF_HEALING_AND_TASK_QUEUE_GUIDE.md)**
- **[Distributed Observability & Reliability Guide](docs/RELIABILITY_OBSERVABILITY_GUIDE.md)**
- **[OpenAPI MCP Native Plugin Guide](docs/OPENAPI_PLUGIN_GUIDE.md)**
- **[Tool Onboarding & Self-Healing Guide](docs/MCP_TOOL_ONBOARDING.md)**
- **[Server Features & Observability Guide](docs/MCP_SERVER_FEATURES.md)**
- **[Authentication & Authorization Guide](docs/MCP_AUTH_GUIDE.md)**
- **[Full Documentation Index](docs/README.md)**
