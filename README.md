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
- **Production Observability & Log Exposure API**: OpenTelemetry W3C `traceparent` context propagation, structured single-line JSON logging, secret masking, health probe sampling, and HTTP log streaming (`GET /admin/logs`).

## Documentation Index

- **[Distributed Observability & Reliability Guide](docs/RELIABILITY_OBSERVABILITY_GUIDE.md)**
- **[OpenAPI MCP Native Plugin Guide](docs/OPENAPI_PLUGIN_GUIDE.md)**
- **[Tool Onboarding & Self-Healing Guide](docs/MCP_TOOL_ONBOARDING.md)**
- **[Server Features & Observability Guide](docs/MCP_SERVER_FEATURES.md)**
- **[Authentication & Authorization Guide](docs/MCP_AUTH_GUIDE.md)**
- **[Full Documentation Index](docs/README.md)**
