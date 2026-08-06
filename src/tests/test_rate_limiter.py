"""Unit tests for RateLimitEnforcer, tenant isolation, and eviction (H3 fix)."""
from __future__ import annotations

import pytest

from src.plugins.reliability import RateLimitConfig, RateLimitEnforcer, RateLimitExceededError


@pytest.mark.anyio
async def test_rate_limit_enforcer_sliding_window():
    config = RateLimitConfig(max_requests_per_minute=2, on_exceed="reject")
    enforcer = RateLimitEnforcer(config)

    # 1. First 2 requests allowed
    ok1, rem1, _ = await enforcer.check_rate_limit("tenant_1")
    assert ok1 is True
    assert rem1 == 1

    ok2, rem2, _ = await enforcer.check_rate_limit("tenant_1")
    assert ok2 is True
    assert rem2 == 0

    # 2. 3rd request rejected
    with pytest.raises(RateLimitExceededError):
        await enforcer.check_rate_limit("tenant_1")

    # 3. Tenant 2 has independent bucket
    ok_t2, rem_t2, _ = await enforcer.check_rate_limit("tenant_2")
    assert ok_t2 is True
    assert rem_t2 == 1


@pytest.mark.anyio
async def test_stale_tenant_eviction():
    config = RateLimitConfig(max_requests_per_minute=10)
    enforcer = RateLimitEnforcer(config)

    await enforcer.check_rate_limit("tenant_idle")
    assert "tenant_idle" in enforcer._window

    # Evict with 0 sec idle threshold
    evicted = await enforcer.evict_stale_tenants(max_idle_sec=0.0)
    assert evicted == 1
    assert "tenant_idle" not in enforcer._window
