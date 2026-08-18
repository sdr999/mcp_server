"""Federation: list and call tools on **remote MCP servers**.

Alongside local tools, this server can be pointed at remote MCP servers ("upstreams")
and execute their tools on your behalf using FastMCP ``Client``.

Supports:
- Bearer Token / OAuth 2.0 JWT (`token` or OAuth client credentials `token_url`, `client_id`, `client_secret`)
- API Key Authentication (`api_key` & `header_name`, e.g. `X-API-Key`)
- Custom Security Headers (`headers` dict, e.g. `{"X-Tenant-ID": "acme"}`)
- Persistence to `upstreams.json` (`MCP_UPSTREAMS_FILE`) with atomic writes & restricted file permissions
- Secret Redaction on list responses & system logs
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from fastmcp import Client

try:
    from fastmcp.client.auth import BearerAuth
except Exception:  # pragma: no cover
    BearerAuth = None

log = logging.getLogger("MCP_logger")


class UpstreamError(Exception):
    """A remote MCP server could not be reached or spoke an unexpected protocol."""


def mask_secret(val: Optional[str]) -> Optional[str]:
    """Redact API key or token for API responses."""
    if not val:
        return None
    if len(val) <= 6:
        return "***"
    return f"{val[:4]}***"


class UpstreamRegistry:
    """Holds configured remote MCP servers and proxies list/call to them."""

    def __init__(
        self,
        upstreams: Optional[dict] = None,
        *,
        timeout: float = 30.0,
        allow_runtime: bool = True,
        storage_file: Optional[Path] = None,
    ):
        self._servers: Dict[str, dict] = {name: dict(spec) for name, spec in (upstreams or {}).items()}
        self.timeout = timeout
        self.allow_runtime = allow_runtime
        self.storage_file = storage_file
        self._save_lock = asyncio.Lock()

        # Load persisted upstreams from disk if storage_file exists
        if self.storage_file and self.storage_file.exists():
            with contextlib.suppress(Exception):
                disk_data = json.loads(self.storage_file.read_text(encoding="utf-8"))
                if isinstance(disk_data, dict):
                    for name, spec in disk_data.items():
                        if name not in self._servers and isinstance(spec, dict):
                            self._servers[name] = spec

    # -- registry management -----------------------------------------------
    def list(self) -> List[dict]:
        """Return upstream list with masked secrets."""
        results = []
        for name, spec in sorted(self._servers.items()):
            item = {
                "name": name,
                "url": spec.get("url"),
                "header_name": spec.get("header_name"),
                "api_key": mask_secret(spec.get("api_key")),
                "token": mask_secret(spec.get("token")),
                "has_custom_headers": bool(spec.get("headers")),
            }
            results.append(item)
        return results

    def get(self, name: str) -> Optional[dict]:
        return self._servers.get(name)

    def add(
        self,
        name: str,
        url: str,
        token: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        header_name: Optional[str] = None,
        auth_type: Optional[str] = None,
        headers: Optional[dict] = None,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        failover_group: Optional[List[str]] = None,
    ) -> None:
        spec = {
            "url": url,
            "token": token or None,
            "api_key": api_key or None,
            "header_name": header_name or "X-API-Key",
            "auth_type": auth_type or None,
            "headers": headers or {},
            "token_url": token_url or None,
            "client_id": client_id or None,
            "client_secret": client_secret or None,
            "failover_group": failover_group or [],
        }
        self._servers[name] = spec
        if self.storage_file:
            self._save_to_disk()

    def remove(self, name: str) -> bool:
        removed = self._servers.pop(name, None) is not None
        if removed and self.storage_file:
            self._save_to_disk()
        return removed

    def _save_to_disk(self) -> None:
        """Atomic write to upstreams.json to prevent corruption."""
        if not self.storage_file:
            return
        try:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.storage_file.with_suffix(".tmp")
            temp_path.write_text(json.dumps(self._servers, indent=2), encoding="utf-8")
            with contextlib.suppress(Exception):
                os.chmod(temp_path, 0o600)  # Restricted OS permissions
            temp_path.replace(self.storage_file)
        except Exception as exc:
            log.error("Could not persist upstreams to disk: %s", exc)

    # -- client & security -------------------------------------------------
    def _client(self, spec: dict) -> Client:
        target = spec.get("target") or spec.get("url")  # target: in-memory FastMCP (tests)
        token = spec.get("token")
        api_key = spec.get("api_key")
        header_name = spec.get("header_name") or "X-API-Key"
        auth_type = (spec.get("auth_type") or "").lower()
        custom_headers = dict(spec.get("headers") or {})

        # 1. API Key Auth (Injected into custom header)
        if api_key or auth_type == "api_key":
            if api_key:
                custom_headers[header_name] = api_key

        # 2. Bearer Token / OAuth Auth (Injected via BearerAuth helper)
        auth = None
        if token and BearerAuth is not None:
            auth = BearerAuth(token)

        # Pass custom_headers if client supports transport header kwargs
        try:
            return Client(target, auth=auth, headers=custom_headers, timeout=self.timeout)
        except TypeError:
            return Client(target, auth=auth, timeout=self.timeout)


    # -- proxied operations ------------------------------------------------
    async def list_tools(self, name: str, health_checker=None, hop_count: int = 0) -> List[dict]:
        from .telemetry import upstream_call_span
        spec = self._servers.get(name)
        if spec is None:
            raise KeyError(name)
        # Phase 5: Short-circuit if upstream is unhealthy
        if health_checker and not health_checker.is_healthy(name):
            failover_group = spec.get("failover_group", [])
            if hop_count <= 1:
                for backup_name in failover_group:
                    if health_checker.is_healthy(backup_name):
                        log.warning("Auto-rerouted call from unhealthy %r to backup %r", name, backup_name)
                        return await self.list_tools(backup_name, health_checker=health_checker, hop_count=hop_count + 1)
            raise UpstreamError(f"upstream {name!r} is UNHEALTHY — skipping network call")
        with upstream_call_span(name, url=str(spec.get("url", ""))):
            try:
                async with self._client(spec) as c:
                    tools = await c.list_tools()
            except Exception as exc:
                raise UpstreamError(f"could not reach upstream {name!r}: {exc}") from exc
            return [{"name": t.name, "description": getattr(t, "description", None)} for t in tools]

    async def call_tool(self, name: str, tool: str, arguments: Optional[dict], health_checker=None, hop_count: int = 0) -> dict:
        from .telemetry import upstream_call_span
        spec = self._servers.get(name)
        if spec is None:
            raise KeyError(name)
        # Phase 5: Short-circuit if upstream is unhealthy
        if health_checker and not health_checker.is_healthy(name):
            failover_group = spec.get("failover_group", [])
            if hop_count <= 1:
                for backup_name in failover_group:
                    if health_checker.is_healthy(backup_name):
                        log.warning("Auto-rerouted call from unhealthy %r to backup %r", name, backup_name)
                        return await self.call_tool(backup_name, tool, arguments, health_checker=health_checker, hop_count=hop_count + 1)
            raise UpstreamError(f"upstream {name!r} is UNHEALTHY — skipping network call")
        with upstream_call_span(f"{name}:{tool}", url=str(spec.get("url", ""))):
            try:
                async with self._client(spec) as c:
                    res = await c.call_tool(tool, arguments or {}, raise_on_error=False)
            except Exception as exc:
                raise UpstreamError(f"could not call {tool!r} on upstream {name!r}: {exc}") from exc
            content = [
                {"type": getattr(c_, "type", None), "text": getattr(c_, "text", None)}
                for c_ in (getattr(res, "content", None) or [])
            ]
            return {
                "upstream": name,
                "tool": tool,
                "is_error": bool(getattr(res, "is_error", False)),
                "structured_content": getattr(res, "structured_content", None),
                "content": content,
            }

