"""Abstract base class interface for the Pluggable Tenancy Store (Phase 1)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Set, Tuple

from plugins.identity import Principal
from .models import AuditEntry, Membership, Organization, Role, ToolGrant, ToolOwnership, Workspace


class TenancyStore(ABC):
    """Abstract interface for all TenancyStore backends (memory, json, sqlite, postgres).
    All methods are async and fail-closed.
    """

    @abstractmethod
    async def init_db(self) -> None:
        """Initialize database schema, tables, and migrations."""
        pass

    @abstractmethod
    async def resolve_principal(
        self,
        issuer: str,
        subject: str,
        active_org: Optional[str] = None,
        active_ws: Optional[str] = None,
    ) -> Optional[Principal]:
        """Hot-path query: Join identity + store memberships + roles + permissions."""
        pass

    # --- Organization Management ---
    @abstractmethod
    async def create_org(self, org_id: str, name: str, settings: Optional[dict] = None) -> Organization:
        pass

    @abstractmethod
    async def get_org(self, org_id: str) -> Optional[Organization]:
        pass

    @abstractmethod
    async def list_orgs(self, limit: int = 100, offset: int = 0) -> List[Organization]:
        pass

    @abstractmethod
    async def delete_org(self, org_id: str) -> bool:
        pass

    # --- Workspace Management ---
    @abstractmethod
    async def create_workspace(self, workspace_id: str, org_id: str, name: str) -> Workspace:
        pass

    @abstractmethod
    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        pass

    @abstractmethod
    async def list_workspaces(self, org_id: str) -> List[Workspace]:
        pass

    @abstractmethod
    async def delete_workspace(self, workspace_id: str) -> bool:
        pass

    # --- Memberships & Role Bindings ---
    @abstractmethod
    async def bind_member(
        self,
        principal_id: str,
        org_id: str,
        role: str,
        workspace_id: Optional[str] = None,
    ) -> Membership:
        pass

    @abstractmethod
    async def get_memberships(self, principal_id: str) -> List[Membership]:
        pass

    @abstractmethod
    async def list_org_members(self, org_id: str) -> List[Membership]:
        pass

    @abstractmethod
    async def remove_member(
        self,
        principal_id: str,
        org_id: str,
        role: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> bool:
        pass

    # --- Role Definitions ---
    @abstractmethod
    async def get_role(self, role_name: str) -> Optional[Role]:
        pass

    @abstractmethod
    async def list_roles(self) -> List[Role]:
        pass

    @abstractmethod
    async def save_role(self, role_name: str, permissions: List[str]) -> Role:
        pass

    # --- Tool Ownership & Grants ---
    @abstractmethod
    async def set_tool_ownership(
        self,
        tool_name: str,
        owner_org: str,
        owner_workspace: Optional[str] = None,
        created_by: Optional[str] = None,
        visibility: str = "private",
        tags: Optional[List[str]] = None,
    ) -> ToolOwnership:
        pass

    @abstractmethod
    async def get_tool_ownership(self, tool_name: str) -> Optional[ToolOwnership]:
        pass

    @abstractmethod
    async def add_tool_grant(
        self,
        scope_type: str,
        scope_id: str,
        effect: str,
        match_type: str,
        match_value: str,
    ) -> ToolGrant:
        pass

    @abstractmethod
    async def list_tool_grants(self, scope_type: Optional[str] = None, scope_id: Optional[str] = None) -> List[ToolGrant]:
        pass

    # --- Audit Trail ---
    @abstractmethod
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
        pass

    @abstractmethod
    async def query_audit(self, org_id: Optional[str] = None, limit: int = 50) -> List[AuditEntry]:
        pass
