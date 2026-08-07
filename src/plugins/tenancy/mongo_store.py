"""MongoDB implementation of TenancyStore (modeled after hire-pilot's mongo_pool.py, Phase 1)."""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Set

from plugins.identity import Principal, derive_principal_id, select_tenant_context
from .base import TenancyStore
from .models import AuditEntry, Membership, Organization, Role, ToolGrant, ToolOwnership, Workspace

try:
    import motor.motor_asyncio
    HAS_MOTOR = True
except ImportError:
    HAS_MOTOR = False


class MongoTenancyStore(TenancyStore):
    """MongoDB multi-replica tenancy store backend using Motor async client.
    Modeled after hire-pilot connection pool configuration and index setup.
    """

    def __init__(self, uri: str, db_name: str = "mcp_tenancy"):
        if not HAS_MOTOR:
            raise RuntimeError("motor package is required for MongoTenancyStore (pip install motor)")
        self.uri = uri
        self.db_name = db_name
        self._client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
        self._db = None

    def _get_db(self):
        if self._client is None:
            pool_config = dict(
                maxPoolSize=200,
                minPoolSize=10,
                maxIdleTimeMS=30_000,
                connectTimeoutMS=5_000,
                socketTimeoutMS=10_000,
                serverSelectionTimeoutMS=5_000,
                retryReads=True,
                retryWrites=True,
            )
            self._client = motor.motor_asyncio.AsyncIOMotorClient(self.uri, **pool_config)
            self._db = self._client[self.db_name]
        return self._db

    async def init_db(self) -> None:
        db = self._get_db()
        # Pre-create indexes modeled after hire-pilot's ensure_indexes()
        await asyncio.gather(
            db["organizations"].create_index("org_id", unique=True),
            db["workspaces"].create_index([("org_id", 1), ("name", 1)], unique=True),
            db["memberships"].create_index("principal_id"),
            db["memberships"].create_index([("principal_id", 1), ("org_id", 1)]),
            db["roles"].create_index("role", unique=True),
            db["tool_ownership"].create_index("tool_name", unique=True),
            db["tool_grants"].create_index([("scope_type", 1), ("scope_id", 1)]),
            db["audit"].create_index("org_id"),
            db["audit"].create_index([("ts", -1)]),
            # analytics rows: separate collection in the SAME db (never `audit`)
            db["analytics_results"].create_index([("org_id", 1), ("ts", -1)]),
        )

    # -- analytics capability (separate collection, same db) ---------------
    async def append_analytics(self, rows) -> None:
        if not rows:
            return
        db = self._get_db()
        await db["analytics_results"].insert_many([dict(r) for r in rows])

    async def query_analytics(self, *, org_id=None, tool: str = "",
                              errors_only: bool = False, limit: int = 50, offset: int = 0) -> dict:
        db = self._get_db()
        q = {}
        if org_id is not None:
            q["org_id"] = org_id
        if tool:
            q["tool"] = tool
        if errors_only:
            q["ok"] = False
        limit = max(1, min(500, limit))
        total = await db["analytics_results"].count_documents(q)
        cursor = (db["analytics_results"].find(q, {"_id": 0})
                  .sort("ts", -1).skip(offset).limit(limit))
        rows = await cursor.to_list(length=limit)
        nxt = offset + limit if offset + limit < total else None
        return {"total": total, "cursor": offset, "next_cursor": nxt, "results": rows}

    async def purge_analytics(self, cutoff: float) -> int:
        db = self._get_db()
        res = await db["analytics_results"].delete_many({"ts": {"$lt": cutoff}})
        return res.deleted_count

    async def is_empty(self) -> bool:
        db = self._get_db()
        return (await db["organizations"].estimated_document_count() == 0
                and await db["roles"].estimated_document_count() == 0)

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None

    async def resolve_principal(
        self,
        issuer: str,
        subject: str,
        active_org: Optional[str] = None,
        active_ws: Optional[str] = None,
    ) -> Optional[Principal]:
        db = self._get_db()
        pid = derive_principal_id(issuer, subject)

        cursor = db["memberships"].find({"principal_id": pid})
        rows = await cursor.to_list(length=100)

        memberships = [Membership(principal_id=pid, org_id=r["org_id"], role=r["role"], workspace_id=r.get("workspace_id")) for r in rows]

        # Header is only honored for orgs the caller is actually a member of.
        org_id, workspace_id = select_tenant_context(memberships, active_org, active_ws)

        roles: List[str] = []
        permissions: Set[str] = {"tool:list", "tool:call", "upstream:read", "upstream:call"}

        for m in memberships:
            if m.org_id == org_id:
                if m.role not in roles:
                    roles.append(m.role)
                r_doc = await db["roles"].find_one({"role": m.role})
                if r_doc:
                    permissions.update(r_doc.get("permissions", []))

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
        db = self._get_db()
        now = time.time()
        doc = {"org_id": org_id, "name": name, "status": "active", "created_at": now, "settings": settings or {}}
        await db["organizations"].replace_one({"org_id": org_id}, doc, upsert=True)
        return Organization(org_id=org_id, name=name, status="active", created_at=now, settings=settings or {})

    async def get_org(self, org_id: str) -> Optional[Organization]:
        db = self._get_db()
        doc = await db["organizations"].find_one({"org_id": org_id})
        if not doc:
            return None
        return Organization(org_id=doc["org_id"], name=doc["name"], status=doc.get("status", "active"), created_at=doc.get("created_at", 0.0), settings=doc.get("settings", {}))

    async def list_orgs(self, limit: int = 100, offset: int = 0) -> List[Organization]:
        db = self._get_db()
        cursor = db["organizations"].find().skip(offset).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [Organization(org_id=r["org_id"], name=r["name"], status=r.get("status", "active"), created_at=r.get("created_at", 0.0), settings=r.get("settings", {})) for r in rows]

    async def delete_org(self, org_id: str) -> bool:
        db = self._get_db()
        res = await db["organizations"].delete_one({"org_id": org_id})
        if res.deleted_count > 0:
            await db["memberships"].delete_many({"org_id": org_id})
            return True
        return False

    async def create_workspace(self, workspace_id: str, org_id: str, name: str) -> Workspace:
        db = self._get_db()
        now = time.time()
        doc = {"workspace_id": workspace_id, "org_id": org_id, "name": name, "created_at": now}
        await db["workspaces"].replace_one({"workspace_id": workspace_id}, doc, upsert=True)
        return Workspace(workspace_id=workspace_id, org_id=org_id, name=name, created_at=now)

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        db = self._get_db()
        doc = await db["workspaces"].find_one({"workspace_id": workspace_id})
        if not doc:
            return None
        return Workspace(workspace_id=doc["workspace_id"], org_id=doc["org_id"], name=doc["name"], created_at=doc.get("created_at", 0.0))

    async def list_workspaces(self, org_id: str, limit: int = 100, offset: int = 0) -> List[Workspace]:
        db = self._get_db()
        cursor = db["workspaces"].find({"org_id": org_id}).skip(offset).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [Workspace(workspace_id=r["workspace_id"], org_id=r["org_id"], name=r["name"], created_at=r.get("created_at", 0.0)) for r in rows]

    async def delete_workspace(self, workspace_id: str) -> bool:
        db = self._get_db()
        res = await db["workspaces"].delete_one({"workspace_id": workspace_id})
        return res.deleted_count > 0

    async def bind_member(
        self,
        principal_id: str,
        org_id: str,
        role: str,
        workspace_id: Optional[str] = None,
    ) -> Membership:
        db = self._get_db()
        ws_id = workspace_id or ""
        filter_doc = {"principal_id": principal_id, "org_id": org_id, "role": role, "workspace_id": ws_id}
        await db["memberships"].replace_one(filter_doc, filter_doc, upsert=True)
        return Membership(principal_id=principal_id, org_id=org_id, role=role, workspace_id=workspace_id)

    async def get_memberships(self, principal_id: str) -> List[Membership]:
        db = self._get_db()
        cursor = db["memberships"].find({"principal_id": principal_id})
        rows = await cursor.to_list(length=100)
        return [Membership(principal_id=r["principal_id"], org_id=r["org_id"], role=r["role"], workspace_id=r.get("workspace_id") or None) for r in rows]

    async def list_org_members(self, org_id: str, limit: int = 100, offset: int = 0) -> List[Membership]:
        db = self._get_db()
        cursor = db["memberships"].find({"org_id": org_id}).skip(offset).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [Membership(principal_id=r["principal_id"], org_id=r["org_id"], role=r["role"], workspace_id=r.get("workspace_id") or None) for r in rows]

    async def remove_member(
        self,
        principal_id: str,
        org_id: str,
        role: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> bool:
        db = self._get_db()
        query = {"principal_id": principal_id, "org_id": org_id}
        if role is not None:
            query["role"] = role
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        res = await db["memberships"].delete_many(query)
        return res.deleted_count > 0

    async def get_role(self, role_name: str) -> Optional[Role]:
        db = self._get_db()
        doc = await db["roles"].find_one({"role": role_name})
        if not doc:
            return None
        return Role(role=doc["role"], permissions=doc.get("permissions", []))

    async def list_roles(self, limit: int = 100, offset: int = 0) -> List[Role]:
        db = self._get_db()
        cursor = db["roles"].find().skip(offset).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [Role(role=r["role"], permissions=r.get("permissions", [])) for r in rows]

    async def save_role(self, role_name: str, permissions: List[str]) -> Role:
        db = self._get_db()
        doc = {"role": role_name, "permissions": permissions}
        await db["roles"].replace_one({"role": role_name}, doc, upsert=True)
        return Role(role=role_name, permissions=permissions)

    async def set_tool_ownership(
        self,
        tool_name: str,
        owner_org: str,
        owner_workspace: Optional[str] = None,
        created_by: Optional[str] = None,
        visibility: str = "private",
        tags: Optional[List[str]] = None,
    ) -> ToolOwnership:
        db = self._get_db()
        doc = {
            "tool_name": tool_name,
            "owner_org": owner_org,
            "owner_workspace": owner_workspace,
            "created_by": created_by,
            "visibility": visibility,
            "tags": tags or [],
        }
        await db["tool_ownership"].replace_one({"tool_name": tool_name}, doc, upsert=True)
        return ToolOwnership(
            tool_name=tool_name,
            owner_org=owner_org,
            owner_workspace=owner_workspace,
            created_by=created_by,
            visibility=visibility,
            tags=tags or [],
        )

    async def get_tool_ownership(self, tool_name: str) -> Optional[ToolOwnership]:
        db = self._get_db()
        doc = await db["tool_ownership"].find_one({"tool_name": tool_name})
        if not doc:
            return None
        return ToolOwnership(
            tool_name=doc["tool_name"],
            owner_org=doc["owner_org"],
            owner_workspace=doc.get("owner_workspace"),
            created_by=doc.get("created_by"),
            visibility=doc.get("visibility", "private"),
            tags=doc.get("tags", []),
        )

    async def add_tool_grant(
        self,
        scope_type: str,
        scope_id: str,
        effect: str,
        match_type: str,
        match_value: str,
    ) -> ToolGrant:
        db = self._get_db()
        now = time.time()
        doc = {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "effect": effect,
            "match_type": match_type,
            "match_value": match_value,
            "created_at": now,
        }
        res = await db["tool_grants"].insert_one(doc)
        return ToolGrant(
            id=str(res.inserted_id),
            scope_type=scope_type,
            scope_id=scope_id,
            effect=effect,
            match_type=match_type,
            match_value=match_value,
            created_at=now,
        )

    async def list_tool_grants(self, scope_type: Optional[str] = None, scope_id: Optional[str] = None,
                               limit: int = 500, offset: int = 0) -> List[ToolGrant]:
        db = self._get_db()
        query = {}
        if scope_type:
            query["scope_type"] = scope_type
        if scope_id:
            query["scope_id"] = scope_id
        cursor = db["tool_grants"].find(query).skip(offset).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [
            ToolGrant(
                id=str(r["_id"]),
                scope_type=r["scope_type"],
                scope_id=r["scope_id"],
                effect=r["effect"],
                match_type=r["match_type"],
                match_value=r["match_value"],
                created_at=r.get("created_at", 0.0),
            )
            for r in rows
        ]

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
        db = self._get_db()
        now = time.time()
        doc = {
            "ts": now,
            "actor_principal": actor_principal,
            "issuer": issuer,
            "org_id": org_id,
            "action": action,
            "resource": resource,
            "decision": decision,
            "detail": detail,
        }
        res = await db["audit"].insert_one(doc)
        return AuditEntry(
            id=str(res.inserted_id),
            ts=now,
            actor_principal=actor_principal,
            issuer=issuer,
            org_id=org_id,
            action=action,
            resource=resource,
            decision=decision,
            detail=detail,
        )

    async def query_audit(self, org_id: Optional[str] = None, limit: int = 50) -> List[AuditEntry]:
        db = self._get_db()
        query = {}
        if org_id:
            query["org_id"] = org_id
        cursor = db["audit"].find(query).sort("ts", -1).limit(limit)
        rows = await cursor.to_list(length=limit)
        return [
            AuditEntry(
                id=str(r["_id"]),
                ts=r.get("ts", 0.0),
                actor_principal=r["actor_principal"],
                issuer=r["issuer"],
                org_id=r["org_id"],
                action=r["action"],
                resource=r["resource"],
                decision=r["decision"],
                detail=r.get("detail", ""),
            )
            for r in rows
        ]
