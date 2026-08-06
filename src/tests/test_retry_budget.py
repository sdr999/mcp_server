"""Unit tests for RetryBudget."""
from __future__ import annotations

from src.plugins.reliability import RetryBudget, RetryBudgetConfig


def test_retry_budget_enforcement():
    config = RetryBudgetConfig(max_retry_ratio=0.2, window_sec=60.0, min_retries_per_window=2)
    budget = RetryBudget(config)

    # Initial state allows retry
    assert budget.can_retry() is True

    # Record normal calls
    for _ in range(10):
        budget.record_attempt(is_retry=False)

    # 1st and 2nd retries allowed (under min_retries_per_window)
    budget.record_attempt(is_retry=True)
    assert budget.can_retry() is True

    budget.record_attempt(is_retry=True)
    assert budget.can_retry() is True

    # 3rd retry exceeds max_retry_ratio (3 retries out of 13 calls = 23% > 20%)
    budget.record_attempt(is_retry=True)
    assert budget.can_retry() is False
