"""Pluggable TenancyStore package, backend registry, and factory (Phase 1, §20)."""
from __future__ import annotations

import importlib
import logging
from typing import Callable, Dict

from .base import TenancyStore
from .json_store import JsonTenancyStore
from .memory import MemoryTenancyStore
from .mongo_store import MongoTenancyStore, HAS_MOTOR
from .sqlite_store import SqliteTenancyStore

log = logging.getLogger("MCP_logger")

# name -> constructor(ctx) -> TenancyStore. Backends register themselves below;
# a deployment can add its own (Redis, DynamoDB, a hosted API) via a
# "module.path:Factory" spec in MCP_TENANCY_STORE, without patching the server.
_BACKENDS: Dict[str, Callable[[object], TenancyStore]] = {}


def register_backend(name: str, ctor: Callable[[object], TenancyStore]) -> None:
    _BACKENDS[name.lower()] = ctor


def _sqlite(ctx) -> TenancyStore:
    db_path = getattr(ctx, "tenancy_db_path", None) or (ctx.base_dir / "data" / "tenancy.db")
    return SqliteTenancyStore(db_path)


def _json(ctx) -> TenancyStore:
    json_path = getattr(ctx, "tenancy_db_path", None) or (ctx.base_dir / "data" / "tenancy.json")
    return JsonTenancyStore(json_path)


def _memory(ctx) -> TenancyStore:
    return MemoryTenancyStore()


def _mongodb(ctx) -> TenancyStore:
    dsn = getattr(ctx, "tenancy_dsn", "") or "mongodb://localhost:27017"
    db_name = getattr(ctx, "tenancy_db_name", "") or "mcp_tenancy"
    return MongoTenancyStore(dsn, db_name=db_name)


register_backend("memory", _memory)
register_backend("json", _json)
register_backend("sqlite", _sqlite)
register_backend("mongodb", _mongodb)


def _load_dotted(spec: str) -> Callable[[object], TenancyStore]:
    """Resolve a 'package.module:Factory' spec into a callable(ctx)->store."""
    module_path, _, attr = spec.partition(":")
    if not module_path or not attr:
        raise RuntimeError(f"MCP_TENANCY_STORE custom spec must be 'module.path:Factory', got {spec!r}")
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(f"could not load custom tenancy backend {spec!r}: {exc}") from exc


def create_tenancy_store(ctx) -> TenancyStore:
    """Instantiate the configured TenancyStore backend (§20.2).

    ``MCP_TENANCY_STORE`` selects a registered backend (memory | json | sqlite |
    mongodb) or a custom ``module.path:Factory``. An unknown value is a
    configuration error — we fail fast rather than silently falling back.
    """
    spec = (getattr(ctx, "tenancy_store", "sqlite") or "sqlite").strip()
    if ":" in spec:
        ctor = _load_dotted(spec)
    else:
        ctor = _BACKENDS.get(spec.lower())
        if ctor is None:
            raise RuntimeError(
                f"unknown MCP_TENANCY_STORE={spec!r}; known backends: {sorted(_BACKENDS)} "
                f"(or a 'module.path:Factory' spec)"
            )
    store = ctor(ctx)
    log.info("Instantiated tenancy backend %r -> %s", spec, type(store).__name__)
    return store


__all__ = [
    "TenancyStore",
    "MemoryTenancyStore",
    "JsonTenancyStore",
    "SqliteTenancyStore",
    "MongoTenancyStore",
    "register_backend",
    "create_tenancy_store",
]
