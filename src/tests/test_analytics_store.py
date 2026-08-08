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


# -- RBAC: permissions, gating helper, content policy ----------------------

def test_new_analytics_permissions_in_role_matrix():
    from plugins.identity import BUILTIN_ROLE_PERMISSIONS as B
    assert {"analytics:admin", "analytics:read", "analytics:read_content"} <= B["platform_superadmin"]
    assert "analytics:admin" not in B["org_admin"]                    # not global dashboards
    assert {"analytics:read", "analytics:read_content"} <= B["org_admin"]
    assert B["developer"] & {"analytics:read"} == {"analytics:read"}
    assert "analytics:read_content" not in B["developer"]             # metadata only
    assert not (B["agent_consumer"] & {"analytics:read", "analytics:admin"})


def test_require_permission_helper():
    from types import SimpleNamespace
    from plugins.security import require_permission

    def _req(admin_token="", principal=None, headers=None):
        return SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(admin_token=admin_token)),
            headers=headers or {}, query_params={},
            state=SimpleNamespace(principal=principal))

    class P:
        def __init__(self, subject, perms):
            self.subject, self.permissions = subject, set(perms)

    # static admin token always passes
    r = _req(admin_token="sek", headers={"authorization": "Bearer sek"})
    assert asyncio.run(require_permission(r, "analytics:admin")) is None
    # principal holding the permission passes
    r = _req(principal=P("alice", {"analytics:read"}))
    assert asyncio.run(require_permission(r, "analytics:read")) is None
    # authenticated but missing -> 403
    r = _req(principal=P("bob", {"tool:call"}))
    resp = asyncio.run(require_permission(r, "analytics:read"))
    assert resp is not None and resp.status_code == 403
    # anonymous -> 401
    r = _req(principal=P("anonymous", set()))
    resp = asyncio.run(require_permission(r, "analytics:read"))
    assert resp is not None and resp.status_code == 401


def test_content_policy_strips_bodies_without_permission():
    from plugins.analytics.routes import _apply_content_policy
    data = {"results": [{"tool": "t", "result_excerpt": "secret-ish"}]}
    stripped = _apply_content_policy({"results": [dict(r) for r in data["results"]]}, allowed=False)
    assert "result_excerpt" not in stripped["results"][0]
    kept = _apply_content_policy({"results": [dict(r) for r in data["results"]]}, allowed=True)
    assert kept["results"][0]["result_excerpt"] == "secret-ish"


# -- Phase E: histogram buckets, error taxonomy, self-metrics --------------

def test_legacy_metrics_histogram_render():
    from legacy_metrics import LegacyMetrics
    m = LegacyMetrics()
    m.declare_histogram("lat", (0.01, 0.1, 1.0), "latency")
    for v in (0.005, 0.05, 0.5, 5.0):    # one in each bucket incl. overflow
        m.observe("lat", v, tool="t")
    out = m.render()
    assert "# TYPE lat histogram" in out
    # cumulative buckets: le=0.01 ->1, le=0.1 ->2, le=1 ->3, +Inf ->4
    assert 'lat_bucket{tool="t",le="0.01"} 1' in out
    assert 'lat_bucket{tool="t",le="0.1"} 2' in out
    assert 'lat_bucket{tool="t",le="1"} 3' in out
    assert 'lat_bucket{tool="t",le="+Inf"} 4' in out
    assert 'lat_count{tool="t"} 4' in out


def test_metrics_histogram_quantile_derivable():
    # a TSDB computes p95 from the bucket series; verify the cumulative counts
    # are monotonic and the +Inf bucket equals the total (the histogram invariant)
    from legacy_metrics import LegacyMetrics
    m = LegacyMetrics()
    m.declare_histogram("d", (0.01, 0.1, 1.0), "")
    for _ in range(90):
        m.observe("d", 0.05)             # ~50ms
    for _ in range(10):
        m.observe("d", 2.0)              # slow tail
    out = m.render()
    lines = [l for l in out.splitlines() if l.startswith("d_bucket")]
    counts = [int(l.split()[-1]) for l in lines]
    assert counts == sorted(counts)      # monotonic non-decreasing
    assert counts[-1] == 100             # +Inf == total observations


# -- production hardening: sink re-buffers on store failure (F1/F2) ---------

def test_tenancy_sink_rebuffers_on_store_failure():
    from plugins.analytics.sink import TenancyBackedSink

    class FlakyStore:
        def __init__(self):
            self.fail = True
            self.saved = []
        async def append_analytics(self, rows):
            if self.fail:
                raise IOError("db down")
            self.saved.extend(rows)

    async def run():
        store = FlakyStore()
        sink = TenancyBackedSink(store, max_results=100)
        for i in range(3):
            sink.append({"ts": 1.0, "tool": "t", "ok": False, "n": i})
        # first flush fails -> rows must be re-buffered, not lost, and raise
        try:
            await sink.aflush()
            assert False, "expected the store failure to propagate"
        except IOError:
            pass
        # recover: next flush persists the SAME rows (nothing was dropped)
        store.fail = False
        await sink.aflush()
        assert len(store.saved) == 3
        assert sink.dropped == 0
    asyncio.run(run())


def test_tenancy_sink_buffer_is_bounded():
    from plugins.analytics.sink import TenancyBackedSink

    class DeadStore:
        async def append_analytics(self, rows):
            raise IOError("down")

    async def run():
        sink = TenancyBackedSink(DeadStore(), max_results=10, max_buffer=50)
        for i in range(200):                 # flood far past the cap
            sink.append({"ts": 1.0, "tool": "t", "ok": True, "n": i})
        assert len(sink._buffer) <= 50       # bounded, no unbounded growth
        assert sink.dropped > 0              # overflow was counted, not silent
    asyncio.run(run())
