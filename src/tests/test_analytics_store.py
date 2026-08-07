"""Phase F: analytics persistence reusing the tenancy store (same DB, separate
`analytics_results` collection/table) with org-scoped reads."""
from __future__ import annotations

import asyncio
import time

import pytest

from plugins import observer
from plugins.observer import ToolEvent
from plugins.analytics.engine import AnalyticsEngine, AnalyticsConfig
from plugins.tenancy.memory import MemoryTenancyStore
from pathlib import Path
from plugins.tenancy.sqlite_store import SqliteTenancyStore


@pytest.fixture(autouse=True)
def _clean_observers():
    observer.clear()
    yield
    observer.clear()


def _rows():
    now = time.time()
    return [
        {"ts": now, "tool": "add", "ok": True, "duration_ms": 1.0, "org_id": "acme", "kind": "service", "caller_fp": "fp1"},
        {"ts": now, "tool": "boom", "ok": False, "duration_ms": 2.0, "error_type": "RuntimeError", "error_msg": "x", "org_id": "acme", "kind": "service", "caller_fp": "fp1"},
        {"ts": now, "tool": "add", "ok": True, "duration_ms": 1.5, "org_id": "globex", "kind": "user", "caller_fp": "fp2"},
    ]


# -- store capability: same DB, separate collection ------------------------

def test_memory_store_analytics_capability():
    async def run():
        s = MemoryTenancyStore()
        await s.append_analytics(_rows())
        allrows = await s.query_analytics()
        assert allrows["total"] == 3
        acme = await s.query_analytics(org_id="acme")
        assert acme["total"] == 2 and all(r["org_id"] == "acme" for r in acme["results"])
        errs = await s.query_analytics(errors_only=True)
        assert errs["total"] == 1 and errs["results"][0]["tool"] == "boom"
    asyncio.run(run())


def test_sqlite_store_analytics_capability(tmp_path):
    async def run():
        s = SqliteTenancyStore(tmp_path / "tenancy.db")
        await s.init_db()                                  # creates analytics_results table
        await s.append_analytics(_rows())
        allrows = await s.query_analytics()
        assert allrows["total"] == 3
        # org isolation
        acme = await s.query_analytics(org_id="acme")
        assert acme["total"] == 2 and {r["org_id"] for r in acme["results"]} == {"acme"}
        globex = await s.query_analytics(org_id="globex")
        assert globex["total"] == 1
        # errors + pagination
        assert (await s.query_analytics(errors_only=True))["total"] == 1
        pg = await s.query_analytics(limit=2, offset=0)
        assert len(pg["results"]) == 2 and pg["next_cursor"] == 2
    asyncio.run(run())


def test_sqlite_analytics_is_separate_from_audit_table(tmp_path):
    async def run():
        s = SqliteTenancyStore(tmp_path / "t.db")
        await s.init_db()
        await s.append_analytics(_rows())
        audit = await s.query_audit()          # audit table must stay empty
        assert audit == []
        assert (await s.query_analytics())["total"] == 3
    asyncio.run(run())


def test_sqlite_purge_analytics(tmp_path):
    async def run():
        s = SqliteTenancyStore(tmp_path / "t.db")
        await s.init_db()
        old = time.time() - 10_000
        await s.append_analytics([{"ts": old, "tool": "old", "ok": True, "org_id": "acme"}])
        await s.append_analytics(_rows())
        removed = await s.purge_analytics(cutoff=time.time() - 5_000)
        assert removed == 1
        assert (await s.query_analytics())["total"] == 3
    asyncio.run(run())


# -- engine integration: attach store, durable write, org-scoped read ------

def test_engine_persists_to_tenancy_store_sqlite(tmp_path):
    async def run():
        store = SqliteTenancyStore(tmp_path / "t.db")
        await store.init_db()
        eng = AnalyticsEngine(AnalyticsConfig(sink="tenancy", min_samples=1))
        eng.attach_store(store)
        eng.subscribe()
        # attributed errors + successes via the seam
        class _P:
            principal_id, subject, org_id, kind, workspace_id = "pid", "alice", "acme", "service", "default"
        for _ in range(3):
            observer.emit(ToolEvent(tool="boom", duration=0.01, ok=False,
                                    error=RuntimeError("x"), principal=_P(), ts=time.time()))
        eng._flush_once()          # rollups + buffer
        await eng._flush_store()   # durable batch-write to sqlite
        # read back org-scoped from the DB
        res = await eng.query_results(org_id="acme", errors_only=True)
        assert res["total"] == 3 and all(r["tool"] == "boom" for r in res["results"])
        # a different org sees nothing
        assert (await eng.query_results(org_id="other"))["total"] == 0
    asyncio.run(run())
