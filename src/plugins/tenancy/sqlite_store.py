"""SQLite implementation of TenancyStore (default single-node backend, Phase 1)."""
from __future__ import annotations

import asyncio
import contextlib
import json

import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from plugins.identity import Principal, derive_principal_id, select_tenant_context
from .base import TenancyStore
from .models import AuditEntry, Membership, Organization, Role, ToolGrant, ToolOwnership, Workspace

CURRENT_SCHEMA_VERSION = 1


class SqliteTenancyStore(TenancyStore):
    """SQLite single-node tenancy store backend using stdlib sqlite3.
    Executes database operations via asyncio.to_thread to keep event loop non-blocking.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    @contextlib.contextmanager
    def _get_conn(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


    async def init_db(self) -> None:
        def _run_init():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        version INTEGER PRIMARY KEY
                    )
                """
                )
                cur.execute("SELECT version FROM schema_meta LIMIT 1")
                row = cur.fetchone()
                if not row:
                    cur.execute("INSERT INTO schema_meta (version) VALUES (?)", (CURRENT_SCHEMA_VERSION,))

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS organizations (
                        org_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        status TEXT DEFAULT 'active',
                        created_at REAL NOT NULL,
                        settings_json TEXT
                    )
                """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspaces (
                        workspace_id TEXT PRIMARY KEY,
                        org_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        UNIQUE(org_id, name)
                    )
                """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memberships (
                        principal_id TEXT NOT NULL,
                        org_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        workspace_id TEXT,
                        PRIMARY KEY(principal_id, org_id, role, workspace_id)
                    )
                """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS roles (
                        role TEXT PRIMARY KEY,
                        permissions_json TEXT NOT NULL
                    )
                """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_ownership (
                        tool_name TEXT PRIMARY KEY,
                        owner_org TEXT NOT NULL,
                        owner_workspace TEXT,
                        created_by TEXT,
                        visibility TEXT DEFAULT 'private',
                        tags_json TEXT,
                        trusted_tags_json TEXT
                    )
                """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_grants (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scope_type TEXT NOT NULL,
                        scope_id TEXT NOT NULL,
                        effect TEXT NOT NULL,
                        match_type TEXT NOT NULL,
                        match_value TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        actor_principal TEXT NOT NULL,
                        issuer TEXT NOT NULL,
                        org_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        detail TEXT
                    )
                """
                )
                # Analytics result-audit rows -- a SEPARATE table in the SAME db,
                # never the transactional `audit` table (review R3).
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        tool TEXT NOT NULL,
                        ok INTEGER NOT NULL,
                        duration_ms REAL,
                        error_type TEXT,
                        error_msg TEXT,
                        org_id TEXT,
                        kind TEXT,
                        caller_fp TEXT,
                        result_excerpt TEXT
                    )
                """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS ix_analytics_org_ts ON analytics_results (org_id, ts)")
                conn.commit()

        await asyncio.to_thread(_run_init)

    async def is_empty(self) -> bool:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT (SELECT COUNT(*) FROM organizations) + (SELECT COUNT(*) FROM roles) AS n")
                return cur.fetchone()["n"] == 0
        return await asyncio.to_thread(_run)

    async def close(self) -> None:
        # Connections are opened per-operation and closed in _get_conn(); nothing
        # persistent to release.
        return None

    async def resolve_principal(
        self,
        issuer: str,
        subject: str,
        active_org: Optional[str] = None,
        active_ws: Optional[str] = None,
    ) -> Optional[Principal]:
        pid = derive_principal_id(issuer, subject)

        def _query():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT org_id, role, workspace_id FROM memberships WHERE principal_id = ?", (pid,))
                rows = cur.fetchall()

                memberships = [Membership(principal_id=pid, org_id=r["org_id"], role=r["role"], workspace_id=r["workspace_id"]) for r in rows]

                # Header is only honored for orgs the caller is actually a member of.
                org_id, workspace_id = select_tenant_context(memberships, active_org, active_ws)

                roles: List[str] = []
                permissions: Set[str] = {"tool:list", "tool:call", "upstream:read", "upstream:call"}

                for m in memberships:
                    if m.org_id == org_id:
                        if m.role not in roles:
                            roles.append(m.role)
                        cur.execute("SELECT permissions_json FROM roles WHERE role = ?", (m.role,))
                        r_row = cur.fetchone()
                        if r_row:
                            perms = json.loads(r_row["permissions_json"])
                            permissions.update(perms)

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

        return await asyncio.to_thread(_query)

    async def create_org(self, org_id: str, name: str, settings: Optional[dict] = None) -> Organization:
        now = time.time()
        settings_str = json.dumps(settings or {})

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO organizations (org_id, name, status, created_at, settings_json) VALUES (?, ?, 'active', ?, ?)",
                    (org_id, name, now, settings_str),
                )
                conn.commit()
            return Organization(org_id=org_id, name=name, status="active", created_at=now, settings=settings or {})

        return await asyncio.to_thread(_run)

    async def get_org(self, org_id: str) -> Optional[Organization]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT org_id, name, status, created_at, settings_json FROM organizations WHERE org_id = ?", (org_id,))
                r = cur.fetchone()
                if not r:
                    return None
                return Organization(
                    org_id=r["org_id"],
                    name=r["name"],
                    status=r["status"],
                    created_at=r["created_at"],
                    settings=json.loads(r["settings_json"] or "{}"),
                )

        return await asyncio.to_thread(_run)

    async def list_orgs(self, limit: int = 100, offset: int = 0) -> List[Organization]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT org_id, name, status, created_at, settings_json FROM organizations LIMIT ? OFFSET ?", (limit, offset))
                rows = cur.fetchall()
                return [
                    Organization(
                        org_id=r["org_id"],
                        name=r["name"],
                        status=r["status"],
                        created_at=r["created_at"],
                        settings=json.loads(r["settings_json"] or "{}"),
                    )
                    for r in rows
                ]

        return await asyncio.to_thread(_run)

    async def delete_org(self, org_id: str) -> bool:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM organizations WHERE org_id = ?", (org_id,))
                deleted = cur.rowcount > 0
                cur.execute("DELETE FROM memberships WHERE org_id = ?", (org_id,))
                conn.commit()
                return deleted

        return await asyncio.to_thread(_run)

    async def create_workspace(self, workspace_id: str, org_id: str, name: str) -> Workspace:
        now = time.time()

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO workspaces (workspace_id, org_id, name, created_at) VALUES (?, ?, ?, ?)",
                    (workspace_id, org_id, name, now),
                )
                conn.commit()
            return Workspace(workspace_id=workspace_id, org_id=org_id, name=name, created_at=now)

        return await asyncio.to_thread(_run)

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT workspace_id, org_id, name, created_at FROM workspaces WHERE workspace_id = ?", (workspace_id,))
                r = cur.fetchone()
                if not r:
                    return None
                return Workspace(workspace_id=r["workspace_id"], org_id=r["org_id"], name=r["name"], created_at=r["created_at"])

        return await asyncio.to_thread(_run)

    async def list_workspaces(self, org_id: str, limit: int = 100, offset: int = 0) -> List[Workspace]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT workspace_id, org_id, name, created_at FROM workspaces WHERE org_id = ? LIMIT ? OFFSET ?", (org_id, limit, offset))
                rows = cur.fetchall()
                return [Workspace(workspace_id=r["workspace_id"], org_id=r["org_id"], name=r["name"], created_at=r["created_at"]) for r in rows]

        return await asyncio.to_thread(_run)

    async def delete_workspace(self, workspace_id: str) -> bool:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted

        return await asyncio.to_thread(_run)

    async def bind_member(
        self,
        principal_id: str,
        org_id: str,
        role: str,
        workspace_id: Optional[str] = None,
    ) -> Membership:
        ws_id = workspace_id or ""

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO memberships (principal_id, org_id, role, workspace_id) VALUES (?, ?, ?, ?)",
                    (principal_id, org_id, role, ws_id),
                )
                conn.commit()
            return Membership(principal_id=principal_id, org_id=org_id, role=role, workspace_id=workspace_id)

        return await asyncio.to_thread(_run)

    async def get_memberships(self, principal_id: str) -> List[Membership]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT principal_id, org_id, role, workspace_id FROM memberships WHERE principal_id = ?", (principal_id,))
                rows = cur.fetchall()
                return [
                    Membership(
                        principal_id=r["principal_id"],
                        org_id=r["org_id"],
                        role=r["role"],
                        workspace_id=r["workspace_id"] if r["workspace_id"] else None,
                    )
                    for r in rows
                ]

        return await asyncio.to_thread(_run)

    async def list_org_members(self, org_id: str, limit: int = 100, offset: int = 0) -> List[Membership]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT principal_id, org_id, role, workspace_id FROM memberships WHERE org_id = ? LIMIT ? OFFSET ?", (org_id, limit, offset))
                rows = cur.fetchall()
                return [
                    Membership(
                        principal_id=r["principal_id"],
                        org_id=r["org_id"],
                        role=r["role"],
                        workspace_id=r["workspace_id"] if r["workspace_id"] else None,
                    )
                    for r in rows
                ]

        return await asyncio.to_thread(_run)

    async def remove_member(
        self,
        principal_id: str,
        org_id: str,
        role: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> bool:
        ws_id = workspace_id or ""

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                if role is not None:
                    cur.execute(
                        "DELETE FROM memberships WHERE principal_id = ? AND org_id = ? AND role = ? AND workspace_id = ?",
                        (principal_id, org_id, role, ws_id),
                    )
                else:
                    cur.execute("DELETE FROM memberships WHERE principal_id = ? AND org_id = ?", (principal_id, org_id))
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted

        return await asyncio.to_thread(_run)

    async def get_role(self, role_name: str) -> Optional[Role]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT role, permissions_json FROM roles WHERE role = ?", (role_name,))
                r = cur.fetchone()
                if not r:
                    return None
                return Role(role=r["role"], permissions=json.loads(r["permissions_json"]))

        return await asyncio.to_thread(_run)

    async def list_roles(self, limit: int = 100, offset: int = 0) -> List[Role]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT role, permissions_json FROM roles LIMIT ? OFFSET ?", (limit, offset))
                rows = cur.fetchall()
                return [Role(role=r["role"], permissions=json.loads(r["permissions_json"])) for r in rows]

        return await asyncio.to_thread(_run)

    async def save_role(self, role_name: str, permissions: List[str]) -> Role:
        perms_str = json.dumps(permissions)

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("INSERT OR REPLACE INTO roles (role, permissions_json) VALUES (?, ?)", (role_name, perms_str))
                conn.commit()
            return Role(role=role_name, permissions=permissions)

        return await asyncio.to_thread(_run)

    async def set_tool_ownership(
        self,
        tool_name: str,
        owner_org: str,
        owner_workspace: Optional[str] = None,
        created_by: Optional[str] = None,
        visibility: str = "private",
        tags: Optional[List[str]] = None,
    ) -> ToolOwnership:
        tags_str = json.dumps(tags or [])

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT OR REPLACE INTO tool_ownership 
                       (tool_name, owner_org, owner_workspace, created_by, visibility, tags_json, trusted_tags_json)
                       VALUES (?, ?, ?, ?, ?, ?, '[]')""",
                    (tool_name, owner_org, owner_workspace, created_by, visibility, tags_str),
                )
                conn.commit()
            return ToolOwnership(
                tool_name=tool_name,
                owner_org=owner_org,
                owner_workspace=owner_workspace,
                created_by=created_by,
                visibility=visibility,
                tags=tags or [],
            )

        return await asyncio.to_thread(_run)

    async def get_tool_ownership(self, tool_name: str) -> Optional[ToolOwnership]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT tool_name, owner_org, owner_workspace, created_by, visibility, tags_json FROM tool_ownership WHERE tool_name = ?", (tool_name,))
                r = cur.fetchone()
                if not r:
                    return None
                return ToolOwnership(
                    tool_name=r["tool_name"],
                    owner_org=r["owner_org"],
                    owner_workspace=r["owner_workspace"],
                    created_by=r["created_by"],
                    visibility=r["visibility"],
                    tags=json.loads(r["tags_json"] or "[]"),
                )

        return await asyncio.to_thread(_run)

    async def add_tool_grant(
        self,
        scope_type: str,
        scope_id: str,
        effect: str,
        match_type: str,
        match_value: str,
    ) -> ToolGrant:
        now = time.time()

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO tool_grants (scope_type, scope_id, effect, match_type, match_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (scope_type, scope_id, effect, match_type, match_value, now),
                )
                gid = cur.lastrowid
                conn.commit()
            return ToolGrant(id=gid, scope_type=scope_type, scope_id=scope_id, effect=effect, match_type=match_type, match_value=match_value, created_at=now)

        return await asyncio.to_thread(_run)

    async def list_tool_grants(self, scope_type: Optional[str] = None, scope_id: Optional[str] = None,
                               limit: int = 500, offset: int = 0) -> List[ToolGrant]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                query = "SELECT id, scope_type, scope_id, effect, match_type, match_value, created_at FROM tool_grants"
                params = []
                where_clauses = []
                if scope_type:
                    where_clauses.append("scope_type = ?")
                    params.append(scope_type)
                if scope_id:
                    where_clauses.append("scope_id = ?")
                    params.append(scope_id)
                if where_clauses:
                    query += " WHERE " + " AND ".join(where_clauses)
                query += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                cur.execute(query, params)
                rows = cur.fetchall()
                return [
                    ToolGrant(
                        id=r["id"],
                        scope_type=r["scope_type"],
                        scope_id=r["scope_id"],
                        effect=r["effect"],
                        match_type=r["match_type"],
                        match_value=r["match_value"],
                        created_at=r["created_at"],
                    )
                    for r in rows
                ]

        return await asyncio.to_thread(_run)

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
        now = time.time()

        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO audit 
                       (ts, actor_principal, issuer, org_id, action, resource, decision, detail) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now, actor_principal, issuer, org_id, action, resource, decision, detail),
                )
                aid = cur.lastrowid
                conn.commit()
            return AuditEntry(
                id=aid,
                ts=now,
                actor_principal=actor_principal,
                issuer=issuer,
                org_id=org_id,
                action=action,
                resource=resource,
                decision=decision,
                detail=detail,
            )

        return await asyncio.to_thread(_run)

    async def query_audit(self, org_id: Optional[str] = None, limit: int = 50) -> List[AuditEntry]:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                if org_id:
                    cur.execute(
                        "SELECT id, ts, actor_principal, issuer, org_id, action, resource, decision, detail FROM audit WHERE org_id = ? ORDER BY id DESC LIMIT ?",
                        (org_id, limit),
                    )
                else:
                    cur.execute(
                        "SELECT id, ts, actor_principal, issuer, org_id, action, resource, decision, detail FROM audit ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                rows = cur.fetchall()
                return [
                    AuditEntry(
                        id=r["id"],
                        ts=r["ts"],
                        actor_principal=r["actor_principal"],
                        issuer=r["issuer"],
                        org_id=r["org_id"],
                        action=r["action"],
                        resource=r["resource"],
                        decision=r["decision"],
                        detail=r["detail"] or "",
                    )
                    for r in reversed(rows)
                ]

        return await asyncio.to_thread(_run)

    # -- analytics capability (separate table, same db) --------------------
    _AN_COLS = ("ts", "tool", "ok", "duration_ms", "error_type", "error_msg",
                "org_id", "kind", "caller_fp", "result_excerpt")

    async def append_analytics(self, rows: List[dict]) -> None:
        params = [
            (r.get("ts"), r.get("tool"), 1 if r.get("ok") else 0, r.get("duration_ms"),
             r.get("error_type"), r.get("error_msg"), r.get("org_id"), r.get("kind"),
             r.get("caller_fp"), r.get("result_excerpt"))
            for r in rows
        ]

        def _run():
            with self._get_conn() as conn:
                conn.executemany(
                    f"INSERT INTO analytics_results ({','.join(self._AN_COLS)}) "
                    f"VALUES ({','.join('?' * len(self._AN_COLS))})",
                    params,
                )
                conn.commit()

        if params:
            await asyncio.to_thread(_run)

    async def query_analytics(self, *, org_id: Optional[str] = None, tool: str = "",
                              errors_only: bool = False, limit: int = 50, offset: int = 0) -> dict:
        limit = max(1, min(500, limit))

        def _run():
            where, args = [], []
            if org_id is not None:
                where.append("org_id = ?"); args.append(org_id)
            if tool:
                where.append("tool = ?"); args.append(tool)
            if errors_only:
                where.append("ok = 0")
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) AS c FROM analytics_results{clause}", args)
                total = cur.fetchone()["c"]
                cur.execute(
                    f"SELECT {','.join(self._AN_COLS)} FROM analytics_results{clause} "
                    f"ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
                rows = []
                for r in cur.fetchall():
                    d = {c: r[c] for c in self._AN_COLS}
                    d["ok"] = bool(d["ok"])
                    rows.append(d)
            nxt = offset + limit if offset + limit < total else None
            return {"total": total, "cursor": offset, "next_cursor": nxt, "results": rows}

        return await asyncio.to_thread(_run)

    async def purge_analytics(self, cutoff: float) -> int:
        def _run():
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM analytics_results WHERE ts < ?", (cutoff,))
                conn.commit()
                return cur.rowcount

        return await asyncio.to_thread(_run)
