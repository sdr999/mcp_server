"""Tests for the analytics plugin: seam decoupling, rollups, failure isolation,
backpressure, bounded memory, and lifecycle."""
from __future__ import annotations

import asyncio
import time

import pytest

from plugins import observer
from plugins.observer import ToolEvent, emit
from plugins.analytics.engine import (
    AnalyticsEngine, AnalyticsConfig, _percentile, _bucket_index, _NUM_BUCKETS,
)
from plugins.analytics.bounded import LRUMap, HyperLogLog


@pytest.fixture(autouse=True)
def _clean_observers():
    observer.clear()
    yield
    observer.clear()


def _ev(tool="t", ok=True, dur=0.01, err=None, principal=None, ts=None):
    return ToolEvent(tool=tool, duration=dur, ok=ok, error=err,
                     principal=principal, ts=ts or time.time())


# -- seam ------------------------------------------------------------------

def test_emit_is_noop_without_subscribers():
    # must not raise and must do nothing
    emit(_ev())
    assert observer.observer_count() == 0


def test_subscribe_is_idempotent():
    eng = AnalyticsEngine()
    eng.subscribe()
    eng.subscribe()
    assert observer.observer_count() == 1


def test_emit_swallows_subscriber_errors():
    def boom(_):
        raise RuntimeError("nope")
    observer.subscribe(boom)
    emit(_ev())  # must not propagate


def test_wrapper_never_imports_analytics():
    import plugins.tool_loader as tl
    src = __import__("inspect").getsource(tl)
    assert "import analytics" not in src and "from .analytics" not in src


# -- rollups ---------------------------------------------------------------

def _drain(eng):
    eng._flush_once()


def test_basic_rollup_calls_errors_latency():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=1))
    eng.subscribe()
    for _ in range(8):
        emit(_ev("adder", ok=True, dur=0.010))
    for _ in range(2):
        emit(_ev("adder", ok=False, dur=0.020, err=ValueError("bad")))
    _drain(eng)
    stats = eng.get_stats()
    t = stats["tools"]["adder"]
    assert t["calls"] == 10
    assert t["errors"] == 2
    assert t["success_rate_percent"] == 80.0
    assert 10.0 <= t["avg_latency_ms"] <= 20.0
    assert stats["total_calls"] == 10


def test_error_streak_and_leaderboards():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=1))
    eng.subscribe()
    for _ in range(5):
        emit(_ev("flaky", ok=False, dur=0.01, err=RuntimeError("x")))
    emit(_ev("solid", ok=True, dur=0.05))
    _drain(eng)
    stats = eng.get_stats()
    assert stats["tools"]["flaky"]["error_streak"] == 5
    names = [x["name"] for x in stats["leaderboards"]["flakiest"]]
    assert "flaky" in names


def test_timeseries_sparkline():
    eng = AnalyticsEngine()
    eng.subscribe()
    for _ in range(3):
        emit(_ev("weather", ok=True, dur=0.01))
    _drain(eng)
    ts = eng.get_timeseries("weather")
    assert ts["n"] == 3
    assert sum(b["calls"] for b in ts["buckets"]) == 3


def test_min_samples_suppresses_slowest():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=20))
    eng.subscribe()
    for _ in range(3):
        emit(_ev("rare", ok=True, dur=0.5))
    _drain(eng)
    slow = [x["name"] for x in eng.get_stats()["leaderboards"]["slowest"]]
    assert "rare" not in slow  # below min_samples -> not ranked


# -- Phase B: percentiles + heatmap ----------------------------------------

def test_percentile_helper_from_buckets():
    hist = [0] * _NUM_BUCKETS
    # 90 calls at ~5ms, 10 calls at ~1000ms
    hist[_bucket_index(5)] = 90
    hist[_bucket_index(1000)] = 10
    assert _percentile(hist, 0.50) <= 5
    assert _percentile(hist, 0.99) >= 500
    assert _percentile([0] * _NUM_BUCKETS, 0.95) == 0.0


def test_tool_percentiles_gated_by_min_samples():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=20))
    eng.subscribe()
    for _ in range(5):                        # below min_samples
        emit(_ev("rare", ok=True, dur=0.01))
    _drain(eng)
    assert eng.get_stats()["tools"]["rare"]["p95_ms"] is None
    for _ in range(30):                       # now above
        emit(_ev("rare", ok=True, dur=0.01))
    _drain(eng)
    assert eng.get_stats()["tools"]["rare"]["p95_ms"] is not None


def test_hour_heatmap_present():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=1))
    eng.subscribe()
    emit(_ev("t", ok=True, dur=0.01))
    _drain(eng)
    hm = eng.get_stats()["hour_heatmap"]
    assert len(hm) == 24 and sum(hm) == 1


# -- backpressure: errors are never dropped for successes ------------------

def test_error_lane_reserved_under_success_flood():
    cfg = AnalyticsConfig(success_lane=5, error_lane=100)
    eng = AnalyticsEngine(cfg)
    eng.subscribe()
    for _ in range(50):                       # flood successes (lane=5)
        emit(_ev("t", ok=True, dur=0.001))
    for _ in range(10):                       # errors must all survive
        emit(_ev("t", ok=False, dur=0.001, err=ValueError("e")))
    assert eng.dropped_success > 0            # successes were dropped
    assert eng.dropped_error == 0            # errors were not
    _drain(eng)
    assert eng.get_stats()["tools"]["t"]["errors"] == 10


# -- Phase C: durable sink, redaction, HMAC fingerprint --------------------

def test_redaction_nested_and_value_patterns():
    from plugins.analytics.sink import redact
    keys = {"password", "token"}
    out = redact({
        "user": "alice",
        "password": "hunter2",
        "nested": {"token": "abc", "note": "Bearer sk-ABCDEFGHIJKLMNOP12345"},
        "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
    }, keys)
    assert out["password"] == "***"
    assert out["nested"]["token"] == "***"
    assert "***" in out["nested"]["note"]     # value-pattern redaction
    assert "***" in out["jwt"]
    assert out["user"] == "alice"


def test_hmac_fingerprint_keyed_and_stable():
    from plugins.analytics.sink import token_fingerprint
    s1, s2 = b"secret-1", b"secret-2"
    fp = token_fingerprint("principal-xyz", s1)
    assert fp == token_fingerprint("principal-xyz", s1)   # stable per key
    assert fp != token_fingerprint("principal-xyz", s2)   # keyed -> differs by secret
    assert token_fingerprint(None, s1) is None
    assert len(fp) == 12


def test_jsonl_sink_durability_and_query(tmp_path):
    from plugins.analytics.sink import JsonlResultSink
    p = tmp_path / "results.jsonl"
    sink = JsonlResultSink(str(p), max_results=100, ttl_seconds=3600)
    for i in range(5):
        sink.append({"ts": time.time(), "tool": "t", "ok": i % 2 == 0})
    assert p.exists() and len(p.read_text().strip().splitlines()) == 5   # durable
    page = sink.query(errors_only=True)
    assert page["total"] == 2 and all(not r["ok"] for r in page["results"])


def test_engine_capture_content_off_by_default():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=1))
    eng.subscribe()
    emit(_ev("t", ok=False, dur=0.01, err=ValueError("boom")))
    _drain(eng)
    rows = eng.get_results()["results"]
    assert len(rows) == 1
    assert "result_excerpt" not in rows[0]      # bodies OFF by default
    assert rows[0]["error_type"] == "ValueError"  # metadata still captured
    assert "caller_fp" in rows[0]


def test_results_pagination():
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=1))
    eng.subscribe()
    for _ in range(10):
        emit(_ev("t", ok=False, dur=0.01, err=RuntimeError("x")))
    _drain(eng)
    p1 = eng.get_results(limit=4, cursor=0)
    assert len(p1["results"]) == 4 and p1["next_cursor"] == 4
    p3 = eng.get_results(limit=4, cursor=8)
    assert len(p3["results"]) == 2 and p3["next_cursor"] is None


# -- failure isolation -----------------------------------------------------

def test_sink_failure_never_breaks_and_trips_breaker(monkeypatch):
    eng = AnalyticsEngine(AnalyticsConfig(min_samples=1))
    eng.subscribe()

    def boom(_ev, _ms):
        raise IOError("disk full")
    monkeypatch.setattr(eng, "_capture_result", boom)
    # emit errors -> _apply calls _capture_result which raises; must be swallowed
    for _ in range(10):
        emit(_ev("t", ok=False, dur=0.01, err=RuntimeError("x")))
    _drain(eng)  # must not raise
    # rollup still recorded despite sink failure
    assert eng.get_stats()["tools"]["t"]["errors"] == 10


def test_control_kill_switch():
    eng = AnalyticsEngine()
    eng.subscribe()
    eng.set_control(enabled=False)
    emit(_ev("t", ok=True, dur=0.01))
    _drain(eng)
    assert eng.get_stats()["total_calls"] == 0  # disabled -> not recorded


# -- bounded memory --------------------------------------------------------

def test_lru_map_evicts():
    m = LRUMap(capacity=3, factory=lambda: {"n": 0})
    for k in "abcd":
        m.get_or_create(k)
    assert len(m) == 3
    assert m.evictions == 1
    assert m.peek("a") is None       # coldest evicted


def test_max_tools_bounded():
    eng = AnalyticsEngine(AnalyticsConfig(max_tools=3))
    eng.subscribe()
    for i in range(10):
        emit(_ev(f"tool{i}", ok=True, dur=0.01))
    _drain(eng)
    assert eng.get_stats()["tools_tracked"] <= 3


def test_hyperloglog_approximates():
    hll = HyperLogLog(p=10)
    for i in range(1000):
        hll.add(f"caller-{i}")
    est = hll.count()
    assert 850 <= est <= 1150        # within ~15% for a tiny sketch


# -- lifecycle -------------------------------------------------------------

# -- R1 spike: does the authenticated principal reach the tool wrapper? -----

def test_r1_identity_reaches_wrapper_http(tmp_path):
    """Phase-0 gate: capture the principal the wrapper observes on the HTTP
    /tools/{name}/call path. Determines whether caller-dimension metrics are
    viable (Phase D) or need explicit principal threading."""
    import sys
    from pathlib import Path
    from plugins.app import build_app
    from plugins.config import AppContext
    from starlette.testclient import TestClient

    SRC = str(Path(__file__).resolve().parent.parent)
    d = tmp_path / "an_pkg"
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "echo.py").write_text("def echo(msg: str) -> str:\n    return msg\n")
    sys.path.insert(0, SRC)
    sys.path.insert(0, str(tmp_path))
    ctx = AppContext(
        base_dir=Path(SRC), tools_dir=d, env={}, auth_type="none",
        api_key_header="authorization", api_key_value="", jwks_url="",
        jwt_issuer=None, jwt_audience=None, jwt_required_scopes=None, host="127.0.0.1", port=0,
        import_timeout=30, metrics_enabled=True, sandbox=False, sandbox_timeout=30,
        sandbox_mem_mb=0, sandbox_cpu_sec=0, admin_token="mysecretadmin",
        require_signed=False, manifest_name="tools.manifest.json", signing_key=None,
        onboard_enabled=True, onboard_autoinstall=True, onboard_network_check=False,
        onboard_network_timeout=3.0, onboard_install_timeout=30.0,
        onboard_allowlist_path=None, onboard_denylist_path=None,
    )

    seen = {}
    observer.subscribe(lambda ev: seen.update(principal=ev.principal))

    app, _ = build_app(ctx)
    with TestClient(app) as client:
        for _ in range(50):
            if client.get("/readyz").status_code == 200:
                break
            time.sleep(0.1)
        r = client.post("/tools/echo/call", json={"arguments": {"msg": "hi"}},
                        headers={"Authorization": "Bearer mysecretadmin"})
        assert r.status_code == 200

    p = seen.get("principal")
    assert p is not None, "wrapper saw no principal at all"
    assert getattr(p, "subject", None) == "admin-token", (
        f"identity did not propagate to wrapper: saw subject={getattr(p,'subject',None)!r}")


def test_start_and_stop_drain():
    async def run():
        eng = AnalyticsEngine(AnalyticsConfig(drain_interval=0.02, min_samples=1))
        eng.subscribe()
        eng.start()
        for _ in range(5):
            emit(_ev("t", ok=False, dur=0.01, err=ValueError("e")))
        await asyncio.sleep(0.08)              # let the drain task run
        await eng.stop(timeout=1.0)            # flush-and-cancel
        assert eng.get_stats()["tools"]["t"]["errors"] == 5
    asyncio.run(run())
