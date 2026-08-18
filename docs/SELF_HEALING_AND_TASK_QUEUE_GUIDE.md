# Distributed Task Queue & Enterprise Self-Healing Infrastructure Guide

This guide details the architecture, setup, configuration, API endpoints, and operational behaviors for **Phase 5 (Distributed Task Queue & Active Upstream Health Engine)** and **Phase 6 (Enterprise Self-Healing Infrastructure Suite)**.

---

## 1. Asynchronous Task Queue Engine

The Asynchronous Task Queue decouples long-running or resource-intensive tool execution from HTTP request-response cycles.

### Architecture & Pluggable Backends

```
Client  ──POST /tools/{name}/async_call──►  TaskQueueEngine
                                                  │
                            ┌─────────────────────┼─────────────────────┐
                            ▼                     ▼                     ▼
                       [in_memory]            [celery]                [arq]
                     (4-Worker Pool)     (RabbitMQ / Redis)       (Async Redis)
```

- **`in_memory` (Default)**: Single-container `asyncio.Queue` execution loop with 4 worker tasks. Requires **zero external dependencies or services**.
- **`celery`**: Multi-node worker cluster dispatch via RabbitMQ / Redis. Requires `pip install celery`.
- **`arq`**: High-performance async Redis queue adapter.

### Configuration (`.env`)

```env
# Supported options: 'in_memory' | 'celery' | 'arq'
MCP_TASK_QUEUE_BACKEND=in_memory

# Celery options (if backend=celery)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Execution limits & retries
MCP_TASK_JOB_TIMEOUT_SEC=300.0
MCP_TASK_MAX_RETRIES=3
```

### API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/tools/{name}/async_call` | MCP | Submit async tool call. Returns `202 Accepted` with `job_id` & `status_url`. |
| `GET`  | `/jobs/{job_id}` | None | Poll job lifecycle status (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`). |
| `GET`  | `/admin/jobs` | Admin | Overview of queue performance metrics and recent job history. |
| `GET`  | `/admin/jobs/dlq` | Admin | List jobs in the Dead-Letter Queue. |
| `POST` | `/admin/jobs/dlq/{job_id}/retry` | Admin | Reset retries and re-enqueue a DLQ job. |

---

## 2. Active Upstream Health Prober

The Upstream Health Engine actively monitors remote federated MCP servers (`MCP_UPSTREAMS`) in the background.

### Probing & State Machine

```
   [UNKNOWN]  ──2 successes──►  [HEALTHY]
       │                            │
   1-2 failures                 1-2 failures
       ▼                            ▼
   [DEGRADED] ──3 failures──►  [UNHEALTHY]  (503 Short-Circuit)
```

- **Fast Short-Circuiting**: Requests to `UNHEALTHY` upstreams immediately return `503 Service Unavailable` without waiting for network socket timeouts.
- **Probe Strategy**: Sends HTTP `GET /status` with automatic fallback to `HEAD /`.

### Configuration (`.env`)

```env
MCP_UPSTREAM_PROBE_INTERVAL_SEC=15.0
MCP_UPSTREAM_PROBE_TIMEOUT_SEC=3.0
MCP_UPSTREAM_PROBE_UNHEALTHY_THRESHOLD=3
MCP_UPSTREAM_PROBE_HEALTHY_THRESHOLD=2
```

---

## 3. Enterprise Self-Healing Suite (Phase 6)

The Self-Healing Suite provides automated failure remediation across 5 core runtime domains:

### A. Adaptive Load Shedding & Hysteresis Watchdog (`src/plugins/system_watchdog.py`)
- Monitors system CPU & Memory utilization every 5 seconds.
- **Hysteresis Activation**: Turns load shedding ON at **>85% CPU / >90% Memory**. Turns load shedding OFF only when CPU <75% and Memory <80% for **3 consecutive cycles** (prevents high-frequency flapping).
- Rejects non-essential requests with `503 Service Unavailable (Server Overloaded)` while keeping health check `/status`, `/metrics`, and `/health` endpoints open.

### B. Upstream Failover Groups (`src/plugins/upstreams.py`)
- Upstreams can declare `failover_group` lists of backup upstreams.
- If primary is `UNHEALTHY`, automatically reroutes calls to a `HEALTHY` backup upstream with a strict **1-hop limit** (`hop_count <= 1`) to prevent circular loops.

### C. Task Queue Zombie Reaper & Worker Auto-Spawner (`src/plugins/task_queue/queue_engine.py`)
- **Zombie Reaper**: Cancels hanging worker tasks (`task.cancel()`) after 300s.
- **Worker Crash Supervisor**: Detects worker task exceptions and auto-spawns replacement workers.
- **Backoff Retries & Bounded DLQ**: Retries transient failures up to `max_retries` with exponential backoff ($2^{\text{retry}}$ seconds). Failed jobs move to a DLQ capped at 1,000 items with FIFO eviction.

### D. Storage & SQLite WAL Checkpoint Lock Recovery (`src/plugins/tenancy/sqlite_store.py`)
- On SQLite `database is locked` / `busy` errors, automatically retries operations and triggers non-blocking `PRAGMA wal_checkpoint(PASSIVE)`.
- On permanent disk I/O failure, degrades store to `READ_ONLY` mode to keep read queries (roles, tenants) serving auth safely.

### E. OpenAPI Schema Auto-Coercion (`src/plugins/openapi_plugin.py`)
- Whitelisted coercion for stringified numbers (`"123"` $\rightarrow$ `123`), stringified booleans (`"true"` $\rightarrow$ `True`), and scalars to arrays (`"val"` $\rightarrow$ `["val"]`).
- Retries OpenAPI requests once with coerced arguments on downstream `400 Bad Request`.

---

## 4. Verification

Run the Phase 5 & 6 self-healing test suite:

```bash
python -m pytest src/tests/test_task_queue.py src/tests/test_upstream_health.py src/tests/test_system_watchdog.py src/tests/test_upstream_failover.py src/tests/test_task_queue_self_healing.py src/tests/test_sqlite_auto_recovery.py src/tests/test_openapi_coercion.py -v
```
