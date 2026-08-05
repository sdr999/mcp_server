"""Pluggable TenancyStore package and factory (Phase 1)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .base import TenancyStore
from .json_store import JsonTenancyStore
from .memory import MemoryTenancyStore
from .mongo_store import MongoTenancyStore, HAS_MOTOR
from .sqlite_store import SqliteTenancyStore

log = logging.getLogger("MCP_logger")


def create_tenancy_store(ctx) -> TenancyStore:
    """Factory function: Instantiate the configured TenancyStore backend.
    MCP_TENANCY_STORE choices: sqlite (default) | mongodb | memory | json.
    """
    store_type = getattr(ctx, "tenancy_store", "sqlite").lower()

    if store_type == "memory":
        log.info("Instantiating MemoryTenancyStore backend")
        return MemoryTenancyStore()

    elif store_type == "json":
        json_path = getattr(ctx, "tenancy_db_path", None) or (ctx.base_dir / "data" / "tenancy.json")
        log.info("Instantiating JsonTenancyStore backend at %s", json_path)
        return JsonTenancyStore(json_path)

    elif store_type == "mongodb":
        dsn = getattr(ctx, "tenancy_dsn", "") or "mongodb://localhost:27017"
        db_name = getattr(ctx, "tenancy_db_name", "") or "mcp_tenancy"
        log.info("Instantiating MongoTenancyStore backend at %s / db=%s", dsn, db_name)
        return MongoTenancyStore(dsn, db_name=db_name)

    elif store_type == "sqlite":
        db_path = getattr(ctx, "tenancy_db_path", None) or (ctx.base_dir / "data" / "tenancy.db")
        log.info("Instantiating SqliteTenancyStore backend at %s", db_path)
        return SqliteTenancyStore(db_path)

    else:
        log.warning("Unknown MCP_TENANCY_STORE %r; falling back to SqliteTenancyStore", store_type)
        db_path = ctx.base_dir / "data" / "tenancy.db"
        return SqliteTenancyStore(db_path)


__all__ = [
    "TenancyStore",
    "MemoryTenancyStore",
    "JsonTenancyStore",
    "SqliteTenancyStore",
    "MongoTenancyStore",
    "create_tenancy_store",
]
