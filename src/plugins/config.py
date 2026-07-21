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
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import dotenv_values

from agentic_framework.utils import global_variables

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
    """Build the process env and alias it onto ``global_variables.env`` so the
    framework and tool modules read the same configuration."""
    env_path = base_dir / "config" / ".env"
    fallbacks = dotenv_values(str(env_path)) if env_path.exists() else {}
    env = merge_env(os.environ, fallbacks)
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
    )


def validate_context(ctx: AppContext) -> None:
    """Fail fast on missing required configuration."""
    if ctx.auth_type not in ("", "none", "api_key", "bearer_jwt"):
        raise RuntimeError(f"MCP_AUTH_TYPE must be none|api_key|bearer_jwt, got {ctx.auth_type!r}")
    if ctx.auth_type == "bearer_jwt" and not ctx.jwks_url:
        raise RuntimeError("JWKS_URL must be set when MCP_AUTH_TYPE=bearer_jwt")
    if ctx.auth_type == "api_key" and not ctx.api_key_value:
        raise RuntimeError("MCP_API_KEY_VALUE must be set when MCP_AUTH_TYPE=api_key")
