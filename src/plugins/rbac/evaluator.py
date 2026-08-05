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

    def _grant_applies_to(self, grant, principal: Principal) -> bool:
        """Whether a grant's scope targets this principal.

        Scope types (aligned with the data model): principal | org | workspace |
        role. ``user`` is accepted as an alias for ``principal``. An unrecognized
        scope_type does NOT apply — it must never fall through and match everyone.
        """
        st = grant.scope_type
        if st in ("principal", "user"):
            return grant.scope_id == principal.principal_id
        if st == "org":
            return grant.scope_id == principal.org_id
        if st == "workspace":
            return grant.scope_id == principal.workspace_id
        if st == "role":
            return grant.scope_id in principal.roles
        return False

    def _match_grant(self, grant, resource: str, ownership=None) -> bool:
        """Whether a grant's match clause selects ``resource``.

        The data-model vocabulary (§6, §8) is the ``match_type`` dimension:
          - ``all``   → matches any resource.
          - ``name``  → matches the tool name; ``match_value`` may contain glob
                        wildcards (``* ? []``), else it is an exact match.
          - ``tag``   → matches if the tool's ownership carries that tag.
          - ``owner`` → matches if the tool's owning org equals ``match_value``.
        Legacy pattern aliases (``exact`` | ``prefix`` | ``glob``) are still
        accepted and treated as name-pattern matches for backward compatibility.
        """
        mt = (grant.match_type or "").lower()
        mv = grant.match_value or ""

        if mt == "all":
            return True
        if mt == "name":
            if any(ch in mv for ch in "*?["):
                return fnmatch.fnmatch(resource, mv)
            return resource == mv
        if mt == "tag":
            return bool(ownership and mv in (ownership.tags or []))
        if mt == "owner":
            return bool(ownership and ownership.owner_org == mv)

        # --- backward-compatible pattern aliases (name-pattern semantics) ---
        if mt == "exact":
            return resource == mv
        if mt == "prefix":
            base = mv[:-1] if mv.endswith("*") else mv
            return resource.startswith(base)
        if mt == "glob":
            return fnmatch.fnmatch(resource, mv)
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

        # Resolve tool ownership once up front — grant matching (tag/owner) and the
        # tenant-boundary check below both need it, and it saves a second lookup.
        ownership = None
        if resource and action in ("tool:call", "tool:list", "tool:manage"):
            ownership = await self.store.get_tool_ownership(resource)

        # 2. Check Explicit Tool Grants.
        # Precedence is DENY-OVERRIDE (§17.13): a matching deny at ANY scope wins
        # over any allow, regardless of order or specificity. So we must scan ALL
        # matching grants, not return on the first one.
        grants = await self.store.list_tool_grants()
        matched_allow = False
        for g in grants:
            if not self._grant_applies_to(g, principal):
                continue
            if not self._match_grant(g, resource, ownership):
                continue
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
                matched_allow = True

        if matched_allow:
            res = EvaluationResult(
                allowed=True,
                decision="ALLOW_GRANT",
                reason=f"Explicit allow grant matched for resource {resource} (no deny overrode it)",
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

        # 4. Tenant & Visibility Boundaries Check (for tools). ``ownership`` was
        # resolved once above.
        if action in ("tool:call", "tool:list", "tool:manage") and resource:
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

                # ABAC Attribute Evaluation (Phase 4)
                from .abac import ABACEvaluator
                abac_res = ABACEvaluator.evaluate_tool_attributes(principal, resource, ownership, context)
                if not abac_res.allowed:
                    res = EvaluationResult(
                        allowed=False,
                        decision="DENY_ABAC_ATTRIBUTE",
                        reason=abac_res.reason,
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
