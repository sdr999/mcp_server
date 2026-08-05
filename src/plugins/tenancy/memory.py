"""In-memory implementation of TenancyStore for fast testing and ephemeral mode (Phase 1)."""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Set

from plugins.identity import Principal, derive_principal_id
from .base import TenancyStore
from .models import AuditEntry, Membership, Organization, Role, ToolGrant, ToolOwnership, Workspace


class MemoryTenancyStore(TenancyStore):
    def __init__(self):
        self._lock = asyncio.Lock()
        self._orgs: Dict[str, Organization] = {}
        self._workspaces: Dict[str, Workspace] = {}
        self._memberships: List[Membership] = []
        self._roles: Dict[str, Role] = {}
        self._tool_ownerships: Dict[str, ToolOwnership] = {}
        self._tool_grants: List[ToolGrant] = []
        self._audit_logs: List[AuditEntry] = []
        self._grant_counter = 1
        self._audit_counter = 1

    async def init_db(self) -> None:
        pass  # In-memory requires no initialization

    async def resolve_principal(
        self,
        issuer: str,
        subject: str,
        active_org: Optional[str] = None,
        active_ws: Optional[str] = None,
    ) -> Optional[Principal]:
        async with self._lock:
            pid = derive_principal_id(issuer, subject)
            user_memberships = [m for m in self._memberships if m.principal_id == pid]

            org_id = active_org or (user_memberships[0].org_id if user_memberships else "default")
            workspace_id = active_ws or (user_memberships[0].workspace_id if user_memberships else "default")

            roles: List[str] = []
            permissions: Set[str] = {"tool:list", "tool:call", "upstream:read", "upstream:call"}

            for m in user_memberships:
                if m.org_id == org_id:
                    if m.role not in roles:
                        roles.append(m.role)
                    role_obj = self._roles.get(m.role)
                    if role_obj:
                        permissions.update(role_obj.permissions)

            return Principal(
                principal_id=pid,
                issuer=issuer,
                subject=subject,
                kind="user",
                org_id=org_id,
                workspace_id=workspace_id or "default",
                roles=roles if roles else ["agent_consumer"],
                permissions=permissions,
            )

    async def create_org(self, org_id: str, name: str, settings: Optional[dict] = None) -> Organization:
        async with self._lock:
            org = Organization(org_id=org_id, name=name, created_at=time.time(), settings=settings or {})
            self._orgs[org_id] = org
            return org

    async def get_org(self, org_id: str) -> Optional[Organization]:
        async with self._lock:
            return self._orgs.get(org_id)

    async def list_orgs(self, limit: int = 100, offset: int = 0) -> List[Organization]:
        async with self._lock:
            items = list(self._orgs.values())
            return items[offset : offset + limit]

    async def delete_org(self, org_id: str) -> bool:
        async with self._lock:
            if org_id in self._orgs:
                del self._orgs[org_id]
                self._memberships = [m for m in self._memberships if m.org_id != org_id]
                return True
            return False

    async def create_workspace(self, workspace_id: str, org_id: str, name: str) -> Workspace:
        async with self._lock:
            ws = Workspace(workspace_id=workspace_id, org_id=org_id, name=name, created_at=time.time())
            self._workspaces[workspace_id] = ws
            return ws

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        async with self._lock:
            return self._workspaces.get(workspace_id)

    async def list_workspaces(self, org_id: str) -> List[Workspace]:
        async with self._lock:
            return [w for w in self._workspaces.values() if w.org_id == org_id]

    async def delete_workspace(self, workspace_id: str) -> bool:
        async with self._lock:
            if workspace_id in self._workspaces:
                del self._workspaces[workspace_id]
                return True
            return False

    async def bind_member(
        self,
        principal_id: str,
        org_id: str,
        role: str,
        workspace_id: Optional[str] = None,
    ) -> Membership:
        async with self._lock:
            mem = Membership(principal_id=principal_id, org_id=org_id, role=role, workspace_id=workspace_id)
            # Remove existing matching record if present
            self._memberships = [
                m
                for m in self._memberships
                if not (m.principal_id == principal_id and m.org_id == org_id and m.role == role and m.workspace_id == workspace_id)
            ]
            self._memberships.append(mem)
            return mem

    async def get_memberships(self, principal_id: str) -> List[Membership]:
        async with self._lock:
            return [m for m in self._memberships if m.principal_id == principal_id]

    async def list_org_members(self, org_id: str) -> List[Membership]:
        async with self._lock:
            return [m for m in self._memberships if m.org_id == org_id]

    async def remove_member(
        self,
        principal_id: str,
        org_id: str,
        role: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> bool:
        async with self._lock:
            before_len = len(self._memberships)
            self._memberships = [
                m
                for m in self._memberships
                if not (
                    m.principal_id == principal_id
                    and m.org_id == org_id
                    and (role is None or m.role == role)
                    and (workspace_id is None or m.workspace_id == workspace_id)
                )
            ]
            return len(self._memberships) < before_len

    async def get_role(self, role_name: str) -> Optional[Role]:
        async with self._lock:
            return self._roles.get(role_name)

    async def list_roles(self) -> List[Role]:
        async with self._lock:
            return list(self._roles.values())

    async def save_role(self, role_name: str, permissions: List[str]) -> Role:
        async with self._lock:
            role = Role(role=role_name, permissions=permissions)
            self._roles[role_name] = role
            return role

    async def set_tool_ownership(
        self,
        tool_name: str,
        owner_org: str,
        owner_workspace: Optional[str] = None,
        created_by: Optional[str] = None,
        visibility: str = "private",
        tags: Optional[List[str]] = None,
    ) -> ToolOwnership:
        async with self._lock:
            towner = ToolOwnership(
                tool_name=tool_name,
                owner_org=owner_org,
                owner_workspace=owner_workspace,
                created_by=created_by,
                visibility=visibility,
                tags=tags or [],
            )
            self._tool_ownerships[tool_name] = towner
            return towner

    async def get_tool_ownership(self, tool_name: str) -> Optional[ToolOwnership]:
        async with self._lock:
            return self._tool_ownerships.get(tool_name)

    async def add_tool_grant(
        self,
        scope_type: str,
        scope_id: str,
        effect: str,
        match_type: str,
        match_value: str,
    ) -> ToolGrant:
        async with self._lock:
            grant = ToolGrant(
                id=self._grant_counter,
                scope_type=scope_type,
                scope_id=scope_id,
                effect=effect,
                match_type=match_type,
                match_value=match_value,
                created_at=time.time(),
            )
            self._grant_counter += 1
            self._tool_grants.append(grant)
            return grant

    async def list_tool_grants(self, scope_type: Optional[str] = None, scope_id: Optional[str] = None) -> List[ToolGrant]:
        async with self._lock:
            res = self._tool_grants
            if scope_type:
                res = [g for g in res if g.scope_type == scope_type]
            if scope_id:
                res = [g for g in res if g.scope_id == scope_id]
            return res

    async def log_audit(
        self,
        actor_principal: str,
        issuer: str,
        org_id: str,
        action: str,
        resource: str,
        decision: str,
        detail: str = "",
    ) -> AuditEntry:
        async with self._lock:
            entry = AuditEntry(
                id=self._audit_counter,
                ts=time.time(),
                actor_principal=actor_principal,
                issuer=issuer,
                org_id=org_id,
                action=action,
                resource=resource,
                decision=decision,
                detail=detail,
            )
            self._audit_counter += 1
            self._audit_logs.append(entry)
            return entry

    async def query_audit(self, org_id: Optional[str] = None, limit: int = 50) -> List[AuditEntry]:
        async with self._lock:
            res = self._audit_logs
            if org_id:
                res = [e for e in res if e.org_id == org_id]
            return res[-limit:]
