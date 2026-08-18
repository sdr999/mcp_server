"""Tool analytics & insights plugin (no hard dependency; stdlib-only core).

See docs/ANALYTICS_PLUGIN_PLAN.md. Attaches an AnalyticsEngine to app.state and
consumes tool events through the neutral observer seam, so the hot-path wrapper
never imports this package.
"""
from __future__ import annotations

from .engine import AnalyticsConfig, AnalyticsEngine
from .routes import analytics_routes

__all__ = ["AnalyticsEngine", "AnalyticsConfig", "analytics_routes"]
