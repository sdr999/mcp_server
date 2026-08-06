"""Domain models for Multi-Tenancy & RBAC (Phase 1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class Organization:
    org_id: str
    name: str
    status: str = "active"  # active | suspended | deleting
    created_at: float = 0.0
    settings: dict = field(default_factory=dict)


@dataclass
class Workspace:
    workspace_id: str
    org_id: str
    name: str
    created_at: float = 0.0


@dataclass
class Membership:
    principal_id: str
    org_id: str
    role: str
    workspace_id: Optional[str] = None


@dataclass
class Role:
    role: str
    permissions: List[str] = field(default_factory=list)


@dataclass
class ToolOwnership:
    tool_name: str
    owner_org: str
    owner_workspace: Optional[str] = None
    created_by: Optional[str] = None  # principal_id
    visibility: str = "private"       # private | org | public
    tags: List[str] = field(default_factory=list)
    trusted_tags: List[str] = field(default_factory=list)


@dataclass
class ToolGrant:
    id: Optional[int]
    scope_type: str                  # org | workspace | role | principal
    scope_id: str
    effect: str                      # allow | deny
    match_type: str                  # name | tag | owner | all
    match_value: str
    created_at: float = 0.0


@dataclass
class AuditEntry:
    id: Optional[int]
    ts: float
    actor_principal: str
    issuer: str
    org_id: str
    action: str
    resource: str
    decision: str                    # allow | deny | shadow_deny
    detail: str = ""
