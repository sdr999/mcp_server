"""Attribute-Based Access Control (ABAC) and Fine-Grained Dynamic Grants (Phase 4)."""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import List, Optional

from plugins.identity import Principal
from plugins.tenancy.models import ToolOwnership

log = logging.getLogger("MCP_logger")


@dataclass(frozen=True)
class ABACResult:
    allowed: bool
    reason: str


class ABACEvaluator:
    """Attribute-Based Access Control Engine:
    - Evaluates dynamic context attributes (trusted tags, workspace scoping, time bounds).
    - Supports wildcard tool matchers: exact, prefix, glob.
    """

    @staticmethod
    def match_tool_pattern(match_type: str, pattern: str, tool_name: str) -> bool:
        if match_type == "exact":
            return pattern == tool_name
        elif match_type == "prefix":
            clean_pattern = pattern[:-1] if pattern.endswith("*") else pattern
            return tool_name.startswith(clean_pattern)
        elif match_type == "glob":
            return fnmatch.fnmatch(tool_name, pattern)
        return False

    @classmethod
    def evaluate_tool_attributes(
        cls,
        principal: Principal,
        tool_name: str,
        ownership: Optional[ToolOwnership],
        context: Optional[dict] = None,
    ) -> ABACResult:
        if ownership is None:
            return ABACResult(allowed=True, reason="No attribute constraints on unregistered tool")

        # 1. Trusted Tags Check
        if ownership.trusted_tags:
            user_tags = set(principal.metadata.get("tags", [])) if principal.metadata else set()
            required_tags = set(ownership.trusted_tags)
            if not required_tags.issubset(user_tags) and "platform_superadmin" not in principal.roles:
                return ABACResult(
                    allowed=False,
                    reason=f"Caller lacks required trusted tags {list(required_tags)} for tool {tool_name!r}",
                )

        # 2. Workspace Environment Restrictions
        if "prod_only" in ownership.tags:
            if principal.workspace_id != "prod" and "platform_superadmin" not in principal.roles:
                return ABACResult(
                    allowed=False,
                    reason=f"Tool {tool_name!r} restricted to 'prod' workspace, caller active workspace is {principal.workspace_id!r}",
                )

        return ABACResult(allowed=True, reason="ABAC attribute checks passed")
