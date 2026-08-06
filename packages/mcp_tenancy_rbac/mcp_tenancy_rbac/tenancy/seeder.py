"""First-start seeder for TenancyStore (Phase 1).
Seeds built-in roles, default organization & workspace, superadmin identity, and tags platform tools.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from plugins.identity import BUILTIN_ROLE_PERMISSIONS

if TYPE_CHECKING:
    from .base import TenancyStore

log = logging.getLogger("MCP_logger")

SEED_LOCK = asyncio.Lock()

# Seed the store from the canonical role->permission matrix (§5) defined in
# plugins.identity, so the seeded rows and the in-code fallback never drift (H1).
BUILTIN_ROLES = {role: sorted(perms) for role, perms in BUILTIN_ROLE_PERMISSIONS.items()}


async def seed_tenancy_store_if_empty(store: TenancyStore, ctx) -> None:
    """Idempotently seed roles, default organization, default workspace, and superadmin binding."""
    if not getattr(ctx, "tenancy_seed", True):
        return

    # NOTE: SEED_LOCK serializes concurrent seeding within one process. It does
    # NOT cover multi-replica cold starts (§21.1); the store writes below are
    # idempotent create-if-absent, so a lost cross-process race degrades to a
    # no-op. A backend-level lock (pg advisory / Mongo sentinel) is future work.
    async with SEED_LOCK:
        # 1. Seed built-in roles; optionally reconcile drifted perms (§21.5).
        reconcile = getattr(ctx, "tenancy_reconcile_roles", False)
        for role_name, perms in BUILTIN_ROLES.items():
            existing = await store.get_role(role_name)
            if not existing:
                await store.save_role(role_name, perms)
                log.info("Seeded built-in role: %s", role_name)
            elif reconcile and set(existing.permissions) != set(perms):
                await store.save_role(role_name, perms)
                log.info("Reconciled built-in role perms: %s", role_name)

        # 2. Seed Default Org & Workspace
        default_org_id = getattr(ctx, "default_org", "default") or "default"
        org = await store.get_org(default_org_id)
        if not org:
            await store.create_org(default_org_id, name="Default Organization")
            log.info("Seeded default organization: %s", default_org_id)

        ws = await store.get_workspace("default")
        if not ws:
            await store.create_workspace("default", org_id=default_org_id, name="Default Workspace")
            log.info("Seeded default workspace in org: %s", default_org_id)

        # 3. Superadmin bootstrap (M5). We do NOT bind a principal here: at seed
        # time only the email is known, but principals are keyed on (issuer, JWT
        # subject) — the subject is the IdP's user id, not the email, so a binding
        # derived from the email could never match resolve_principal() at runtime.
        # Superadmin is instead granted by the identity middleware when the
        # verified token's email claim equals MCP_SUPERADMIN_EMAIL, and via the
        # MCP_ADMIN_TOKEN bootstrap. (No hardcoded issuer default here either.)
        superadmin_email = getattr(ctx, "superadmin_email", "") or ""
        if superadmin_email:
            log.info("Superadmin bootstrap: email-claim match for %s (granted at auth time)", superadmin_email)

        # 4. Tag existing platform tools in tools_dir as public
        tools_dir = getattr(ctx, "tools_dir", None)
        if tools_dir and tools_dir.exists():
            for p in tools_dir.glob("*.py"):
                if p.name.startswith(("_", ".")):
                    continue
                tool_name = p.stem
                ownership = await store.get_tool_ownership(tool_name)
                if not ownership:
                    await store.set_tool_ownership(
                        tool_name=tool_name,
                        owner_org=default_org_id,
                        owner_workspace="default",
                        visibility="public",
                        tags=["platform"],
                    )
