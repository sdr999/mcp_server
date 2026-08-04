"""Best-effort ``notifications/tools/list_changed`` push to connected clients."""
from __future__ import annotations

import contextlib
import logging

log = logging.getLogger("MCP_logger")


def _discover_sessions(mcp):
    """Best-effort discovery of active MCP ServerSessions. FastMCP exposes no
    public registry, so this probes known internal attributes and returns []
    when none are found (clients still see changes on their next list_tools)."""
    for mgr_attr in ("_session_manager", "session_manager", "_sessions"):
        mgr = getattr(mcp, mgr_attr, None)
        if mgr is None:
            continue
        if isinstance(mgr, dict):
            return list(mgr.values())
        for s_attr in ("_sessions", "sessions", "_server_sessions"):
            sessions = getattr(mgr, s_attr, None)
            if isinstance(sessions, dict):
                return list(sessions.values())
            if isinstance(sessions, (list, set, tuple)):
                return list(sessions)
    return []


async def notify_tools_changed(mcp) -> None:
    """Push notifications/tools/list_changed to connected clients (best effort)."""
    try:
        sessions = _discover_sessions(mcp)
        sent = 0
        for sess in sessions:
            send = getattr(sess, "send_tool_list_changed", None)
            if send is None:
                continue
            with contextlib.suppress(Exception):
                await send()
                sent += 1
        if sent:
            log.info("Notified %d client session(s): tools/list_changed", sent)
    except Exception as exc:
        log.debug("tools/list_changed notify skipped: %s", exc)
