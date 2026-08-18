"""Budget enforcement middleware checking per-tenant cumulative USD spend."""
from __future__ import annotations

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("MCP_logger")


class BudgetEnforcerMiddleware(BaseHTTPMiddleware):
    """Enforces per-tenant monthly USD budget limits on API and tool requests."""

    def __init__(self, app, cost_tracker=None, default_budget_usd: float = 100.0):
        super().__init__(app)
        self.cost_tracker = cost_tracker
        self.default_budget_usd = default_budget_usd

    async def dispatch(self, request: Request, call_next) -> Response:
        tracker = self.cost_tracker or getattr(request.app.state, "cost_tracker", None)
        if not tracker:
            return await call_next(request)

        # Derive the tenant from the resolved principal (IdentityMiddleware runs
        # outer to this one, so request.state.principal is populated). Nothing ever
        # sets request.state.tenant_id, so the old lookup collapsed every caller
        # onto a single "default" budget bucket.
        principal = getattr(request.state, "principal", None)
        tenant_id = getattr(principal, "org_id", None) or "default"
        current_spend = tracker.get_tenant_spend(tenant_id)
        budget_limit = getattr(request.app.state, "tenant_monthly_budget_usd", self.default_budget_usd)

        if current_spend >= budget_limit:
            log.warning("Tenant %s exceeded monthly budget limit ($%.2f >= $%.2f)", tenant_id, current_spend, budget_limit)
            return JSONResponse(
                {
                    "error": "Budget Exceeded",
                    "message": f"Tenant '{tenant_id}' has exceeded the monthly budget limit of ${budget_limit:.2f}.",
                    "current_spend_usd": current_spend,
                    "budget_limit_usd": budget_limit,
                },
                status_code=429,
                headers={
                    "X-Cost-USD": f"{current_spend:.4f}",
                    "X-Budget-Remaining": "0.0000",
                    "Retry-After": "3600",
                },
            )

        response = await call_next(request)
        remaining = max(0.0, budget_limit - current_spend)
        response.headers["X-Cost-USD"] = f"{current_spend:.4f}"
        response.headers["X-Budget-Remaining"] = f"{remaining:.4f}"
        return response
