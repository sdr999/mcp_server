# `src/main.py` — Secure, Plugin-Based MCP Tool Server

`src/main.py` is a lightweight sibling of `multiple_mcp_main.py` (see
[MCP_SERVER_FEATURES.md](MCP_SERVER_FEATURES.md)): same tool-authoring
contract, same security posture, same operational surface — but **no remote
tool distribution**. There is no Azure File Share (or any other remote
store): tools always live in a local directory, and a filesystem watcher
gives hot-reload. Everything else — auth, admin API, signed tools, metrics,
sandboxing, fault isolation — is preserved.

Each feature is a separate module under `src/plugins/` instead of one large
file, so any single concern (auth, loading, signing, routing, …) can be read,
tested, and changed in isolation:

| Module | Responsibility |
|--------|-----------------|
| `plugins/config.py` | CLI + environment parsing into an `AppContext`; safe `--config` path resolution (no traversal out of `src/`). |
| `plugins/signing.py` | Signed-tool manifest (SHA-256 + optional HMAC) — supply-chain hardening. |
| `plugins/tool_loader.py` | Fault-isolated tool discovery/registration, metrics wrapping, subprocess sandboxing. |
| `plugins/watcher.py` | Local filesystem watcher — the only source of hot-reload (no remote poller). |
| `plugins/notifications.py` | Best-effort `notifications/tools/list_changed` push to connected clients. |
| `plugins/security.py` | `FastMCP` + JWT verifier construction, API-key middleware, admin-token guard. |
| `plugins/routes.py` | `/healthz`, `/readyz`, `/status`, `/tools`, `/metrics`, `/admin/*`. |
| `plugins/cli.py` | `--validate` / `--sign` CLI utilities. |
| `plugins/app.py` | Wires everything into one ASGI app + lifespan (initial load, then drain reload events). |

## What's different from `multiple_mcp_main.py`

* **No Azure.** `MCP_TOOL_SOURCE`, `AZURE_FILESTORE_CONNECTION_URL`,
  `AZURE_FILESTORE_NAME`, `MCP_POLL_INTERVAL_SEC`, and `MCP_AZURE_LOG_LEVEL`
  do not apply — they're simply not read. Tools are always local.
* `/status` always reports `"source": "local"`.
* `POST /admin/resync` always returns `409` (kept for API-shape parity —
  there's nothing to resync since there's no remote source; the filesystem
  watcher already covers local edits).
* Tool discovery/registration/signing/metrics/sandboxing/auth behave
  identically to `multiple_mcp_main.py` — see
  [MCP_SERVER_FEATURES.md](MCP_SERVER_FEATURES.md) §1 (authoring), §4 (signed
  tools), §6 (metrics), §7 (sandboxing) for details, and
  [MCP_AUTH_GUIDE.md](MCP_AUTH_GUIDE.md) for the full auth setup (still
  applies verbatim — same `MCP_AUTH_TYPE`, same admin token, same endpoint
  matrix).

## CLI

```bash
# Serve using src/tools (auto-created if missing)
python main.py

# Serve using a different local tools directory (base64-encoded, relative to src/)
python main.py --config "$(printf mytools | base64)"

# CI gate: validate a local tools directory, exit 0 if every module yields a tool
python main.py --validate ./mytools

# Generate a signed manifest (HMAC if MCP_TOOL_SIGNING_KEY is set)
MCP_TOOL_SIGNING_KEY=secret python main.py --sign ./mytools
```

## Security defaults

* `MCP_AUTH_TYPE=none` unless configured — set `api_key` or `bearer_jwt` for
  anything beyond local development (see MCP_AUTH_GUIDE.md).
* The admin API (`/admin/*`) is **disabled** (`503`) unless `MCP_ADMIN_TOKEN`
  is set; all credential checks use constant-time comparison
  (`hmac.compare_digest`).
* `--config` is decoded and validated so it cannot resolve outside `src/`
  (rejects absolute paths, `..` segments, and drive-qualified paths).
* A broken tool module is logged and skipped — it never takes down the
  server or its siblings; a hanging import is bounded by
  `MCP_TOOL_IMPORT_TIMEOUT_SEC`.
* Optional `MCP_REQUIRE_SIGNED_TOOLS=true` restricts loading to tools listed
  in a trusted, optionally HMAC-signed manifest.
* Optional `MCP_SANDBOX_TOOLS=true` runs each tool call in a short-lived
  subprocess (crash/hang/resource isolation via `tool_runner.py`).

## Tests

```bash
pytest src/tests/test_plugins_config.py src/tests/test_plugins_tool_loader.py src/tests/test_main_server.py
```
