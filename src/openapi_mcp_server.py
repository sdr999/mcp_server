
"""
MCP server that watches an Azure File Share folder for OpenAPI config files,
syncs them locally, and dynamically adds OpenAPI-derived tools to the running server.

Each config file in Azure is a JSON with:
  - "openapi_collection_id": unique id for this collection (suffixed to each tool name for uniqueness)
  - "spec_file": path/filename of the OpenAPI spec in Azure (e.g. "openapi.yaml")
  - "operations": list of operationIds to expose (e.g. ["listTasks", "getTask"])

Tool names are {operationId}_{openapi_collection_id} so they stay unique across collections.

When adding tools we read the spec from Azure, create a local copy under
openapi_tools/azure_openapi_specs/, then use that local path. Configs are synced
to openapi_tools/azure_openapi_configs/.

Azure config files have unique names. We track which config files we have already processed
and which tool names we added from each file, so we never create duplicate tools
from the same file. On config update we remove that file's tools and re-add from
the new content.

Requires: fastmcp, httpx, watchdog, azure-storage-file-share, PyYAML.
Optional: agentic_framework (for Bearer auth) — see comments below.
"""

import argparse
import base64
import json
import logging
import mimetypes
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.fileshare import ShareDirectoryClient, ShareServiceClient
from fastmcp import FastMCP
from fastmcp.tools.tool import Tool, ToolResult
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

try:
    import yaml
except ImportError:
    yaml = None
# import agentic_framework.utils as global_variables
# global_variables.env=env
from agentic_framework.utils import global_variables
from dotenv import dotenv_values
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', '.env')
env = dotenv_values(dotenv_path=env_path)
global_variables.env=env
# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("MCP_OpenAPI_Azure")

# ---------------------------------------------------------------------------
# Paths & environment (edit these or use env / --config)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# Azure connection: set in env or .env
# AZURE_FILESTORE_CONNECTION_URL (or AZURE_STORAGE_CONNECTION_STRING)
# AZURE_FILESTORE_NAME (or AZURE_FILE_SHARE_NAME)
# env = dict(os.environ)
AZURE_CONN_STR = env.get("AZURE_FILESTORE_CONNECTION_URL") or env.get("AZURE_STORAGE_CONNECTION_STRING", "")
FILE_SHARE_NAME = env.get("AZURE_FILESTORE_NAME") or env.get("AZURE_FILE_SHARE_NAME", "")

# Optional: Bearer auth (uncomment and set MCP_AUTHENTICATION_FLAG, JWKS_URL if you use agentic_framework)
# try:
#     from agentic_framework.utils import global_variables
#     from fastmcp.server.auth.providers.bearer import BearerAuthProvider
#     global_variables.env = env
#     if env.get("MCP_AUTHENTICATION_FLAG", "").lower() == "true":
#         auth = BearerAuthProvider(jwks_uri=env["JWKS_URL"])
#     else:
#         auth = None
# except ImportError:
#     auth = None

# ---------------------------------------------------------------------------
# CLI: --config base64(remote_path) — Azure path to the *config* folder.
# Azure structure expected:
#   openapi_specs/                    <- specs folder (all .yaml/.json spec files here)
#     openapi_add_tools/              <- config folder (all .json configs here)
#     openapi.yaml, other_spec.yaml  ...
# So you pass config path: openapi_specs/openapi_add_tools
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="MCP server that adds OpenAPI tools from Azure File Share configs.")
parser.add_argument("--config", type=str, required=True, help="Base64-encoded path to config folder (e.g. openapi_specs/openapi_add_tools)")
args = parser.parse_args()

file_data = args.config
if file_data.startswith("data:"):
    header, base64_data = file_data.split(",", 1)
    _mime = header.split(";")[0].split(":")[-1]
else:
    base64_data = file_data

decoded_path = base64.b64decode(base64_data).decode("utf-8").strip()
# Config folder in Azure (where .json configs live)
REMOTE_CONFIG_PREFIX = decoded_path
# Specs folder in Azure = parent of config folder (where .yaml/.json spec files live)
REMOTE_SPEC_PREFIX = "/".join(decoded_path.rstrip("/").split("/")[:-1]) if "/" in decoded_path else ""
if not REMOTE_SPEC_PREFIX:
    # Config path was a single segment (e.g. "openapi_add_tools"); specs at share root
    REMOTE_SPEC_PREFIX = ""

# Local layout: openapi_tools/
#   azure_openapi_configs/  - synced config JSONs from Azure
#   azure_openapi_specs/    - spec files downloaded from Azure when adding tools
OPENAPI_TOOLS_DIR = BASE_DIR / "openapi_tools"
LOCAL_OPENAPI_CONFIG_DIR = OPENAPI_TOOLS_DIR / "azure_openapi_configs"
LOCAL_OPENAPI_SPEC_DIR = OPENAPI_TOOLS_DIR / "azure_openapi_specs"
OPENAPI_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_OPENAPI_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_OPENAPI_SPEC_DIR.mkdir(parents=True, exist_ok=True)

if not AZURE_CONN_STR or not FILE_SHARE_NAME:
    log.warning("Missing AZURE_FILESTORE_CONNECTION_URL and/or AZURE_FILESTORE_NAME; sync will fail.")

# ---------------------------------------------------------------------------
# Azure clients
# ---------------------------------------------------------------------------
service_client = ShareServiceClient.from_connection_string(AZURE_CONN_STR)
share_client = service_client.get_share_client(FILE_SHARE_NAME)


def ensure_remote_directory_hierarchy(path: str) -> ShareDirectoryClient:
    """Ensure the remote path exists on the Azure File Share; return directory client for that path."""
    segments = [s for s in path.split("/") if s]
    try:
        share_client.get_share_properties()
    except ResourceNotFoundError:
        raise RuntimeError(f"Azure File Share '{FILE_SHARE_NAME}' does not exist. Create it first.")
    current_path = ""
    for seg in segments:
        current_path = f"{current_path}/{seg}" if current_path else seg
        dir_client = share_client.get_directory_client(current_path)
        try:
            dir_client.get_directory_properties()
        except ResourceNotFoundError:
            share_client.create_directory(current_path)
    return share_client.get_directory_client(path if path else "")


# Azure directory client for *config* folder (openapi_specs/openapi_add_tools) — sync .json from here
REMOTE_CONFIG_DIR_CLIENT = ensure_remote_directory_hierarchy(REMOTE_CONFIG_PREFIX)
# Azure directory client for *specs* folder (openapi_specs) — fetch spec files from here when adding tools
REMOTE_SPEC_DIR_CLIENT = ensure_remote_directory_hierarchy(REMOTE_SPEC_PREFIX) if REMOTE_SPEC_PREFIX else share_client.get_directory_client("")


def download_spec_from_azure(spec_file: str) -> Path:
    """
    Download the OpenAPI spec file from the Azure *specs* folder (openapi_specs/)
    to openapi_tools/azure_openapi_specs/ and return the local path.
    spec_file is the filename in that folder (e.g. 'openapi.yaml'). We store by
    basename so the local path is LOCAL_OPENAPI_SPEC_DIR / basename(spec_file).
    """
    spec_file = spec_file.strip()
    if not spec_file:
        raise ValueError("spec_file is empty")
    # Use basename so we have a flat local spec dir; same filename = same spec.
    filename = Path(spec_file).name
    local_path = LOCAL_OPENAPI_SPEC_DIR / filename
    file_client = REMOTE_SPEC_DIR_CLIENT.get_file_client(spec_file)
    try:
        with open(local_path, "wb") as f:
            f.write(file_client.download_file().readall())
    except ResourceNotFoundError:
        raise FileNotFoundError(f"Spec file not found in Azure: {spec_file}")
    return local_path


# ---------------------------------------------------------------------------
# OpenAPI spec loading and operation extraction (same logic as run_mcp_with_endpoints)
# ---------------------------------------------------------------------------
OPERATION_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def load_spec(path: Path) -> dict[str, Any]:
    """Load OpenAPI spec from .json or .yaml/.yml file."""
    if not path.exists():
        raise FileNotFoundError(f"OpenAPI spec not found: {path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise ImportError("PyYAML required for YAML specs. pip install pyyaml")
        return yaml.safe_load(text)
    raise ValueError(f"Unsupported format: {suffix}. Use .json, .yaml, or .yml.")


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    obj = spec
    for part in ref[2:].split("/"):
        obj = obj.get(part, {})
    return obj if isinstance(obj, dict) else {}


def _resolve_parameter(spec: dict[str, Any], param: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in param:
        resolved = _resolve_ref(spec, param["$ref"])
        return {**resolved, **{k: v for k, v in param.items() if k != "$ref"}}
    return dict(param)


def _merge_parameters(
    spec: dict[str, Any],
    path_params: list[dict[str, Any]],
    op_params: Optional[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for p in (path_params or []) + (op_params or []):
        resolved = _resolve_parameter(spec, p)
        name = resolved.get("name")
        if name and name not in seen:
            seen.add(name)
            out.append(resolved)
    return out


def extract_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all operations from the OpenAPI spec (path, method, parameters, requestBody, etc.)."""
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
            op_params = value.get("parameters")
            parameters = _merge_parameters(spec, path_level_params, op_params)
            op_id = value.get("operationId") or f"{method}_{path.replace('/', '_').strip('_')}"
            operations.append({
                "path": path,
                "method": method,
                "operationId": op_id,
                "summary": value.get("summary"),
                "description": value.get("description") or value.get("summary") or "",
                "parameters": parameters,
                "requestBody": value.get("requestBody"),
                "tags": value.get("tags") or [],
            })
    return operations


def _resolve_ref_schema(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {"type": "object"}
    obj = spec
    for part in ref[2:].split("/"):
        obj = obj.get(part, {})
    return dict(obj) if isinstance(obj, dict) else {"type": "object"}


def _get_request_body_schema(spec: dict[str, Any], request_body: Optional[dict]) -> Optional[dict[str, Any]]:
    if not request_body:
        return None
    content = request_body.get("content") or {}
    json_content = content.get("application/json")
    if not json_content:
        return None
    schema = json_content.get("schema")
    if not schema:
        return None
    if "$ref" in schema:
        return _resolve_ref_schema(spec, schema["$ref"])
    return dict(schema)


def build_input_schema(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Build JSON Schema for tool input from parameters and optional requestBody."""
    properties = {}
    required = []
    for param in operation.get("parameters") or []:
        name = param.get("name")
        if not name:
            continue
        schema = param.get("schema") or {"type": "string"}
        schema = dict(schema)
        if param.get("description"):
            schema["description"] = param["description"]
        properties[name] = schema
        if param.get("required"):
            required.append(name)
    body_schema = _get_request_body_schema(spec, operation.get("requestBody"))
    if body_schema is not None:
        properties["body"] = {
            **body_schema,
            "description": body_schema.get("description") or "Request body (JSON).",
        }
        if operation.get("requestBody", {}).get("required"):
            required.append("body")
    return {"type": "object", "properties": properties, "required": required}


def get_base_url(spec: dict[str, Any], override: Optional[str] = None) -> str:
    """Base URL from override, OPENAPI_MCP_BASE_URL, or spec servers (prefer localhost)."""
    if override:
        return override.rstrip("/")
    base = os.environ.get("OPENAPI_MCP_BASE_URL")
    if base:
        return base.rstrip("/")
    servers = spec.get("servers") or []
    if not servers:
        raise ValueError("No base URL. Set OPENAPI_MCP_BASE_URL or add 'servers' to the OpenAPI spec.")
    for s in servers:
        url = (s or {}).get("url")
        if not url:
            continue
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() in _LOCAL_HOSTS:
            return url.rstrip("/")
    return (servers[0].get("url") or "").rstrip("/")


# ---------------------------------------------------------------------------
# HTTP execution for OpenAPI tools
# ---------------------------------------------------------------------------
def _path_param_names(path: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", path))


def _substitute_path(path: str, path_params: dict[str, Any]) -> str:
    result = path
    for key, value in path_params.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


async def execute_api_call(
    base_url: str,
    operation: dict[str, Any],
    params: dict[str, Any],
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 30.0,
) -> Any:
    """Execute the HTTP request for the given operation; return JSON or text."""
    path = operation["path"]
    method = operation["method"]
    path_names = _path_param_names(path)
    params = dict(params)
    path_params = {k: params[k] for k in path_names if k in params}
    body = params.pop("body", None)
    query_params = {k: v for k, v in params.items() if v is not None}
    url = base_url.rstrip("/") + _substitute_path(path, path_params)
    request_headers = dict(headers or {})
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method == "GET":
            r = await client.get(url, params=query_params, headers=request_headers)
        elif method == "POST":
            r = await client.post(url, params=query_params, json=body, headers=request_headers)
        elif method == "PUT":
            r = await client.put(url, params=query_params, json=body, headers=request_headers)
        elif method == "PATCH":
            r = await client.patch(url, params=query_params, json=body, headers=request_headers)
        elif method == "DELETE":
            r = await client.delete(url, params=query_params, headers=request_headers)
        elif method == "HEAD":
            r = await client.head(url, params=query_params, headers=request_headers)
        else:
            r = await client.request(method, url, params=query_params, json=body, headers=request_headers)
        r.raise_for_status()
        if r.status_code == 204:
            return {"status": "success", "message": "No content"}
        if "application/json" in (r.headers.get("content-type") or "").lower():
            return r.json()
        return r.text


# ---------------------------------------------------------------------------
# OpenAPI MCP tool (one per operation; name can be prefixed for uniqueness)
# ---------------------------------------------------------------------------
class OpenAPITool(Tool):
    """Single OpenAPI operation exposed as an MCP tool."""

    def __init__(
        self,
        name: str,
        operation: dict[str, Any],
        input_schema: dict[str, Any],
        base_url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
    ):
        description = (
            operation.get("description")
            or operation.get("summary")
            or f"{operation['method']} {operation['path']}"
        )
        super().__init__(name=name, description=description, parameters=input_schema)
        self._operation = operation
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout = timeout

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = await execute_api_call(
                self._base_url,
                self._operation,
                arguments,
                headers=self._headers,
                timeout=self._timeout,
            )
        except Exception as e:
            return ToolResult(
                content=f"Error: {e!s}",
                structured_content={"error": str(e), "code": "EXECUTION_ERROR"},
            )
        if isinstance(result, dict):
            return ToolResult(structured_content=result)
        if isinstance(result, list):
            return ToolResult(structured_content={"result": result})
        return ToolResult(structured_content={"result": result})


# ---------------------------------------------------------------------------
# MCP server and OpenAPI config loader
# Tracks which config files have been processed and which tool names came from each,
# so we never create duplicate tools from the same file. On update we remove that
# file's tools and re-add from the new content.
# ---------------------------------------------------------------------------
# Create MCP server (no auth by default; uncomment auth block above if needed)
mcp = FastMCP(name="OpenAPI Tool Server")


class OpenAPIConfigServer:
    """
    Loads OpenAPI config files (JSON) from the local synced directory, builds tools
    from the referenced spec + operations, and registers them with the MCP server.
    Tracks processed files by unique config filename so we do not add duplicate tools
    from the same file.
    """

    # Extensions we consider as OpenAPI config files (must be JSON)
    CONFIG_EXTENSIONS = {".json"}

    def __init__(self, mcp_server: FastMCP, local_config_dir: Path):
        self.mcp = mcp_server
        self.local_dir = Path(local_config_dir)
        # Map: config filename (unique) -> set of MCP tool names we added from this file.
        # Used to remove tools when file is updated/deleted and to avoid duplicate registration.
        self._tools_by_config: dict[str, set[str]] = {}
        # Map: config filename -> last processed mtime (to skip unchanged files)
        self._last_mtime: dict[str, float] = {}
        # Optional auth header for API calls
        self._api_headers = {}
        token = os.environ.get("OPENAPI_MCP_TOKEN")
        if token:
            self._api_headers["Authorization"] = f"Bearer {token}"

    def _remove_tools_for_config(self, config_filename: str) -> None:
        """Unregister all tools that were added from this config file."""
        tool_names = self._tools_by_config.get(config_filename)
        if not tool_names:
            return
        for name in list(tool_names):
            if hasattr(self.mcp, "remove_tool"):
                try:
                    getattr(self.mcp, "remove_tool")(name)
                except Exception:
                    pass
        self._tools_by_config.pop(config_filename, None)
        self._last_mtime.pop(config_filename, None)

    def _load_single_config(self, config_path: Path) -> None:
        """
        Process one OpenAPI config file: read spec_file + operations, remove any
        previously added tools from this config file, then add new tools.
        Skips if not a .json file or if already processed with same mtime.
        """
        if config_path.suffix.lower() != ".json":
            return
        config_filename = config_path.name
        try:
            mtime = config_path.stat().st_mtime
        except FileNotFoundError:
            self._remove_tools_for_config(config_filename)
            return

        # Skip if we already processed this file and it hasn't changed
        if self._last_mtime.get(config_filename) == mtime:
            return

        # Read config JSON
        try:
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as e:
            log.error("Invalid JSON in config %s: %s", config_path, e)
            return

        openapi_collection_id = data.get("openapi_collection_id")
        spec_file = data.get("spec_file")
        operations_list = data.get("operations")
        base_url_override = data.get("base_url")

        if not openapi_collection_id or not spec_file or not operations_list:
            log.warning("Config %s missing 'openapi_collection_id', 'spec_file', or 'operations'", config_path)
            return
        openapi_collection_id = str(openapi_collection_id).strip()
        if not openapi_collection_id:
            log.warning("Config %s: openapi_collection_id cannot be empty", config_path)
            return

        # Fetch spec from Azure and create local copy in openapi_tools/azure_openapi_specs/
        try:
            spec_path = download_spec_from_azure(spec_file)
        except (FileNotFoundError, ValueError) as e:
            log.error("Spec file %s: %s", spec_file, e)
            return

        # Remove any tools we had previously added from this config (idempotent update)
        self._remove_tools_for_config(config_filename)

        # Load spec from local path and get operations
        try:
            spec = load_spec(spec_path)
        except Exception as e:
            log.error("Failed to load spec %s: %s", spec_path, e)
            return

        base_url = get_base_url(spec, override=base_url_override)
        all_ops = extract_operations(spec)
        ops_by_id = {op["operationId"]: op for op in all_ops}
        # Unique tool name: suffix openapi_collection_id so tools stay unique across collections
        added = set()
        for op_id in operations_list:
            if not isinstance(op_id, str):
                op_id = str(op_id)
            op_id = op_id.strip()
            if not op_id or op_id not in ops_by_id:
                continue
            op = ops_by_id[op_id]
            tool_name = f"{op_id}_{openapi_collection_id}"
            schema = build_input_schema(spec, op)
            tool = OpenAPITool(
                name=tool_name,
                operation=op,
                input_schema=schema,
                base_url=base_url,
                headers=self._api_headers or None,
                timeout=30.0,
            )
            try:
                self.mcp.add_tool(tool)
                added.add(tool_name)
            except Exception as e:
                log.error("Failed to add tool %s: %s", tool_name, e)

        if added:
            self._tools_by_config[config_filename] = added
            self._last_mtime[config_filename] = mtime
            log.info("Config %s: added %d tool(s) %s", config_filename, len(added), sorted(added))

    def handle_deleted_file(self, file_path: Path) -> None:
        """When a config file is deleted, remove all tools that were added from it."""
        if file_path.suffix.lower() != ".json":
            return
        self._remove_tools_for_config(file_path.name)
        log.info("Removed tools for deleted config: %s", file_path.name)

    def _initial_load_all(self) -> None:
        """Process all existing config files in the local directory (e.g. after first sync)."""
        for path in self.local_dir.glob("*.json"):
            self._load_single_config(path)


# ---------------------------------------------------------------------------
# Watchdog: watch local OpenAPI config directory for new/updated/deleted files
# ---------------------------------------------------------------------------
class OpenAPIConfigWatcher(FileSystemEventHandler):
    """Fires when JSON config files are created, modified, or deleted in the synced folder."""

    def __init__(self, server: OpenAPIConfigServer, watch_dir: Path):
        self.server = server
        self.watch_dir = Path(watch_dir)
        self.observer = Observer()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".json":
            self.server._load_single_config(path)

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".json":
            self.server._load_single_config(path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".json":
            self.server.handle_deleted_file(path)

    def start(self):
        self.observer.schedule(self, str(self.watch_dir.resolve()), recursive=False)
        self.observer.start()


# ---------------------------------------------------------------------------
# Azure → Local sync: only config JSONs go to openapi_tools/azure_openapi_configs.
# Spec files are not synced here; they are downloaded from Azure when we add tools
# (see download_spec_from_azure) into openapi_tools/azure_openapi_specs.
# ---------------------------------------------------------------------------
def _is_config_file(filename: str) -> bool:
    """Only .json config files are synced to the config dir."""
    return filename.lower().endswith(".json")


def download_if_newer(remote_dir: ShareDirectoryClient, filename: str, local_dir: Path) -> bool:
    """Download remote file if new or updated. Returns True if local file was created/updated."""
    if not _is_config_file(filename):
        return False
    local_path = local_dir / filename
    file_client = remote_dir.get_file_client(filename)
    try:
        props = file_client.get_file_properties()
    except ResourceNotFoundError:
        return False
    remote_mtime = props["last_modified"].timestamp()
    local_mtime = local_path.stat().st_mtime if local_path.exists() else 0.0
    if (not local_path.exists()) or (remote_mtime > local_mtime + 1e-6):
        # Write to a temporary non-.json file first, then atomically replace.
        # This prevents the watchdog from reading a partially-written JSON file.
        temp_path = local_dir / f".{filename}.tmp"
        with open(temp_path, "wb") as f:
            f.write(file_client.download_file().readall())
        os.replace(temp_path, local_path)
        return True
    return False


def sync_openapi_config_from_azure_once(server: Optional[OpenAPIConfigServer] = None) -> None:
    """
    One sync cycle: pull new/updated config .json files only; remove local configs no longer on Azure.
    If a server is provided, immediately (re)load any config files that were updated in this cycle.
    """
    try:
        remote_items = list(REMOTE_CONFIG_DIR_CLIENT.list_directories_and_files())
    except ResourceNotFoundError:
        ensure_remote_directory_hierarchy(REMOTE_CONFIG_PREFIX)
        return

    remote_config_names = {it["name"] for it in remote_items if _is_config_file(it["name"])}

    for name in remote_config_names:
        try:
            updated = download_if_newer(REMOTE_CONFIG_DIR_CLIENT, name, LOCAL_OPENAPI_CONFIG_DIR)
            if updated and server is not None:
                # Immediately load/reload this config so tools get created/updated.
                config_path = LOCAL_OPENAPI_CONFIG_DIR / name
                server._load_single_config(config_path)
        except Exception as e:
            log.error("Error pulling '%s': %s", name, e)

    local_config_names = {p.name for p in LOCAL_OPENAPI_CONFIG_DIR.iterdir() if p.is_file() and _is_config_file(p.name)}
    to_delete = local_config_names - remote_config_names
    for name in to_delete:
        try:
            (LOCAL_OPENAPI_CONFIG_DIR / name).unlink(missing_ok=True)
        except Exception as e:
            log.error("Error deleting local '%s': %s", name, e)


def sync_loop(server: OpenAPIConfigServer, interval_seconds: int = 60) -> None:
    """Background thread: poll Azure periodically to keep local OpenAPI config dir in sync and load configs."""
    while True:
        try:
            sync_openapi_config_from_azure_once(server)
        except Exception as e:
            log.error("Sync cycle error: %s", e)
        time.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ensure_remote_directory_hierarchy(REMOTE_CONFIG_PREFIX)
    sync_openapi_config_from_azure_once()

    server = OpenAPIConfigServer(mcp, LOCAL_OPENAPI_CONFIG_DIR)
    server._initial_load_all()

    watcher = OpenAPIConfigWatcher(server, LOCAL_OPENAPI_CONFIG_DIR)
    watcher.start()

    t = threading.Thread(target=sync_loop, kwargs={"server": server, "interval_seconds": 60}, daemon=True)
    t.start()

    host = os.environ.get("OPENAPI_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENAPI_MCP_PORT", "9000"))
    path = "/sse"
    log.info("MCP server starting at http://%s:%s%s (SSE)", host, port, path)
    mcp.run(transport="sse", host=host, port=port, path=path)


if __name__ == "__main__":
    main()


