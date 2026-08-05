"""Tenant and Workspace Catalog Scoping Module (Phase 3)."""
from __future__ import annotations

import logging
from typing import List, Optional

from plugins.identity import Principal
from plugins.rbac.evaluator import PolicyEvaluator
from plugins.tenancy.base import TenancyStore

log = logging.getLogger("MCP_logger")


async def filter_tools_for_principal(
    store: TenancyStore,
    evaluator: Optional[PolicyEvaluator],
    principal: Optional[Principal],
    tools: List[dict],
) -> List[dict]:
    """Filter a list of tools (from local loader or upstreams) based on caller principal,
    organization ownership, visibility, and evaluation rules.
    """
    if not tools:
        return []

    if principal is None:
        from plugins.identity import create_anonymous_principal
        principal = create_anonymous_principal()

    # SuperAdmin sees all tools
    if "platform_superadmin" in principal.roles or getattr(principal, "is_superadmin", False):
        return tools

    filtered: List[dict] = []
    for tool in tools:
        tool_name = tool.get("name") or tool.get("tool") or ""
        if not tool_name:
            continue

        if evaluator is not None:
            eval_res = await evaluator.evaluate(principal, "tool:list", tool_name)
            if eval_res.allowed:
                filtered.append(tool)
                continue

        # Fallback check on ownership
        ownership = await store.get_tool_ownership(tool_name)
        if ownership is None:
            # Default un-registered tools to public or caller org
            filtered.append(tool)
        elif ownership.visibility == "public":
            filtered.append(tool)
        elif ownership.owner_org == principal.org_id:
            filtered.append(tool)

    return filtered
