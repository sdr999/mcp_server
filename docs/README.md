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
| Follow step-by-step usage for every feature | [Usage](#usage-step-by-step) (below) |
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
| 02 | [Security & Auth](dev/02-security-auth.md) | credentials, configurable per-route policies, a thorough review |
| 03 | [Tool Loading](dev/03-tool-loading.md) | `@tool` contract, resolution + report, `prepare`/`commit`, signing |
| 04 | [App & Hot-Reload](dev/04-app-and-hot-reload.md) | lifespan, off-loop imports, watcher, reload drain, locks |
| 05 | [HTTP API & Metrics](dev/05-http-api-metrics.md) | every endpoint (incl. tool execution), the metrics registry |
| 06 | [Dependency Risk](dev/06-dependency-risk.md) | scoring heuristics, spec grammar, canonicalization, PyPI lookup |
| 07 | [Tool Onboarding](dev/07-tool-onboarding.md) | the full flow, exposure policy, manifest, conflicts, audit |
| 08 | [CLI & Sandbox](dev/08-cli-and-sandbox.md) | `--validate`/`--sign`, the subprocess sandbox |
| 09 | [Federation](dev/09-federation.md) | list/call tools on remote MCP servers |

### Project history

- **[ACTION_LOG.md](ACTION_LOG.md)** — chronological record of the refactor,
  the onboarding endpoint, the review-driven hardening batches, and the
  exposure-policy work, with commit references.

## Usage (step by step)

All commands assume you're in `src/` and the server is `python main.py`. Set a
base URL once: `BASE=http://localhost:8000`.

### 1. Install & run

```bash
pip install -r requirements.txt          # from the repo root
cd src
python main.py                           # serves on 0.0.0.0:8000, tools dir = src/tools
```

Check it's up:

```bash
curl $BASE/healthz      # {"status":"ok"} immediately
curl $BASE/readyz       # {"ready":true} once the initial tool load finishes
```

### 2. Add a tool (local file)

Drop a `.py` file in `src/tools/`. Declare the tool explicitly with `@tool`
(helpers stay private):

```python
# src/tools/weather.py
from tools_sdk import tool

def _to_f(c): return c * 9 / 5 + 32          # helper — not exposed

@tool(name="weather", description="Current weather for a city")
def get_weather(city: str) -> str:
    return f"{city}: {_to_f(21)}F"
```

The filesystem watcher hot-loads it. Confirm:

```bash
curl $BASE/tools        # catalog includes "weather"
curl $BASE/status       # {"ready":true,"stats":{"total_tools":...}}
```

### 3. Execute a tool over HTTP

```bash
curl -X POST $BASE/tools/weather/call \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"city": "Paris"}}'
# {"tool":"weather","is_error":false,"structured_content":{"result":"Paris: 69.8F"},"content":[...]}
```

`404` = unknown/disabled, `400` = bad arguments, `200` with `is_error:true` = the
tool raised. (Tools are also callable by any MCP client over the protocol
endpoint — `/mcp` by default; see step 6.)

### 4. Onboard a tool over HTTP (with dependencies)

Requires the admin token. Low/medium-risk deps auto-install; high-risk is held
pending. (See [MCP_TOOL_ONBOARDING.md](MCP_TOOL_ONBOARDING.md) for the risk model.)

```bash
export MCP_ADMIN_TOKEN=$(openssl rand -hex 32)   # set before starting the server
ADM=(-H "Authorization: Bearer $MCP_ADMIN_TOKEN" -H "Content-Type: application/json")

# a tool with no new dependencies onboards immediately (201)
curl "${ADM[@]}" -X POST $BASE/admin/tools/onboard -d '{
  "name": "reverse",
  "source": "from tools_sdk import tool\n@tool()\ndef reverse(text: str) -> str:\n    return text[::-1]\n"
}'

# review anything held pending, then approve or reject
curl "${ADM[@]:0:2}" $BASE/admin/tools/pending
curl "${ADM[@]}" -X POST $BASE/admin/tools/pending/<name>/approve
curl "${ADM[@]}" -X POST $BASE/admin/tools/pending/<name>/reject
```

### 5. Federate: call tools on other MCP servers

Point the server at upstreams, then list/call their tools through it:

```bash
# configure before starting the server
export MCP_UPSTREAMS='{"billing": {"url": "http://billing-host:8000/sse", "token": "optional"}}'
python main.py

curl $BASE/mcp/upstreams                         # {"upstreams":[{"name":"billing",...}]}
curl $BASE/mcp/upstreams/billing/tools           # remote tool catalog
curl -X POST $BASE/mcp/upstreams/billing/tools/invoice_lookup/call \
  -d '{"arguments": {"id": "INV-42"}}'

# add one at runtime (admin)
curl "${ADM[@]}" -X POST $BASE/admin/mcp/upstreams -d '{"name":"search","url":"http://search:8000/sse"}'
```

### 6. Choose the MCP transport

The server speaks MCP over **Streamable HTTP** by default (single `/mcp`
endpoint); switch to legacy SSE if a client needs it. The REST endpoints
(`/tools/{name}/call`, `/status`, …) are always plain HTTP regardless.

```bash
python main.py                              # default: Streamable HTTP at /mcp
MCP_TRANSPORT=sse python main.py            # legacy SSE at /sse + /messages
MCP_TRANSPORT=http MCP_STATELESS_HTTP=true python main.py   # stateless, for scaling
```

Connect with an MCP client (FastMCP shown):

```python
from fastmcp import Client
async with Client("http://localhost:8000/mcp") as c:   # or ".../sse" in sse mode
    print([t.name for t in await c.list_tools()])
    await c.call_tool("weather", {"city": "Paris"})
```

`curl $BASE/status` reports the active `"transport"`.

### 7. Secure it & configure per-route auth

```bash
# API key (simplest)
MCP_AUTH_TYPE=api_key MCP_API_KEY_HEADER=x-api-key MCP_API_KEY_VALUE=$SECRET python main.py
curl -H "x-api-key: $SECRET" $BASE/status

# OAuth / JWT (resource server)
MCP_AUTH_TYPE=bearer_jwt JWKS_URL=https://idp/.well-known/jwks.json \
MCP_JWT_AUDIENCE=mcp-tools python main.py

# per-route policies (none | mcp | admin):
MCP_METRICS_AUTH=none        # let Prometheus scrape /metrics without a credential
MCP_TOOL_CALL_AUTH=admin     # only operators may execute tools over HTTP
```

Full auth details: [MCP_AUTH_GUIDE.md](MCP_AUTH_GUIDE.md) and
[dev/02](dev/02-security-auth.md).

### 8. Harden with signed tools / sandbox

```bash
# generate a signed manifest, then require it
MCP_TOOL_SIGNING_KEY=$KEY python main.py --sign ./tools
MCP_REQUIRE_SIGNED_TOOLS=true MCP_TOOL_SIGNING_KEY=$KEY python main.py

# run each tool CALL in a subprocess (crash/hang/resource isolation)
MCP_SANDBOX_TOOLS=true MCP_SANDBOX_TIMEOUT_SEC=30 python main.py
```

### 9. Observe & administer

```bash
curl $BASE/metrics                                        # Prometheus text
curl "${ADM[@]}" -X POST $BASE/admin/reload/weather       # reload a tool's module
curl "${ADM[@]}" -X POST $BASE/admin/tool/weather/disable # unregister across reloads
curl "${ADM[@]}" -X POST $BASE/admin/tool/weather/enable
```

### 10. CI: validate a tools directory

```bash
python main.py --validate ./tools     # exit 0 if every module yields a tool, 1 otherwise
```

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
    ├── config, security, tool_loader, signing, watcher, notifications
    ├── routes, app, metrics, cli
    ├── dependency_risk, onboarding      # risk-gated tool onboarding
    └── upstreams                        # federation to remote MCP servers
```
