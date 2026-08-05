# MCP Tool Server

A production-grade, enterprise-ready Model Context Protocol (MCP) Tool Server featuring dynamic tool onboarding, self-healing code resolution, OpenTelemetry trace context propagation, and administrative log streaming.

## Feature Overview

- **Interactive API Documentation & OpenAPI 3.0**: Interactive Swagger UI served at `/docs` (or `/swagger`). Full spec at [`openapi/openapi.yaml`](openapi/openapi.yaml).
- **OpenAPI Spec Native Plugin**: Dynamically converts any OpenAPI 3.0/3.1 REST API spec into live MCP tools (`POST /admin/openapi/register`, `GET /admin/openapi/specs`, `POST /admin/openapi/{id}/remove`). See [`docs/OPENAPI_PLUGIN_GUIDE.md`](docs/OPENAPI_PLUGIN_GUIDE.md).
- **Self-Healing Tool Onboarding Engine**: Submits tools over HTTP, auto-fixes missing imports (`from tools_sdk import tool`), missing `@tool` decorators + docstring extraction, PyPI requirements (`yaml` ➔ `pyyaml`, `PIL` ➔ `pillow`, `cv2` ➔ `opencv-python`), and untyped parameters (`src/plugins/auto_healer.py`).
- **One-Click Tool Reversion**: Restores auto-healed tools back to original source code (`POST /admin/tools/{name}/revert`).
- **Production Observability & Log Exposure API**: OpenTelemetry W3C `traceparent` context propagation, structured single-line JSON logging, secret masking, health probe sampling, and HTTP log streaming (`GET /admin/logs`).

## Documentation Index

- **[OpenAPI MCP Native Plugin Guide](docs/OPENAPI_PLUGIN_GUIDE.md)**
- **[Tool Onboarding & Self-Healing Guide](docs/MCP_TOOL_ONBOARDING.md)**
- **[Server Features & Observability Guide](docs/MCP_SERVER_FEATURES.md)**
- **[Authentication & Authorization Guide](docs/MCP_AUTH_GUIDE.md)**
- **[Full Documentation Index](docs/README.md)**


