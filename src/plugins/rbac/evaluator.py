"""Hierarchical Policy Evaluator Engine for RBAC & Multi-Tenancy (Phase 2)."""
from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass
from typing import Optional

from plugins.identity import Principal
from plugins.tenancy.base import TenancyStore
from .cache import DecisionCache

log = logging.getLogger("MCP_logger")


@dataclass(frozen=True)
class EvaluationResult:
    allowed: bool
    decision: str  # "ALLOW_SUPERADMIN" | "ALLOW_GRANT" | "ALLOW_ROLE" | "ALLOW_PUBLIC" | "DENY_EXPLICIT" | "DENY_NO_PERMISSION" | "DENY_TENANT_BOUNDARY"
    reason: str
    eval_time_ms: float

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reason": self.reason,
            "eval_time_ms": self.eval_time_ms,
        }


class PolicyEvaluator:
    """Deterministic 5-tier Hierarchical Policy Engine:
    1. SuperAdmin Override: platform_superadmin principal bypasses all checks.
    2. Explicit Deny Grants: Deny grants take precedence over allow grants.
    3. Explicit Allow Grants: Direct tool grants to user/org/workspace.
    4. RBAC Permission Check: Action in principal.permissions (tool:list, tool:call, tool:onboard, upstream:call).
    5. Tenant & Visibility Boundaries: owner_org == caller_org or visibility == public.
    """

    def __init__(self, store: TenancyStore, cache: Optional[DecisionCache] = None):
        self.store = store
        self.cache = cache or DecisionCache()

    def _match_grant(self, match_type: str, match_value: str, resource: str) -> bool:
        if match_type == "exact":
            return match_value == resource
        elif match_type == "prefix":
            return resource.startswith(match_value)
        elif match_type == "glob":
            return fnmatch.fnmatch(resource, match_value)
        return False

    async def evaluate(
        self,
        principal: Principal,
        action: str,
        resource: str,
        context: Optional[dict] = None,
    ) -> EvaluationResult:
        start_t = time.perf_counter()

        # Check L1 Decision Cache
        cached = self.cache.get(principal.principal_id, principal.org_id, principal.workspace_id, action, resource)
        if cached is not None and isinstance(cached, EvaluationResult):
            return cached

        # 1. Platform SuperAdmin Override
        if "platform_superadmin" in principal.roles or getattr(principal, "is_superadmin", False):
            res = EvaluationResult(
                allowed=True,
                decision="ALLOW_SUPERADMIN",
                reason=f"SuperAdmin bypass for principal {principal.principal_id[:12]}",
                eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
            )
            self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
            return res

        # 2. Check Explicit Tool Grants (Deny Grants first, then Allow Grants)
        grants = await self.store.list_tool_grants()
        for g in grants:
            if g.scope_type == "user" and g.scope_id != principal.principal_id:
                continue
            if g.scope_type == "org" and g.scope_id != principal.org_id:
                continue
            if g.scope_type == "workspace" and g.scope_id != principal.workspace_id:
                continue

            if self._match_grant(g.match_type, g.match_value, resource):
                if g.effect == "deny":
                    res = EvaluationResult(
                        allowed=False,
                        decision="DENY_EXPLICIT",
                        reason=f"Explicit deny grant matched for resource {resource}",
                        eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
                    )
                    self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
                    return res
                elif g.effect == "allow":
                    res = EvaluationResult(
                        allowed=True,
                        decision="ALLOW_GRANT",
                        reason=f"Explicit allow grant matched for resource {resource}",
                        eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
                    )
                    self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
                    return res


        # 3. Role Permissions Check
        if action and action not in principal.permissions:
            res = EvaluationResult(
                allowed=False,
                decision="DENY_NO_PERMISSION",
                reason=f"Principal lacks required permission {action!r}",
                eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
            )
            self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
            return res

        # 4. Tenant & Visibility Boundaries Check (for tools)
        if action in ("tool:call", "tool:list", "tool:manage") and resource:
            ownership = await self.store.get_tool_ownership(resource)
            if ownership:
                if ownership.visibility == "public":
                    res = EvaluationResult(
                        allowed=True,
                        decision="ALLOW_PUBLIC",
                        reason=f"Tool {resource} is public",
                        eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
                    )
                    self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
                    return res
                elif ownership.owner_org != principal.org_id:
                    res = EvaluationResult(
                        allowed=False,
                        decision="DENY_TENANT_BOUNDARY",
                        reason=f"Tool {resource} owned by organization {ownership.owner_org!r}, caller belongs to {principal.org_id!r}",
                        eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
                    )
                    self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
                    return res

        # 5. Default Allow for Role-permitted Action
        res = EvaluationResult(
            allowed=True,
            decision="ALLOW_ROLE",
            reason=f"Action {action!r} allowed by principal roles",
            eval_time_ms=round((time.perf_counter() - start_t) * 1000, 3),
        )
        self.cache.put(principal.principal_id, principal.org_id, principal.workspace_id, action, resource, res)
        return res
