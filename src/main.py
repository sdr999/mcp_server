"""Secure, plugin-based MCP tool server.

Serves tools over SSE (FastMCP) from a local tools directory. Rebuilt on the
architecture documented in docs/MCP_SERVER_FEATURES.md and
docs/MCP_AUTH_GUIDE.md ("the multiple MCP server"), split into single-purpose
plugin components under ``plugins/`` -- but with no Azure (or any remote file
share) dependency: tools are always local, hot-reloaded by a filesystem watcher.

Tool authoring contract (see ``tools_sdk``): a module in the tools directory
may expose tools via a ``register(registrar)`` hook, a ``TOOLS`` export,
``@tool``-decorated functions, or the legacy "function name == file stem"
convention.

Tool onboarding (see docs/MCP_TOOL_ONBOARDING.md) replaces the removed Azure
sync as the way new tools arrive: ``POST /admin/tools/onboard`` accepts a
tool's source plus its pip dependencies, risk-assesses each dependency with
no hard dependency of its own (stdlib heuristics + a best-effort PyPI check),
and either installs + hot-loads it or holds it pending for an admin to
approve/reject via ``/admin/tools/pending``.

Security features (see docs/MCP_AUTH_GUIDE.md):
  * ``MCP_AUTH_TYPE``: none | api_key | bearer_jwt (JWKS-validated OAuth).
  * Admin API gated by ``MCP_ADMIN_TOKEN`` (disabled entirely when unset).
  * Constant-time credential comparisons (``hmac.compare_digest``).
  * Path-traversal-safe ``--config`` resolution (tools dir can't escape ``src/``).
  * Optional signed-tool manifest enforcement (``MCP_REQUIRE_SIGNED_TOOLS``).
  * Optional per-call subprocess sandboxing (``MCP_SANDBOX_TOOLS``).
  * Fault isolation: a broken tool module is logged and skipped, never crashes
    the server; a slow/hanging import is bounded by ``MCP_TOOL_IMPORT_TIMEOUT_SEC``.

Design notes
------------
* All start-up work runs inside ``main()`` -- importing this module has no
  side effects, so it can be unit-tested.
* Tool registry mutations happen ONLY on the serving event loop, drained from
  a thread-safe queue; the filesystem watcher merely enqueues.

CLI
---
    python main.py                       # serve, tools dir = src/tools (auto-created)
    python main.py --config <b64 path>    # serve, tools dir = src/<decoded path>
    python main.py --validate ./mytools   # CI gate: exit 0 if all modules load
    python main.py --sign ./mytools       # generate a signed manifest
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, List

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("MCP_logger")

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from plugins import cli as plugin_cli
from plugins.app import build_app
from plugins.config import build_context, make_parser, validate_context


def main(argv: Optional[List[str]] = None) -> None:
    args = make_parser().parse_args(argv)

    if args.validate is not None or args.sign is not None:
        from plugins.config import load_environment, DEFAULT_MANIFEST

        env = load_environment(SRC_DIR)
        if args.validate is not None:
            raise SystemExit(plugin_cli.run_validate(Path(args.validate), SRC_DIR))
        raise SystemExit(plugin_cli.run_sign(
            Path(args.sign),
            env.get("MCP_TOOL_SIGNING_KEY"),
            env.get("MCP_TOOL_MANIFEST", DEFAULT_MANIFEST),
        ))

    import uvicorn

    ctx = build_context(argv, base_dir=SRC_DIR)
    validate_context(ctx)

    ctx.tools_dir.mkdir(parents=True, exist_ok=True)
    init_file = ctx.tools_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# Auto-generated to make this a package\n", encoding="utf-8")
    package_root = str(ctx.tools_dir.resolve().parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)

    app, _mcp = build_app(ctx)
    log.info("Starting MCP tool server on %s:%s (auth=%s, tools_dir=%s)",
              ctx.host, ctx.port, ctx.auth_type or "none", ctx.tools_dir)
    uvicorn.run(app, host=ctx.host, port=ctx.port, log_level="info")


if __name__ == "__main__":
    main()
