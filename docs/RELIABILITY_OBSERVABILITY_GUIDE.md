# MCP Tool Server — Distributed Observability & Reliability Guide

*A production guide for OpenTelemetry tracing, per-tenant rate limiting, 3-state circuit breakers, real-time SSE admin dashboard, and webhook alerts.*

---

## 🌟 Quickstart ("Use Me")

### 1. Enable OpenTelemetry Tracing (OTLP gRPC Exporter)
Set environment variables in `.env` or system environment:

```env
MCP_OTEL_ENABLED=true
MCP_OTEL_SERVICE_NAME=mcp-gateway
MCP_OTEL_ENDPOINT=http://localhost:4317
MCP_OTEL_SAMPLING_RATE=1.0
```

### 2. Configure Per-Tenant Rate Limiting & Circuit Breakers
```env
MCP_RATE_LIMIT_ENABLED=true
MCP_RATE_LIMIT_DEFAULT_RPM=600
MCP_CIRCUIT_BREAKER_ENABLED=true
MCP_CIRCUIT_BREAKER_THRESHOLD=5
MCP_CIRCUIT_BREAKER_RECOVERY_SEC=30
```

### 3. Access Live Admin Dashboard & Real-Time SSE Stream
Ensure `MCP_ADMIN_TOKEN` is set:
```env
MCP_ADMIN_TOKEN=your-secret-admin-token
```

Then navigate in browser or curl:
- **Interactive UI**: `http://localhost:8000/admin/dashboard?token=your-secret-admin-token`
- **Header Auth**: `curl -H "Authorization: Bearer your-secret-admin-token" http://localhost:8000/admin/dashboard`
- **Real-Time SSE Stream**: `curl -N -H "Authorization: Bearer your-secret-admin-token" http://localhost:8000/admin/dashboard/stream`

### 4. Enable Webhook Alerting
```env
MCP_ALERT_WEBHOOK_URL=https://your-alert-webhook.example.com/alerts
```

---

## 📊 Feature Deep Dive

### 1. OpenTelemetry & Distributed Tracing
The server uses OpenTelemetry for end-to-end trace correlation across incoming HTTP requests, tool executions, and upstream federation calls.

- **Tracing Context Managers**:
  ```python
  from plugins.telemetry import tool_execution_span, upstream_call_span

  # Manually trace custom operations
  with tool_execution_span("weather_tool", tenant_id="tenant_acme"):
      # tool execution logic
      pass
  ```
- **Fallback (`HAS_OTEL`)**:
  If `opentelemetry` packages are not installed, `HAS_OTEL` evaluates to `False` and span context managers become zero-cost no-ops without throwing runtime errors.

- **Bidirectional Bridge**:
  Converts MCP tool spans to standard OTel spans and forwards them to Jaeger, Grafana Tempo, Datadog, or New Relic via OTLP gRPC (`http://localhost:4317`).

---

### 2. Resilience Engine

#### Rate Limiting (`RateLimitEnforcer`)
- **Sliding-Window Algorithm**: Evaluates request timestamps over a 60-second window.
- **Tenant Isolation**: Evaluates limits per `request.state.tenant_id` (extracted by `IdentityMiddleware`).
- **Response Headers**:
  - `X-RateLimit-Remaining`: Remaining request quota in current window.
  - `Retry-After`: Seconds to wait before retrying when rate-limited.
  - `X-RateLimit-Reset`: Unix timestamp when the limit resets.
- **Automatic Stale Tenant Eviction**: Background task purges tenant windows that have been idle > 10 minutes every 5 minutes (memory leak prevention).

#### 3-State Circuit Breaker (`CircuitBreaker`)
- **Transitions**: `CLOSED` $\rightarrow$ `OPEN` $\rightarrow$ `HALF_OPEN` $\rightarrow$ `CLOSED`.
- **Behavior**:
  - `CLOSED`: Normal operation.
  - `OPEN`: When failure count reaches `failure_threshold`, immediately rejects calls with `503 Service Unavailable` + `Retry-After: 30`.
  - `HALF_OPEN`: After `recovery_timeout` (default 30s), permits probe requests. If successful, transitions back to `CLOSED`.

#### Retry Budget (`RetryBudget`)
- Restricts total retry volume to a maximum retry ratio (e.g. max 20% retries over a rolling 60s window) to prevent retry storms.

---

### 3. Live Admin Reliability Dashboard

Access real-time metrics, server health status, active tool count, and live circuit breaker states.

- **URL**: `/admin/dashboard`
- **Security**: Bearer token via `Authorization: Bearer <MCP_ADMIN_TOKEN>` or query parameter `?token=<MCP_ADMIN_TOKEN>`. Rejects invalid requests with `401 Unauthorized`.
- **SSE Stream (`/admin/dashboard/stream`)**:
  - Pushes metrics every 2 seconds.
  - Connection cap: Max 10 active SSE streams (returns `429` if exceeded).
  - Broadcast model: Computes telemetry payload once per tick and broadcasts to all connected clients without redundant database or compute load.

---

### 4. Smart Webhook Alerting

- **Channel**: `WebhookChannel` built on `httpx.AsyncClient` with non-blocking execution and 3-tier exponential backoff retries ($1\text{s} \rightarrow 2\text{s} \rightarrow 4\text{s}$).
- **Default Rules**:
  - Fires alerts when runtime module load failures occur or health thresholds are breached.
- **Debounce**: Per-rule cooldown period (default 300s) suppresses spam alerts.

---

## 🛠️ Configuration Reference

| Environment Variable | Default | Description |
|---|---|---|
| `MCP_OTEL_ENABLED` | `true` | Enable/disable OpenTelemetry integration |
| `MCP_OTEL_SERVICE_NAME` | `mcp-server` | Service name tag on spans & metrics |
| `MCP_OTEL_ENDPOINT` | `http://localhost:4317` | OTLP gRPC collector target endpoint |
| `MCP_OTEL_SAMPLING_RATE` | `1.0` | Sampling probability (0.0 to 1.0) |
| `MCP_RATE_LIMIT_ENABLED` | `true` | Enable per-tenant rate limiting |
| `MCP_RATE_LIMIT_DEFAULT_RPM` | `600` | Default requests per minute per tenant |
| `MCP_CIRCUIT_BREAKER_ENABLED` | `true` | Enable 3-state circuit breaker protection |
| `MCP_CIRCUIT_BREAKER_THRESHOLD` | `5` | Consecutive failures before opening circuit |
| `MCP_CIRCUIT_BREAKER_RECOVERY_SEC` | `30.0` | Seconds to wait before attempting probe recovery |
| `MCP_ALERT_WEBHOOK_URL` | — | HTTP POST target for system alert notifications |

---

## 🧪 Verification & Testing

Run Phase 3 unit & integration tests:
```bash
pytest src/tests/test_telemetry.py src/tests/test_circuit_breaker.py src/tests/test_rate_limiter.py src/tests/test_retry_budget.py src/tests/test_alerts.py src/tests/test_dashboard.py src/tests/test_reliability_integration.py
```

Run full regression test suite:
```bash
pytest --tb=short -q
```
