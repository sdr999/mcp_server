"""Federation: list and call tools on **remote MCP servers**.

Alongside the local tools this server registers, it can be pointed at other MCP
servers ("upstreams") and execute their tools on your behalf, using a FastMCP
``Client``. Upstreams are configured via ``MCP_UPSTREAMS`` / ``MCP_UPSTREAMS_FILE``
and (optionally) added/removed at runtime through the admin API.

No hard dependency beyond FastMCP (already required). Each call opens a
short-lived client connection; there is no persistent pooling — federation is
expected to be low-volume relative to local tool calls.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastmcp import Client

try:  # optional bearer auth helper
    from fastmcp.client.auth import BearerAuth
except Exception:  # pragma: no cover
    BearerAuth = None

log = logging.getLogger("MCP_logger")


class UpstreamError(Exception):
    """A remote MCP server could not be reached or spoke an unexpected protocol."""


class UpstreamRegistry:
    """Holds configured remote MCP servers and proxies list/call to them."""

    def __init__(self, upstreams: Optional[dict] = None, *, timeout: float = 30.0,
                 allow_runtime: bool = True):
        # name -> {"url": str, "token": str|None} OR {"target": <FastMCP>} (tests use
        # an in-memory FastMCP instance so no network/ports are involved).
        self._servers = {name: dict(spec) for name, spec in (upstreams or {}).items()}
        self.timeout = timeout
        self.allow_runtime = allow_runtime

    # -- registry management -----------------------------------------------
    def list(self) -> List[dict]:
        return [{"name": n, "url": s.get("url")} for n, s in sorted(self._servers.items())]

    def get(self, name: str) -> Optional[dict]:
        return self._servers.get(name)

    def add(self, name: str, url: str, token: Optional[str] = None) -> None:
        self._servers[name] = {"url": url, "token": token or None}

    def remove(self, name: str) -> bool:
        return self._servers.pop(name, None) is not None

    # -- client ------------------------------------------------------------
    def _client(self, spec: dict) -> Client:
        target = spec.get("target") or spec.get("url")     # target: in-memory FastMCP (tests)
        auth = None
        if spec.get("token") and BearerAuth is not None:
            auth = BearerAuth(spec["token"])
        return Client(target, auth=auth, timeout=self.timeout)

    # -- proxied operations ------------------------------------------------
    async def list_tools(self, name: str) -> List[dict]:
        spec = self._servers.get(name)
        if spec is None:
            raise KeyError(name)
        try:
            async with self._client(spec) as c:
                tools = await c.list_tools()
        except Exception as exc:
            raise UpstreamError(f"could not reach upstream {name!r}: {exc}") from exc
        return [{"name": t.name, "description": getattr(t, "description", None)} for t in tools]

    async def call_tool(self, name: str, tool: str, arguments: Optional[dict]) -> dict:
        spec = self._servers.get(name)
        if spec is None:
            raise KeyError(name)
        try:
            async with self._client(spec) as c:
                # raise_on_error=False → remote tool errors come back in-band,
                # matching the local /tools/{name}/call contract.
                res = await c.call_tool(tool, arguments or {}, raise_on_error=False)
        except Exception as exc:
            raise UpstreamError(f"could not call {tool!r} on upstream {name!r}: {exc}") from exc
        content = [{"type": getattr(c_, "type", None), "text": getattr(c_, "text", None)}
                   for c_ in (getattr(res, "content", None) or [])]
        return {
            "upstream": name,
            "tool": tool,
            "is_error": bool(getattr(res, "is_error", False)),
            "structured_content": getattr(res, "structured_content", None),
            "content": content,
        }
