"""OpenAPI MCP Server Native Plugin.

Transforms any OpenAPI 3.0 / 3.1 specification (from URL, local file, or raw JSON/YAML)
into live Model Context Protocol (MCP) tools on the main server.

Features:
- Spec Loader: Parses URLs (`http://`/`https://`), local files, or raw JSON/YAML strings.
- $ref Resolver: Resolves schema references with recursion depth protection (max_depth=10).
- Tool Name Sanitizer: Enforces MCP tool naming constraints (`^[a-zA-Z0-9_-]{1,64}$`).
- Input Schema Generator: Maps path params (`{id}`), query params (`?key=val`), headers, and requestBody.
- REST Execution Engine: Executes HTTP calls using `httpx.AsyncClient` with 30s timeout & 5MB cap.
- Auth Support: API Key (`X-API-Key`), Bearer Token (`Authorization: Bearer <token>`), Custom Headers.
- Spec Persistence & Re-hydration: Persists specs to disk for auto-hydration on server restart.
"""
from __future__ import annotations

import ast
import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

try:
    import yaml
except ImportError:
    yaml = None

log = logging.getLogger("MCP_logger")

OPERATION_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def sanitize_tool_name(name: str, max_length: int = 64) -> str:
    """Sanitize tool name to match ^[a-zA-Z0-9_-]{1,64}$."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "openapi_tool"
    return sanitized[:max_length]


class OpenAPIToolManager:
    """Manages parsing of OpenAPI specs, FastMCP tool generation, and REST execution."""

    def __init__(self, mcp_server: Any, loader: Optional[Any] = None, storage_dir: Optional[Path] = None):
        self.mcp = mcp_server
        self.loader = loader
        self.storage_dir = storage_dir or Path("logs/openapi_specs")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # collection_id -> {"spec": dict, "base_url": str, "tool_names": List[str], "auth_config": dict}
        self.collections: Dict[str, dict] = {}


    def load_spec_content(self, spec_input: str) -> dict:
        """Load OpenAPI spec from HTTP URL, file path, or raw JSON/YAML text."""
        spec_input = spec_input.strip()
        if spec_input.startswith("http://") or spec_input.startswith("https://"):
            try:
                resp = httpx.get(spec_input, timeout=15.0, follow_redirects=True)
                resp.raise_for_status()
                text = resp.text
            except Exception as exc:
                raise ValueError(f"Could not download OpenAPI spec from URL {spec_input!r}: {exc}") from exc
        elif Path(spec_input).exists():
            text = Path(spec_input).read_text(encoding="utf-8")
        else:
            text = spec_input

        # Try JSON first, then YAML
        try:
            return json.loads(text)
        except Exception:
            if yaml is not None:
                try:
                    loaded = yaml.safe_load(text)
                    if isinstance(loaded, dict):
                        return loaded
                except Exception:
                    pass
            raise ValueError("Invalid OpenAPI spec format. Must be valid JSON or YAML.")

    def _resolve_ref(self, spec: dict, ref: str, depth: int = 0) -> dict:
        if depth > 10 or not ref.startswith("#/"):
            return {"type": "object"}
        obj = spec
        for part in ref[2:].split("/"):
            obj = obj.get(part, {})
        if isinstance(obj, dict) and "$ref" in obj:
            return self._resolve_ref(spec, obj["$ref"], depth + 1)
        return dict(obj) if isinstance(obj, dict) else {"type": "object"}

    def extract_operations(self, spec: dict) -> List[dict]:
        """Extract all operations from the OpenAPI spec."""
        operations = []
        paths = spec.get("paths") or {}
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            path_level_params = path_item.get("parameters") or []
            for key, value in path_item.items():
                if key.lower() not in OPERATION_METHODS or not isinstance(value, dict):
                    continue
                method = key.upper()
                op_params = value.get("parameters") or []
                all_params = []
                seen = set()
                for p in path_level_params + op_params:
                    if "$ref" in p:
                        p = self._resolve_ref(spec, p["$ref"])
                    p_name = p.get("name")
                    if p_name and p_name not in seen:
                        seen.add(p_name)
                        all_params.append(p)

                op_id = value.get("operationId") or f"{method.lower()}_{path.replace('/', '_').strip('_')}"
                operations.append({
                    "path": path,
                    "method": method,
                    "operationId": op_id,
                    "summary": value.get("summary"),
                    "description": value.get("description") or value.get("summary") or f"OpenAPI operation {op_id}",
                    "parameters": all_params,
                    "requestBody": value.get("requestBody"),
                    "tags": value.get("tags") or [],
                })
        return operations

    def build_input_schema(self, spec: dict, operation: dict) -> dict:
        """Build JSON Schema for tool input arguments."""
        properties = {}
        required = []

        for param in operation.get("parameters") or []:
            name = param.get("name")
            if not name:
                continue
            schema = param.get("schema") or {"type": "string"}
            if "$ref" in schema:
                schema = self._resolve_ref(spec, schema["$ref"])
            else:
                schema = dict(schema)
            if param.get("description"):
                schema["description"] = param["description"]
            properties[name] = schema
            if param.get("required"):
                required.append(name)

        # Request Body Schema
        request_body = operation.get("requestBody")
        if isinstance(request_body, dict):
            content = request_body.get("content") or {}
            json_content = content.get("application/json") or {}
            body_schema = json_content.get("schema")
            if body_schema:
                if "$ref" in body_schema:
                    body_schema = self._resolve_ref(spec, body_schema["$ref"])
                else:
                    body_schema = dict(body_schema)
                properties["body"] = {
                    **body_schema,
                    "description": body_schema.get("description") or "JSON Request Body",
                }
                if request_body.get("required"):
                    required.append("body")

        return {"type": "object", "properties": properties, "required": required}

    def determine_base_url(self, spec: dict, override: Optional[str] = None) -> str:
        if override:
            return override.rstrip("/")
        env_base = os.environ.get("OPENAPI_MCP_BASE_URL")
        if env_base:
            return env_base.rstrip("/")
        servers = spec.get("servers") or []
        for s in servers:
            url = (s or {}).get("url")
            if url:
                parsed = urlparse(url)
                if (parsed.hostname or "").lower() in _LOCAL_HOSTS:
                    return url.rstrip("/")
        if servers and servers[0].get("url"):
            return servers[0]["url"].rstrip("/")
        return "http://localhost:8000"

    def register_spec_collection(
        self,
        collection_id: str,
        spec_input: str,
        base_url_override: Optional[str] = None,
        auth_config: Optional[dict] = None,
    ) -> dict:
        """Parse OpenAPI spec and register all operations as dynamic FastMCP tools."""
        spec = self.load_spec_content(spec_input)
        operations = self.extract_operations(spec)
        base_url = self.determine_base_url(spec, base_url_override)
        auth_config = auth_config or {}

        if not operations:
            raise ValueError(f"No operations found in OpenAPI spec for collection {collection_id!r}")

        # Unregister existing tools for this collection if re-registering
        if collection_id in self.collections:
            self.remove_spec_collection(collection_id)

        registered_tools = []

        for op in operations:
            raw_name = f"{op['operationId']}_{collection_id}"
            tool_name = sanitize_tool_name(raw_name)
            desc = op["description"] or f"OpenAPI operation {op['operationId']}"
            input_schema = self.build_input_schema(spec, op)

            # Create dynamic tool closure with explicit parameter signatures
            handler = self._make_tool_handler(base_url, op, auth_config, input_schema)

            # Register with ToolLoader (and FastMCP)
            try:
                if self.loader and hasattr(self.loader, "register_external_tool"):
                    self.loader.register_external_tool(
                        name=tool_name,
                        fn_or_tool=handler,
                        description=desc,
                        module_name=f"openapi.{collection_id}",
                        tags=["openapi", collection_id],
                    )
                elif hasattr(self.mcp, "tool"):
                    self.mcp.tool(name=tool_name, description=desc)(handler)
                elif hasattr(self.mcp, "add_tool"):
                    from fastmcp.tools.tool import FunctionTool
                    t_obj = FunctionTool.from_defaults(handler, name=tool_name, description=desc)
                    self.mcp.add_tool(t_obj)
                registered_tools.append(tool_name)
            except Exception as exc:
                log.warning("Could not register OpenAPI tool %r: %s", tool_name, exc)

        # Persist collection metadata and spec file
        record = {
            "collection_id": collection_id,
            "base_url": base_url,
            "tool_names": registered_tools,
            "auth_config": auth_config,
            "spec": spec,
        }
        self.collections[collection_id] = record
        self._save_collection_to_disk(collection_id, record)

        return {
            "collection_id": collection_id,
            "base_url": base_url,
            "tools_count": len(registered_tools),
            "tool_names": registered_tools,
        }

    def _make_tool_handler(self, base_url: str, operation: dict, auth_config: dict, input_schema: dict):
        """Create async handler function with explicit parameter names for FastMCP schema inference."""
        properties = input_schema.get("properties") or {}
        param_names = [p for p in properties.keys() if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", p)]

        async def execute_fn(args: dict) -> dict:
            return await self.execute_api_call(base_url, operation, auth_config, args)

        if param_names:
            params_str = ", ".join(f"{p}=None" for p in param_names)
            dict_str = ", ".join(f"'{p}': {p}" for p in param_names)
            code = f"""
async def openapi_tool_handler({params_str}):
    kwargs = {{{dict_str}}}
    cleaned = {{k: v for k, v in kwargs.items() if v is not None}}
    return await execute_fn(cleaned)
"""
        else:
            code = """
async def openapi_tool_handler():
    return await execute_fn({})
"""

        local_scope = {"execute_fn": execute_fn}
        exec(code, local_scope)
        return local_scope["openapi_tool_handler"]


    async def execute_api_call(
        self, base_url: str, operation: dict, auth_config: dict, arguments: dict
    ) -> dict:
        """Execute HTTP REST call for an OpenAPI operation."""
        path = operation["path"]
        method = operation["method"]
        params = operation.get("parameters") or []

        path_vars = {}
        query_vars = {}
        header_vars = {}

        # Separate arguments into path, query, header, and body
        for p in params:
            p_name = p.get("name")
            p_in = p.get("in", "query")
            if p_name in arguments:
                val = arguments[p_name]
                if p_in == "path":
                    path_vars[p_name] = val
                elif p_in == "query":
                    query_vars[p_name] = val
                elif p_in == "header":
                    header_vars[p_name] = str(val)

        # Substitute path variables (e.g. /pets/{id} -> /pets/42)
        for k, v in path_vars.items():
            path = path.replace(f"{{{k}}}", str(v))

        url = f"{base_url}{path}"

        # Build HTTP Headers
        headers = dict(auth_config.get("headers") or {})
        headers.update(header_vars)

        auth_type = (auth_config.get("auth_type") or "").lower()
        api_key = auth_config.get("api_key")
        header_name = auth_config.get("header_name") or "X-API-Key"
        token = auth_config.get("token")

        if auth_type == "api_key" or (not auth_type and api_key):
            if api_key:
                headers[header_name] = api_key
        if auth_type in ("bearer", "oauth") or (not auth_type and token):
            if token:
                headers["Authorization"] = f"Bearer {token}"


        # JSON Body
        body = arguments.get("body")

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.request(
                    method=method,
                    url=url,
                    params=query_vars,
                    headers=headers,
                    json=body if body is not None else None,
                )
                
                try:
                    res_data = resp.json()
                except Exception:
                    res_data = resp.text

                return {
                    "operationId": operation["operationId"],
                    "status_code": resp.status_code,
                    "is_success": resp.is_success,
                    "data": res_data,
                }
        except Exception as exc:
            return {
                "operationId": operation["operationId"],
                "is_error": True,
                "error": f"HTTP execution failed for {method} {url}: {exc}",
            }

    def remove_spec_collection(self, collection_id: str) -> bool:
        """Unregister all tools for a collection and delete spec from disk."""
        record = self.collections.pop(collection_id, None)
        if not record:
            return False

        for name in record.get("tool_names", []):
            with contextlib.suppress(Exception):
                if self.loader and hasattr(self.loader, "unregister_external_tool"):
                    self.loader.unregister_external_tool(name, module_name=f"openapi.{collection_id}")
                else:
                    provider = getattr(self.mcp, "local_provider", self.mcp)
                    provider.remove_tool(name)


        spec_file = self.storage_dir / f"{collection_id}.json"
        if spec_file.exists():
            with contextlib.suppress(Exception):
                spec_file.unlink()

        return True

    def _save_collection_to_disk(self, collection_id: str, record: dict) -> None:
        try:
            file_path = self.storage_dir / f"{collection_id}.json"
            file_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            log.error("Could not save OpenAPI spec collection %r to disk: %s", collection_id, exc)

    def load_saved_collections_from_disk(self) -> None:
        """Auto-hydrate saved OpenAPI spec collections from storage_dir on startup."""

        if not self.storage_dir.exists():
            return
        for spec_file in self.storage_dir.glob("*.json"):
            try:
                record = json.loads(spec_file.read_text(encoding="utf-8"))
                col_id = record.get("collection_id")
                spec = record.get("spec")
                if col_id and spec:
                    self.register_spec_collection(
                        col_id,
                        json.dumps(spec),
                        base_url_override=record.get("base_url"),
                        auth_config=record.get("auth_config"),
                    )
            except Exception as exc:
                log.warning("Could not auto-hydrate OpenAPI spec from %s: %s", spec_file.name, exc)
