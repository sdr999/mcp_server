"""First-start seeder for TenancyStore (Phase 1).
Seeds built-in roles, default organization & workspace, superadmin identity, and tags platform tools.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from plugins.identity import BUILTIN_ROLE_PERMISSIONS, derive_principal_id

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

    async with SEED_LOCK:
        # 1. Seed Built-in Roles
        for role_name, perms in BUILTIN_ROLES.items():
            existing = await store.get_role(role_name)
            if not existing:
                await store.save_role(role_name, perms)
                log.info("Seeded built-in role: %s", role_name)

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

        # 3. Bind Superadmin Principal if configured
        superadmin_email = getattr(ctx, "superadmin_email", "") or ""
        jwt_issuer = getattr(ctx, "jwt_issuer", "") or "https://bplpycqmizyztxqwglgb.supabase.co/auth/v1"
        if superadmin_email:
            pid = derive_principal_id(jwt_issuer, superadmin_email)
            await store.bind_member(pid, org_id=default_org_id, role="platform_superadmin")
            log.info("Seeded superadmin principal for email %s -> %s", superadmin_email, pid[:12])

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
