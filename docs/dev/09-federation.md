# 09 — Federation: remote MCP servers (`plugins/upstreams.py`)

**Job:** let this server list and execute tools on **other MCP servers**
("upstreams"), so a client can reach many servers through one. The local tools
(doc 03) and remote tools live side by side.

## The registry

Upstreams are configured by name → `{url, token}` (a bearer token is optional).
Each operation opens a short-lived FastMCP `Client` — no persistent pooling,
since federation is expected to be low-volume next to local calls.

```python
class UpstreamRegistry:
    def __init__(self, upstreams=None, *, timeout=30.0, allow_runtime=True):
        self._servers = {name: dict(spec) for name, spec in (upstreams or {}).items()}
        ...

    def _client(self, spec) -> Client:
        target = spec.get("target") or spec.get("url")   # target: in-memory FastMCP (tests)
        auth = BearerAuth(spec["token"]) if (spec.get("token") and BearerAuth) else None
        return Client(target, auth=auth, timeout=self.timeout)
```

> **Testability:** a spec may carry a `target` that is a live `FastMCP` object
> instead of a `url`. `fastmcp.Client` connects to it in-memory, so the whole
> feature is tested with zero ports/network (see `tests/test_plugins_upstreams.py`).

## Listing and calling

Remote tool errors are pulled **in-band** (`raise_on_error=False`) so a failing
remote tool looks the same as a failing local one (`is_error: true`), while a
*connection* failure raises `UpstreamError` → HTTP `502`.

```python
async def call_tool(self, name, tool, arguments):
    spec = self._servers.get(name)
    if spec is None:
        raise KeyError(name)                              # → 404
    try:
        async with self._client(spec) as c:
            res = await c.call_tool(tool, arguments or {}, raise_on_error=False)
    except Exception as exc:
        raise UpstreamError(f"could not call {tool!r} on upstream {name!r}: {exc}") from exc
    return {
        "upstream": name, "tool": tool,
        "is_error": bool(getattr(res, "is_error", False)),
        "structured_content": getattr(res, "structured_content", None),
        "content": [{"type": c_.type, "text": getattr(c_, "text", None)} for c_ in (res.content or [])],
    }
```

The response envelope matches the local `/tools/{name}/call` shape plus an
`upstream` field, so a client handles local and remote results identically.

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/mcp/upstreams` | `MCP_UPSTREAM_AUTH` | list configured upstreams |
| GET | `/mcp/upstreams/{server}/tools` | `MCP_UPSTREAM_AUTH` | list a remote server's tools |
| POST | `/mcp/upstreams/{server}/tools/{name}/call` | `MCP_UPSTREAM_AUTH` | execute a remote tool |
| POST | `/admin/mcp/upstreams` | admin | add an upstream at runtime `{name, url, token?}` |
| POST | `/admin/mcp/upstreams/{server}/remove` | admin | remove an upstream |

Runtime add/remove is disabled when `MCP_UPSTREAM_ALLOW_RUNTIME=false` (`403`).

## Configuration

```bash
# inline JSON (a bare string value is shorthand for {"url": ...})
MCP_UPSTREAMS='{"billing": {"url": "http://billing:8000/sse", "token": "..."},
                "search":  "http://search:8000/sse"}'
# or a file
MCP_UPSTREAMS_FILE=config/upstreams.json
MCP_UPSTREAM_TIMEOUT_SEC=30
MCP_UPSTREAM_ALLOW_RUNTIME=true
```

```console
$ curl localhost:8000/mcp/upstreams/billing/tools
{"upstream":"billing","tools":[{"name":"invoice_lookup","description":"..."}]}

$ curl -X POST localhost:8000/mcp/upstreams/billing/tools/invoice_lookup/call \
       -d '{"arguments": {"id": "INV-42"}}'
{"upstream":"billing","tool":"invoice_lookup","is_error":false,"structured_content":{...},"content":[...]}
```

## Design notes & trade-offs

- **Trust is transitive:** calling an upstream runs code on *their* server with
  whatever token you configured. Only federate to servers you trust.
- **No auto-merge into the local catalog:** remote tools are reached via the
  `/mcp/upstreams/...` namespace, not registered as local tools. This keeps
  name collisions, disable/enable, and risk-gating strictly about *local*
  tools, and makes "where did this tool run?" unambiguous. (Merging upstream
  tools into the local catalog/`/sse` would be a natural future extension via
  FastMCP's proxy/mount, at the cost of that clarity.)
- **Per-call connections** keep the code simple and stateless; if federation
  becomes hot, add a connection cache keyed by upstream name.
