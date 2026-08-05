# MCP Tool Server — Features & Operations Guide

`src/multiple_mcp_main.py` serves tools over SSE (FastMCP). Tool modules are
distributed via an Azure File Share, mirrored locally, and (re)loaded at runtime.
This guide covers the authoring contract, configuration, HTTP endpoints, the admin
API, signed tools, and the CLI utilities.

> **Looking for `src/main.py`?** It shares this authoring contract, auth model,
> signed-tool/sandboxing/metrics features, and HTTP surface, but has no Azure
> (or any remote) tool distribution — tools are always local. It's also split
> into single-purpose plugin modules under `src/plugins/` instead of one file.
> See **[MCP_MAIN_SERVER.md](MCP_MAIN_SERVER.md)**.

---

## 1. Authoring tools

A tool module in the tools directory may expose tools in any of these ways. The
loader uses the **first** mechanism that yields at least one tool:

| # | Mechanism | Example |
|---|-----------|---------|
| 1 | `register(registrar)` hook | `def register(mcp): mcp.add_tool(fn)` |
| 2 | `TOOLS` export | `TOOLS = [fn]` or `TOOLS = {"name": fn}` |
| 3 | `@tool(...)` decorator | `@tool(name="weather", description="…")` |
| 4 | Legacy convention (fallback) | file `my_tool.py` → `def my_tool(...)` |

The tool name is **no longer tied to the file name** (2–3 let you name tools
explicitly and put multiple tools in one file).

```python
# weather.py — multiple tools, explicit names
from tools_sdk import tool

@tool(name="current_weather", description="Weather for a city")
def get_weather(city: str) -> str:
    ...

@tool()                      # name defaults to "forecast"
def forecast(city: str, days: int = 3) -> str:
    ...
```

**Duplicate names** across files: first registration wins; the later one is logged
and skipped.

**Fault isolation:** a tool that fails to import, has a bad signature, raises in
`register()`, or is a non-callable `TOOLS` entry is logged and skipped — it never
stops the server or its siblings. A slow/hanging import is bounded by
`MCP_TOOL_IMPORT_TIMEOUT_SEC` and skipped on timeout.

---

## 2. Configuration (environment variables)

Precedence: an **OS environment variable wins when set and non-blank**; otherwise the
checked-in `config/.env` provides the fallback (a blank OS value like `KEY=""` is
treated as unset, so the fallback still applies). A missing `config/.env` is fine.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TOOL_SOURCE` | `auto` | `auto` (Azure if reachable, else local fallback) \| `azure` (require Azure) \| `local` (never use Azure) |
| `AZURE_FILESTORE_CONNECTION_URL` | — | Azure File Share connection string (required for `azure`; optional for `auto`) |
| `AZURE_FILESTORE_NAME` | — | File share name (required for `azure`; optional for `auto`) |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | Bind address |
| `MCP_POLL_INTERVAL_SEC` | `60` | Azure sync cadence |
| `MCP_TOOL_IMPORT_TIMEOUT_SEC` | `30` | Per-tool import timeout |
| `MCP_AZURE_LOG_LEVEL` | `WARNING` | Azure SDK log level; `INFO`/`DEBUG` re-enables the verbose per-request HTTP logs |
| `MCP_METRICS` | `true` | Wrap tools to record per-call metrics at `/metrics` (loader gauges are always on) |
| `MCP_SANDBOX_TOOLS` | `false` | Run each tool call in a separate process (crash/hang/resource isolation) |
| `MCP_SANDBOX_TIMEOUT_SEC` | `30` | Kill a sandboxed tool call after this many seconds |
| `MCP_SANDBOX_MEM_MB` / `MCP_SANDBOX_CPU_SEC` | `0` | Optional POSIX rlimits for sandbox subprocesses (ignored on Windows) |
| `MCP_AUTH_TYPE` | `none` | `none` \| `api_key` \| `bearer_jwt` |
| `MCP_AUTHENTICATION_FLAG` | `false` | Legacy: `true` ⇒ `bearer_jwt` |
| `MCP_API_KEY_HEADER` / `MCP_API_KEY_VALUE` | `Authorization` / — | api_key mode |
| `JWKS_URL` | — | bearer_jwt mode |
| `MCP_JWT_ISSUER` / `MCP_JWT_AUDIENCE` / `MCP_JWT_REQUIRED_SCOPES` | — | JWT hardening (bind token) |
| `MCP_ADMIN_TOKEN` | — | Enables the admin API (bearer). Unset ⇒ admin disabled |
| `MCP_REQUIRE_SIGNED_TOOLS` | `false` | Only load tools listed in a trusted manifest |
| `MCP_TOOL_MANIFEST` | `tools.manifest.json` | Manifest filename in the tools dir |
| `MCP_TOOL_SIGNING_KEY` | — | HMAC key; when set, the manifest signature must verify |

---

## 3. HTTP endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/healthz` | none (exempt) | Liveness — process is up |
| GET | `/readyz` | none (exempt) | Readiness — `200` only after the initial load; `503` while loading |
| GET | `/status` | api_key* | `{ready, auth, stats:{loaded_modules, total_tools, failed_modules, disabled_tools, failures}}` |
| GET | `/tools` | api_key* | Tool catalog: `[{name, module, description, tags}]` |
| GET | `/metrics` | api_key* | Prometheus metrics (see §6) |
| POST | `/admin/resync` | admin token | Force an immediate Azure sync |
| POST | `/admin/reload/{name}` | admin token | Reload the module that owns a tool |
| POST | `/admin/tool/{name}/disable` | admin token | Unregister a tool and keep it unregistered across reloads |
| POST | `/admin/tool/{name}/enable` | admin token | Re-enable and reload a disabled tool |
| GET | `/sse` | per `MCP_AUTH_TYPE` | MCP SSE stream (clients connect here) |
| POST | `/messages/` | per `MCP_AUTH_TYPE` | MCP JSON-RPC channel; the exact URL (with `session_id`) is handed to the client during the SSE handshake — not called by hand |

\* `/status`, `/tools`, `/metrics` require the MCP credential in both `api_key` and
`bearer_jwt` modes (api key or a valid JWT respectively); they are open only in
`none` mode. Admin endpoints always require `MCP_ADMIN_TOKEN` regardless of MCP auth
mode, and are **disabled** (503) when it is unset. `GET` routes also answer `HEAD`.
Unknown paths return `404`. Interactive Swagger UI documentation is available at `/docs` (and `/swagger`), backed by `/openapi.json` and `/openapi.yaml`.

Readiness split lets a blue-green deploy wait for `/readyz == 200` before routing.

> **Auth:** for full API-key and OAuth (JWT) setup — server config, client usage,
> curl/Python examples, and onboarding `auth_config` — see **[MCP_AUTH_GUIDE.md](MCP_AUTH_GUIDE.md)**.

### 3.1 Example usage

Set a base URL (add `-H "Authorization: Bearer $KEY"` to non-exempt calls when
`MCP_AUTH_TYPE=api_key`):
```bash
BASE=http://localhost:8000
```

**Liveness / readiness**
```bash
curl -s $BASE/healthz
# {"status":"ok"}

curl -s -o /dev/null -w "%{http_code}\n" $BASE/readyz
# 503 while loading, 200 once ready
curl -s $BASE/readyz
# {"ready":true}
```

**Status (load stats)**
```bash
curl -s $BASE/status
# {"ready":true,"auth":"none",
#  "stats":{"loaded_modules":319,"total_tools":319,"failed_modules":151,
#           "disabled_tools":0,"failures":{"traced_uat_tools.extract_pdf_text":"import error: No module named 'PyPDF2'"}}}
```

**Tool catalog**
```bash
curl -s $BASE/tools
# {"tools":[{"name":"weather","module":"onboard.weather","description":"Weather for a city","tags":[]}, ...]}
```

**Admin — resync, reload, disable, enable** (require the admin token)
```bash
ADM=(-H "Authorization: Bearer $MCP_ADMIN_TOKEN")

curl -s "${ADM[@]}" -X POST $BASE/admin/resync
# {"status":"resynced","stats":{"loaded_modules":320,...}}

curl -s "${ADM[@]}" -X POST $BASE/admin/reload/weather
# {"status":"reloaded","tool":"weather","module":"onboard.weather"}

curl -s "${ADM[@]}" -X POST $BASE/admin/tool/weather/disable
# {"status":"disabled","tool":"weather"}

curl -s "${ADM[@]}" -X POST $BASE/admin/tool/weather/enable
# {"status":"enabled","tool":"weather","reloaded":true}

# Without a valid token:
curl -s -o /dev/null -w "%{http_code}\n" -X POST $BASE/admin/resync
# 401  (or 503 if MCP_ADMIN_TOKEN is unset -> admin API disabled)
```

**MCP connection (`/sse` + `/messages/`)** — normally done by an MCP client, not curl.
```bash
# Raw peek at the SSE stream (the server sends the /messages/ endpoint URL as the first event):
curl -N $BASE/sse
```
```python
# Python MCP client:
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async def main():
    async with sse_client("http://localhost:8000/sse") as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()          # discovers registered tools
            result = await s.call_tool("weather", {"city": "Paris"})
```

---

## 4. Signed tools (supply-chain hardening)

With `MCP_REQUIRE_SIGNED_TOOLS=true`, a tool file is imported only if it is listed
in a trusted manifest with a matching SHA-256. If `MCP_TOOL_SIGNING_KEY` is set, the
manifest's own HMAC signature must verify first (so the manifest can't be tampered
with). Manifest format:

```json
{
  "algorithm": "sha256",
  "tools": { "weather.py": "<sha256hex>", "search.py": "<sha256hex>" },
  "signature": "<hmac-sha256 of the sorted tools map>"
}
```

Generate it with the `--sign` CLI (below) and publish it to the tools share.

---

## 5. CLI utilities

```bash
# Run the server (normal mode)
python multiple_mcp_main.py --config <base64 tools-dir path>

# Validate a LOCAL tools directory (CI gate). Exit 0 if all modules yield tools,
# 1 if any failed/empty. Prints JSON stats. No Azure, no server.
python multiple_mcp_main.py --validate ./mytools

# Generate a signed manifest for a LOCAL directory (HMAC if MCP_TOOL_SIGNING_KEY set)
MCP_TOOL_SIGNING_KEY=secret python multiple_mcp_main.py --sign ./mytools
```

Use `--validate` in CI before publishing tools; use `--sign` to (re)generate the
manifest whenever tools change.

---

## 6. Metrics (`/metrics`)

Prometheus text exposition. Loader/registry metrics are always available; per-tool
call metrics require tool wrapping (`MCP_METRICS=true`, the default, or sandbox mode).

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `mcp_ready` | gauge | — | `1` once the initial load completes |
| `mcp_tools_loaded` | gauge | — | Currently registered tools |
| `mcp_modules_failed` | gauge | — | Modules currently failing to load |
| `mcp_tools_disabled` | gauge | — | Disabled tools |
| `mcp_reloads_total` | counter | — | Module (re)loads that registered tools |
| `mcp_load_failures_total` | counter | — | Module loads that failed / yielded no tools |
| `mcp_tool_calls_total` | counter | `tool` | Tool invocations |
| `mcp_tool_errors_total` | counter | `tool` | Invocations that raised |
| `mcp_tool_duration_seconds` | summary | `tool` | `_sum` / `_count` of execution wall-time |

```bash
curl -s $BASE/metrics
# # TYPE mcp_tool_calls_total counter
# mcp_tool_calls_total{tool="weather"} 12.0
# # TYPE mcp_ready gauge
# mcp_ready 1.0
# mcp_tools_loaded 319.0
```
Prometheus scrape (add the api-key header when `MCP_AUTH_TYPE=api_key`):
```yaml
scrape_configs:
  - job_name: mcp-tool-server
    static_configs: [{ targets: ["mcp-host:8000"] }]
```

---

## 7. Sandboxed tool execution

With `MCP_SANDBOX_TOOLS=true`, every tool call runs in a short-lived **subprocess**
(`tool_runner.py`) bounded by `MCP_SANDBOX_TIMEOUT_SEC`. This gives:

- **Crash isolation** — a segfault/`sys.exit`/fatal error kills only that subprocess.
- **Hang isolation** — the call is killed on timeout; the server stays responsive.
- **Resource limits** — CPU/memory via POSIX rlimits (`MCP_SANDBOX_MEM_MB`,
  `MCP_SANDBOX_CPU_SEC`); ignored on Windows.

**What it is not:** this is process isolation, **not** an OS security sandbox. There
are no namespaces/seccomp; a tool still runs as the server's user. For hard security
boundaries, run the server (or the subprocess) in a locked-down container / restricted
user. Combine with **signed tools** (§4) to also control *what* may load.

**Limits:** arguments and results must be JSON-serializable; tools that require an MCP
`Context` or return streaming content are not supported in sandbox mode. Each call pays
subprocess-startup cost, so enable it where isolation matters more than latency.

---

## 8. Tool source & offline / Azure-agnostic operation

The server is not hard-tied to Azure. `MCP_TOOL_SOURCE` controls where tools come from:

| Mode | Behavior |
|------|----------|
| `auto` (default) | Try Azure at startup. If credentials are missing or Azure is unreachable, log a **warning** and fall back to the **local tools directory** — the server still starts and serves whatever is mirrored there. No Azure sync that run. |
| `azure` | Require Azure. Missing creds or an unreachable share is **fatal** (fail fast) — for deployments that mandate Azure. |
| `local` | Never contact Azure. Serve only the local directory (with the file watcher for hot edits). |

In `local`/fallback mode the Azure poller is not started; the file watcher still
provides hot-reload for local edits. `/status` reports the active `source`
(`"azure"` or `"local"`), and `/admin/resync` returns `409` in local mode.

```bash
# Offline / air-gapped: serve a local tools dir, no Azure at all
MCP_TOOL_SOURCE=local python multiple_mcp_main.py --config <b64-path>
```

---

## 10. Production Observability System & Log Exposure API

The server features a production-grade observability system (`src/plugins/observability.py`) built around the three core signals of observability: **Metrics**, **Traces**, and **Logs**.

### Core Observability Architecture

1. **OpenTelemetry W3C Trace Context Propagation**:
   - Extracts incoming `traceparent` or `X-Trace-ID` HTTP headers and propagates trace IDs across async request handlers and sandboxed subprocess execution (`src/tool_runner.py`).
2. **Structured Single-Line JSON Logging (`StructuredJsonFormatter`)**:
   - Emits structured JSON logs to `logs/mcp_server.json.log` with ISO-8601 timestamps, log level, trace_id, span_id, duration_ms, and exception stack traces.
3. **Secret Masking Filter (`SecretMaskingFilter`)**:
   - Automatically redacts Authorization headers, bearer tokens, admin tokens, passwords, and sensitive keys from log output.
4. **Health Probe Log Sampler (`ProbeLogSampler`)**:
   - Suppresses noise by sampling 200 OK `/healthz` and `/readyz` probe logs at INFO level.
5. **Log File Rotation (`RotatingFileHandler`)**:
   - Rotates log files at 20MB with 5 retained backups.

### Log Exposure API Endpoints

#### `GET /admin/logs` & `GET /admin/logs/{log_category}`

Exposes structured server logs and onboarding audit logs over HTTP (requires Admin Token authorization).

**Query Parameters:**
- `type` / `{log_category}`: `"server"` (default), `"audit"`, or `"all"`.
- `limit`: Maximum log records to return (default: 100, max: 1000).
- `level`: Filter by log level (`INFO`, `WARNING`, `ERROR`).
- `trace_id`: Filter logs by OpenTelemetry Trace ID.
- `search`: Substring search across log messages.

**Sample Request:**
```bash
curl -s -H "Authorization: Bearer mysecretadmin" \
  "http://localhost:8000/admin/logs?type=server&level=ERROR"
```

**Sample Response (`200 OK`):**
```json
{
  "log_type": "server",
  "count": 1,
  "logs": [
    {
      "timestamp": "2026-08-05T08:57:00.123Z",
      "level": "ERROR",
      "service": "mcp-tool-server",
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
      "span_id": "00f067aa0ba902b7",
      "event": "tool_call_failed",
      "module": "plugins.routes",
      "message": "Tool 'calculator' failed to execute",
      "exception": ["ZeroDivisionError: division by zero"],
      "log_type": "server"
    }
  ]
}
```

---

## 11. Runtime behavior notes

- **Client notifications:** on a reload the server makes a best-effort attempt to
  push `notifications/tools/list_changed` to connected sessions. FastMCP 3.4.2
  exposes no public session registry, so this degrades to a no-op — clients always
  see changes on their next `list_tools`.
- **Concurrency:** registry mutations (`add_tool`/`remove_tool`) run only on the
  serving event loop; the Azure poller and file watcher only enqueue events.
  Imports run off-loop, bounded by the import timeout.
- **Hot-reload:** the poller mirrors the share atomically (`*.tmp` → `os.replace`);
  the watcher also catches local edits. Deletes unregister the tool.

