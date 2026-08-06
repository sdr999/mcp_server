"""Resilience and fault-tolerance engine for MCP Server Gateway.

Includes:
- 3-state Circuit Breaker (Horus resilience.py pattern)
- Sliding-window per-tenant Rate Limiter with automatic eviction (Horus BudgetEnforcer pattern)
- OTel-native Retry Budget
- ReliabilityMiddleware for request interception
"""
from __future__ import annotations

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitBreakerRegistry, CircuitState
from .rate_limiter import RateLimitConfig, RateLimitEnforcer, RateLimiterRegistry, RateLimitExceededError
from .retry_budget import RetryBudget, RetryBudgetConfig
from .middleware import ReliabilityMiddleware

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
    "CircuitBreakerRegistry",
    "RateLimitConfig",
    "RateLimitEnforcer",
    "RateLimiterRegistry",
    "RateLimitExceededError",
    "RetryBudget",
    "RetryBudgetConfig",
    "ReliabilityMiddleware",
]
