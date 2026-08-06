"""Unit tests for 3-state CircuitBreaker."""
from __future__ import annotations

import pytest

from src.plugins.reliability import CircuitBreaker, CircuitBreakerOpenError, CircuitState


@pytest.mark.anyio
async def test_circuit_breaker_transitions():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, success_threshold=1, name="test_cb")
    assert cb.state == CircuitState.CLOSED
    assert cb.is_closed is True

    # 1. First failure — stays CLOSED
    async def failing_fn():
        raise ValueError("Backend down")

    with pytest.raises(ValueError):
        await cb.call(failing_fn)
    assert cb.state == CircuitState.CLOSED

    # 2. Second failure — trips to OPEN
    with pytest.raises(ValueError):
        await cb.call(failing_fn)
    assert cb.state == CircuitState.OPEN

    # 3. Third call while OPEN — fails fast with CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(failing_fn)

    # 4. Wait for recovery timeout -> probe call in HALF_OPEN
    import anyio
    await anyio.sleep(0.15)

    async def successful_fn():
        return "ok"

    res = await cb.call(successful_fn)
    assert res == "ok"
    assert cb.state == CircuitState.CLOSED  # Recovered back to CLOSED
