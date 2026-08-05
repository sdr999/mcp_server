"""Configuration: environment + CLI parsing into an immutable ``AppContext``.

Precedence: an OS environment variable wins when set AND non-blank; otherwise
the checked-in ``config/.env`` provides the fallback (a blank OS value like
``KEY=""`` is treated as unset, so the fallback still applies). A missing
``config/.env`` is fine — this server has no required external dependency.
"""
from __future__ import annotations

import argparse
import base64
import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import dotenv_values

# Optional: the agentic framework is only needed so framework-authored tool
# modules can read the server's env via ``global_variables.env``. The server
# core never reads it, so this is a soft dependency — absence is fine.
try:
    from agentic_framework.utils import global_variables
except Exception:  # pragma: no cover - framework not installed
    global_variables = None

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_IMPORT_TIMEOUT = 30
DEFAULT_SANDBOX_TIMEOUT = 30
DEFAULT_MANIFEST = "tools.manifest.json"
DEFAULT_TOOLS_DIR = "tools"


@dataclass
class AppContext:
    base_dir: Path
    tools_dir: Path
    env: dict
    auth_type: str
    api_key_header: str
    api_key_value: str
    jwks_url: str
    jwt_issuer: Optional[str]
    jwt_audience: Optional[str]
    jwt_required_scopes: Optional[List[str]]
    host: str
    port: int
    import_timeout: float
    metrics_enabled: bool
    sandbox: bool
    sandbox_timeout: float
    sandbox_mem_mb: int
    sandbox_cpu_sec: int
    admin_token: str
    require_signed: bool
    manifest_name: str
    signing_key: Optional[str]
    jwt_algorithm: str = "ES256"
    onboard_enabled: bool = True


    onboard_autoinstall: bool = True
    onboard_network_check: bool = True
    onboard_network_timeout: float = 3.0
    onboard_install_timeout: float = 120.0
    onboard_allowlist_path: Optional[Path] = None
    onboard_denylist_path: Optional[Path] = None
    onboard_only_binary: bool = False
    onboard_audit_log: Optional[Path] = None
    onboard_require_explicit: bool = True
    onboard_max_tools: int = 0
    openapi_specs_dir: Optional[Path] = None
    # MCP protocol transport: "http" (streamable HTTP, single /mcp endpoint) or

    # "sse" (legacy, /sse + /messages). streamable HTTP is the current standard.
    mcp_transport: str = "http"
    mcp_stateless: bool = False     # streamable HTTP only: no per-session state
    # Per-route auth policies: "none" | "mcp" | "admin"
    read_auth: str = "mcp"          # /status, /tools
    metrics_auth: str = "mcp"       # /metrics
    tool_call_auth: str = "mcp"     # POST /tools/{name}/call
    upstream_auth: str = "mcp"      # /mcp/upstreams* (list + call)
    # Federation: remote MCP servers this server can list/call tools on

    upstreams: dict = field(default_factory=dict)   # name -> {"url", "token"}
    upstream_timeout: float = 30.0
    upstream_allow_runtime: bool = True             # admin add/remove at runtime

    # --- Supabase & Multi-Tenancy / RBAC (Phase 0 & 1) ---
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_jwt_kid: str = ""
    superadmin_email: str = ""
    rbac_enabled: bool = False
    rbac_mode: str = "enforce"  # shadow | enforce (§19 safe rollout)
    tenant_header: str = "X-Tenant-Id"
    workspace_header: str = "X-Workspace-Id"
    api_keys_file: Optional[Path] = None
    tenancy_store: str = "sqlite"
    tenancy_db_path: Optional[Path] = None
    tenancy_dsn: str = ""
    tenancy_db_name: str = "mcp_tenancy"
    rbac_cache_ttl: float = 30.0
    rbac_cache_size: int = 10000
    tenancy_seed: bool = True
    default_org: str = "default"








def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Secure, plugin-based MCP tool server")
    p.add_argument(
        "--config",
        help="Base64-encoded local tools directory path (relative to src/). "
             f"Defaults to {DEFAULT_TOOLS_DIR!r} when omitted.",
    )
    p.add_argument("--validate", metavar="DIR", help="Validate a local tools directory and exit")
    p.add_argument("--sign", metavar="DIR", help="Generate a signed manifest for a local dir and exit")
    return p


def merge_env(os_env, fallbacks: dict) -> dict:
    """OS env wins when set and non-blank; otherwise use the config/.env fallback."""
    env = dict(os_env)
    for key, value in (fallbacks or {}).items():
        if value is None:
            continue
        current = env.get(key)
        if current is None or str(current).strip() == "":
            env[key] = value
    return env


def load_environment(base_dir: Path) -> dict:
    """Build the process env. When the (optional) agentic framework is present,
    alias the result onto ``global_variables.env`` so framework-authored tool
    modules read the same configuration. The server core does not depend on it."""
    env_path = base_dir / "config" / ".env"
    fallbacks = dotenv_values(str(env_path)) if env_path.exists() else {}
    env = merge_env(os.environ, fallbacks)
    if global_variables is not None:
        global_variables.env = env
    return env


def decode_config_path(raw: str, base_dir: Path) -> Tuple[str, Path]:
    """Decode the base64 ``--config`` value into a validated tools directory.

    Raises ValueError on traversal / absolute / drive-qualified paths so a
    malformed or hostile config cannot escape ``base_dir``.
    """
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    decoded = base64.b64decode(raw).decode("utf-8").strip()

    if not decoded:
        raise ValueError("--config decoded to an empty path")
    if decoded.startswith(("/", "\\")) or ".." in Path(decoded).parts or ":" in decoded[:3]:
        raise ValueError(f"--config tool path is not a safe relative path: {decoded!r}")

    base_resolved = base_dir.resolve()
    local = (base_dir / decoded).resolve()
    if not local.is_relative_to(base_resolved):
        raise ValueError(f"--config path escapes base dir: {decoded!r}")
    return decoded, local


_VALID_POLICIES = ("none", "mcp", "admin")


def _policy(env: dict, key: str, default: str = "mcp") -> str:
    val = (env.get(key) or default).lower()
    if val not in _VALID_POLICIES:
        raise RuntimeError(f"{key} must be one of {_VALID_POLICIES}, got {val!r}")
    return val


def _load_upstreams(env: dict, base_dir: Path) -> dict:
    """Parse configured remote MCP servers from MCP_UPSTREAMS (inline JSON) or
    MCP_UPSTREAMS_FILE (a JSON file). Normalizes to {name: {"url", "token"}}."""
    raw = None
    if env.get("MCP_UPSTREAMS"):
        raw = env["MCP_UPSTREAMS"]
    elif env.get("MCP_UPSTREAMS_FILE"):
        p = base_dir / env["MCP_UPSTREAMS_FILE"]
        raw = p.read_text(encoding="utf-8") if p.exists() else None
    if not raw:
        return {}
    data = json.loads(raw)
    out = {}
    for name, spec in (data or {}).items():
        if isinstance(spec, str):
            spec = {"url": spec}
        url = spec.get("url")
        if not url:
            raise RuntimeError(f"upstream {name!r} is missing a 'url'")
        out[str(name)] = {"url": url, "token": spec.get("token") or None}
    return out


def build_context(argv: Optional[List[str]] = None, base_dir: Optional[Path] = None) -> AppContext:
    """Parse args + environment into a context for server mode. No I/O beyond
    reading ``config/.env`` (if present)."""
    args = make_parser().parse_args(argv)
    base_dir = base_dir or Path(__file__).resolve().parent.parent

    env = load_environment(base_dir)

    if args.config:
        _, tools_dir = decode_config_path(args.config, base_dir)
    else:
        tools_dir = (base_dir / DEFAULT_TOOLS_DIR).resolve()

    auth_type = (env.get("MCP_AUTH_TYPE") or "").lower()
    if not auth_type and env.get("MCP_AUTHENTICATION_FLAG", "false").lower() == "true":
        auth_type = "bearer_jwt"  # backward compat

    scopes = [s.strip() for s in (env.get("MCP_JWT_REQUIRED_SCOPES") or "").split(",") if s.strip()]

    return AppContext(
        base_dir=base_dir,
        tools_dir=tools_dir,
        env=env,
        auth_type=auth_type,
        api_key_header=env.get("MCP_API_KEY_HEADER", "Authorization").lower(),
        api_key_value=env.get("MCP_API_KEY_VALUE", ""),
        jwks_url=env.get("JWKS_URL", ""),
        jwt_issuer=env.get("MCP_JWT_ISSUER") or None,
        jwt_audience=env.get("MCP_JWT_AUDIENCE") or None,
        jwt_required_scopes=scopes or None,
        jwt_algorithm=env.get("MCP_JWT_ALGORITHM", "ES256"),
        host=env.get("MCP_HOST", DEFAULT_HOST),

        port=int(env.get("MCP_PORT", DEFAULT_PORT)),
        import_timeout=float(env.get("MCP_TOOL_IMPORT_TIMEOUT_SEC", DEFAULT_IMPORT_TIMEOUT)),
        metrics_enabled=(env.get("MCP_METRICS", "true").lower() == "true"),
        sandbox=(env.get("MCP_SANDBOX_TOOLS", "false").lower() == "true"),
        sandbox_timeout=float(env.get("MCP_SANDBOX_TIMEOUT_SEC", DEFAULT_SANDBOX_TIMEOUT)),
        sandbox_mem_mb=int(env.get("MCP_SANDBOX_MEM_MB", "0")),
        sandbox_cpu_sec=int(env.get("MCP_SANDBOX_CPU_SEC", "0")),
        admin_token=env.get("MCP_ADMIN_TOKEN", ""),
        require_signed=env.get("MCP_REQUIRE_SIGNED_TOOLS", "false").lower() == "true",
        manifest_name=env.get("MCP_TOOL_MANIFEST", DEFAULT_MANIFEST),
        signing_key=env.get("MCP_TOOL_SIGNING_KEY") or None,
        onboard_enabled=env.get("MCP_TOOL_ONBOARD_ENABLED", "true").lower() == "true",
        onboard_autoinstall=env.get("MCP_TOOL_AUTOINSTALL_DEPS", "true").lower() == "true",
        onboard_network_check=env.get("MCP_TOOL_RISK_NETWORK_CHECK", "true").lower() == "true",
        onboard_network_timeout=float(env.get("MCP_TOOL_RISK_NETWORK_TIMEOUT_SEC", "3")),
        onboard_install_timeout=float(env.get("MCP_TOOL_INSTALL_TIMEOUT_SEC", "120")),
        onboard_allowlist_path=(base_dir / p if (p := env.get("MCP_TOOL_DEPENDENCY_ALLOWLIST")) else None),
        onboard_denylist_path=(base_dir / p if (p := env.get("MCP_TOOL_DEPENDENCY_DENYLIST")) else None),
        onboard_only_binary=env.get("MCP_TOOL_INSTALL_ONLY_BINARY", "false").lower() == "true",
        onboard_audit_log=(base_dir / (env.get("MCP_TOOL_AUDIT_LOG") or "logs/onboarding_audit.log")),
        onboard_require_explicit=env.get("MCP_TOOL_ONBOARD_REQUIRE_EXPLICIT", "true").lower() == "true",
        onboard_max_tools=int(env.get("MCP_TOOL_ONBOARD_MAX_TOOLS", "0")),
        mcp_transport=(env.get("MCP_TRANSPORT") or "http").lower(),
        mcp_stateless=env.get("MCP_STATELESS_HTTP", "false").lower() == "true",
        read_auth=_policy(env, "MCP_READ_AUTH"),
        metrics_auth=_policy(env, "MCP_METRICS_AUTH"),
        tool_call_auth=_policy(env, "MCP_TOOL_CALL_AUTH"),
        upstream_auth=_policy(env, "MCP_UPSTREAM_AUTH"),
        upstreams=_load_upstreams(env, base_dir),
        upstream_timeout=float(env.get("MCP_UPSTREAM_TIMEOUT_SEC", "30")),
        upstream_allow_runtime=env.get("MCP_UPSTREAM_ALLOW_RUNTIME", "true").lower() == "true",
        supabase_url=env.get("SUPABASE_URL", ""),
        supabase_key=env.get("SUPABASE_KEY") or env.get("SUPABASE_PUBLISHABLE_KEY") or "",
        supabase_jwt_kid=env.get("SUPABASE_JWT_KID", ""),
        superadmin_email=env.get("MCP_SUPERADMIN_EMAIL", ""),
        api_keys_file=(base_dir / p if (p := env.get("MCP_API_KEYS_FILE")) else None),
        tenancy_store=env.get("MCP_TENANCY_STORE", "sqlite").lower(),
        tenancy_db_path=(base_dir / p if (p := env.get("MCP_TENANCY_DB")) else (base_dir / "data" / "tenancy.db")),
        tenancy_dsn=env.get("MCP_TENANCY_DSN") or env.get("MONGODB_URI") or "",
        tenancy_db_name=env.get("MCP_TENANCY_DB_NAME") or env.get("DB_NAME") or "mcp_tenancy",
        rbac_cache_ttl=float(env.get("MCP_RBAC_CACHE_TTL_SEC", "30")),
        rbac_cache_size=int(env.get("MCP_RBAC_CACHE_MAX_SIZE", "10000")),
        tenancy_seed=env.get("MCP_TENANCY_SEED", "true").lower() == "true",
        default_org=env.get("MCP_DEFAULT_ORG", "default"),
        rbac_enabled=env.get("MCP_RBAC_ENABLED", "false").lower() == "true",
        rbac_mode=env.get("MCP_RBAC_MODE", "enforce").lower(),
    )






def validate_context(ctx: AppContext) -> None:
    """Fail fast on missing required configuration."""
    if ctx.mcp_transport not in ("http", "streamable-http", "sse"):
        raise RuntimeError(f"MCP_TRANSPORT must be http|streamable-http|sse, got {ctx.mcp_transport!r}")
    if ctx.auth_type not in ("", "none", "api_key", "bearer_jwt"):
        raise RuntimeError(f"MCP_AUTH_TYPE must be none|api_key|bearer_jwt, got {ctx.auth_type!r}")
    if ctx.auth_type == "bearer_jwt" and not ctx.jwks_url:
        raise RuntimeError("JWKS_URL must be set when MCP_AUTH_TYPE=bearer_jwt")
    if ctx.auth_type == "api_key" and not ctx.api_key_value:
        raise RuntimeError("MCP_API_KEY_VALUE must be set when MCP_AUTH_TYPE=api_key")
    if ctx.rbac_mode not in ("shadow", "enforce"):
        raise RuntimeError(f"MCP_RBAC_MODE must be shadow|enforce, got {ctx.rbac_mode!r}")
