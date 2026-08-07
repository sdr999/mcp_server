"""Token consumption and USD cost tracking engine."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Dict, Any, Optional

log = logging.getLogger("MCP_logger")

# Default pricing rate table (USD per 1,000 tokens)
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"prompt": 0.0025, "completion": 0.0100},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "claude-3-5-sonnet": {"prompt": 0.0030, "completion": 0.0150},
    "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125},
    "default": {"prompt": 0.0010, "completion": 0.0020},
}


class CostTracker:
    """Thread-safe multi-tenant token consumption and financial spend tracker."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tenant_spend: Dict[str, float] = defaultdict(float)
        self._tenant_tokens: Dict[str, Dict[str, int]] = defaultdict(lambda: {"prompt": 0, "completion": 0, "total": 0})
        self._total_spend: float = 0.0
        self._total_tokens: int = 0

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int, model: str = "default") -> float:
        rates = MODEL_PRICING.get(model.lower(), MODEL_PRICING["default"])
        prompt_cost = (prompt_tokens / 1000.0) * rates["prompt"]
        completion_cost = (completion_tokens / 1000.0) * rates["completion"]
        return round(prompt_cost + completion_cost, 6)

    def record_usage(self, tenant_id: str, prompt_tokens: int, completion_tokens: int, model: str = "default") -> float:
        cost = self.calculate_cost(prompt_tokens, completion_tokens, model)
        total = prompt_tokens + completion_tokens

        with self._lock:
            self._tenant_spend[tenant_id] += cost
            self._total_spend += cost
            self._total_tokens += total
            self._tenant_tokens[tenant_id]["prompt"] += prompt_tokens
            self._tenant_tokens[tenant_id]["completion"] += completion_tokens
            self._tenant_tokens[tenant_id]["total"] += total

        from metrics import METRICS
        METRICS.inc("mcp_token_usage_total", total, tenant=tenant_id, model=model)
        METRICS.inc("mcp_cost_usd_total", cost, tenant=tenant_id, model=model)

        return cost

    def get_tenant_spend(self, tenant_id: str) -> float:
        with self._lock:
            return round(self._tenant_spend.get(tenant_id, 0.0), 4)

    def get_tenant_tokens(self, tenant_id: str) -> Dict[str, int]:
        with self._lock:
            return dict(self._tenant_tokens.get(tenant_id, {"prompt": 0, "completion": 0, "total": 0}))

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_spend_usd": round(self._total_spend, 4),
                "total_tokens": self._total_tokens,
                "active_tenants_tracked": len(self._tenant_spend),
                "tenant_breakdown": {t: round(s, 4) for t, s in self._tenant_spend.items()},
            }
