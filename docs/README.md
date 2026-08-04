# Documentation Index

This project ships two MCP tool servers that share an authoring contract,
auth model, and operational surface:

- **`src/main.py`** — plugin-based, **local** tools only (no Azure); new tools
  arrive as files or via the risk-gated onboarding HTTP API.
- **`src/multiple_mcp_main.py`** — the reference "multiple MCP server" that
  distributes tools via an **Azure File Share**.

Pick a starting point by what you're trying to do.

## By task

| I want to… | Read |
|------------|------|
| Run / configure `src/main.py` (local server) | [MCP_MAIN_SERVER.md](MCP_MAIN_SERVER.md) |
| Run / configure the Azure-backed server + all shared features | [MCP_SERVER_FEATURES.md](MCP_SERVER_FEATURES.md) |
| Secure the server (API key / OAuth-JWT) and connect a client | [MCP_AUTH_GUIDE.md](MCP_AUTH_GUIDE.md) |
| Submit tools over HTTP with dependency risk-gating | [MCP_TOOL_ONBOARDING.md](MCP_TOOL_ONBOARDING.md) |
| Understand *how the code works inside*, module by module | [dev/](dev/README.md) |
| See the history of how this was built | [ACTION_LOG.md](ACTION_LOG.md) |

## All documents

### Operational guides (how to run & configure)

- **[MCP_MAIN_SERVER.md](MCP_MAIN_SERVER.md)** — the plugin-based local server:
  what it is, how it differs from the Azure server, CLI, security defaults, the
  admin/onboarding endpoints unique to it.
- **[MCP_SERVER_FEATURES.md](MCP_SERVER_FEATURES.md)** — the shared feature &
  operations guide: tool authoring contract, configuration (env vars), HTTP
  endpoints, admin API, signed tools, metrics, sandboxing, tool sources.
- **[MCP_AUTH_GUIDE.md](MCP_AUTH_GUIDE.md)** — authorization: `none` /
  `api_key` / `bearer_jwt` (OAuth), server config, client usage, and the
  endpoint × mode matrix.
- **[MCP_TOOL_ONBOARDING.md](MCP_TOOL_ONBOARDING.md)** — the onboarding API:
  the risk-gated flow, dependency scoring table, exposure policy & tool
  manifest, config knobs, and what it deliberately does *not* do.

### Developer guide (how it works inside)

A per-module deep-dive with code snippets — see **[dev/README.md](dev/README.md)**
for the overview, then:

| # | Doc | Covers |
|---|-----|--------|
| 01 | [Configuration](dev/01-configuration.md) | env precedence, `AppContext`, safe `--config` decoding |
| 02 | [Security & Auth](dev/02-security-auth.md) | the three auth modes, admin token, constant-time checks |
| 03 | [Tool Loading](dev/03-tool-loading.md) | `@tool` contract, resolution + report, `prepare`/`commit`, signing |
| 04 | [App & Hot-Reload](dev/04-app-and-hot-reload.md) | lifespan, off-loop imports, watcher, reload drain, locks |
| 05 | [HTTP API & Metrics](dev/05-http-api-metrics.md) | every endpoint, the metrics registry |
| 06 | [Dependency Risk](dev/06-dependency-risk.md) | scoring heuristics, spec grammar, canonicalization, PyPI lookup |
| 07 | [Tool Onboarding](dev/07-tool-onboarding.md) | the full flow, exposure policy, manifest, conflicts, audit |
| 08 | [CLI & Sandbox](dev/08-cli-and-sandbox.md) | `--validate`/`--sign`, the subprocess sandbox |

### Project history

- **[ACTION_LOG.md](ACTION_LOG.md)** — chronological record of the refactor,
  the onboarding endpoint, the review-driven hardening batches, and the
  exposure-policy work, with commit references.

## Where the code lives

```
src/
├── main.py                 # entry point for the plugin-based local server
├── multiple_mcp_main.py    # the Azure-backed reference server
├── tools_sdk.py            # @tool decorator (authoring contract)
├── metrics.py              # Prometheus registry
├── tool_runner.py          # subprocess sandbox entry point
├── tools/                  # the live, hot-reloaded tools directory
└── plugins/                # main.py's single-purpose modules (see dev/ guide)
```
