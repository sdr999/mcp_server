"""OpenTelemetry metrics instruments and compatibility shim for LegacyMetrics."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable, Dict, Tuple

from .bootstrap import get_meter

log = logging.getLogger("MCP_logger")


def _label_key(labels: dict) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))


def _fmt_labels(key: Tuple[Tuple[str, str], ...]) -> str:
    if not key:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in key)
    return "{" + inner + "}"


class OTelMetricsShim:
    """Compatibility shim implementing the LegacyMetrics interface over OTel Meter instruments."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters_cache: Dict[str, Any] = {}
        self._gauges_cache: Dict[str, Tuple[str, Callable[[], float]]] = {}
        self._help: Dict[str, str] = {}
        self._fallback_counters: Dict[Tuple[str, tuple], float] = defaultdict(float)
        self._fallback_sum: Dict[Tuple[str, tuple], float] = defaultdict(float)
        self._fallback_count: Dict[Tuple[str, tuple], float] = defaultdict(float)

    def declare(self, name: str, help_text: str) -> None:
        self._help[name] = help_text

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        with self._lock:
            self._fallback_counters[(name, _label_key(labels))] += value
        meter = get_meter("mcp-server")
        if meter:
            try:
                if name not in self._counters_cache:
                    self._counters_cache[name] = meter.create_counter(
                        name, description=self._help.get(name, "")
                    )
                self._counters_cache[name].add(value, attributes=labels)
            except Exception as exc:
                log.debug("OTel counter inc failed for %s: %s", name, exc)

    def observe(self, name: str, value: float, **labels) -> None:
        with self._lock:
            key = (name, _label_key(labels))
            self._fallback_sum[key] += value
            self._fallback_count[key] += 1
        meter = get_meter("mcp-server")
        if meter:
            try:
                if name not in self._counters_cache:
                    self._counters_cache[name] = meter.create_histogram(
                        name, description=self._help.get(name, "")
                    )
                self._counters_cache[name].record(value, attributes=labels)
            except Exception as exc:
                log.debug("OTel histogram record failed for %s: %s", name, exc)

    def gauge(self, name: str, fn: Callable[[], float], help_text: str = "") -> None:
        with self._lock:
            self._gauges_cache[name] = (help_text or self._help.get(name, ""), fn)

    def render(self) -> str:
        """Renders Prometheus text format for /metrics endpoint."""
        lines = []
        emitted_help = set()

        def _help_type(metric: str, mtype: str):
            if metric in emitted_help:
                return
            emitted_help.add(metric)
            if self._help.get(metric):
                lines.append(f"# HELP {metric} {self._help[metric]}")
            lines.append(f"# TYPE {metric} {mtype}")

        with self._lock:
            for (name, key), value in sorted(self._fallback_counters.items()):
                _help_type(name, "counter")
                lines.append(f"{name}{_fmt_labels(key)} {value}")
            for name, (help_text, fn) in sorted(self._gauges_cache.items()):
                if help_text:
                    self._help.setdefault(name, help_text)
                _help_type(name, "gauge")
                try:
                    lines.append(f"{name} {float(fn())}")
                except Exception:
                    pass
            summaries = set(k[0] for k in self._fallback_sum)
            for name in sorted(summaries):
                _help_type(name, "summary")
                for (n, key), s in sorted(self._fallback_sum.items()):
                    if n != name:
                        continue
                    lbl = _fmt_labels(key)
                    lines.append(f"{name}_sum{lbl} {s}")
                    lines.append(f"{name}_count{lbl} {self._fallback_count[(n, key)]}")
        return "\n".join(lines) + "\n"

    def get_tool_stats(self, tool_names: list[str] | None = None) -> dict[str, dict]:
        with self._lock:
            calls: dict[str, int] = defaultdict(int)
            errors: dict[str, int] = defaultdict(int)

            for (m_name, labels_tuple), val in self._fallback_counters.items():
                labels_dict = dict(labels_tuple)
                tool = labels_dict.get("tool")
                if not tool:
                    continue
                if m_name == "mcp_tool_calls_total":
                    calls[tool] += int(val)
                elif m_name == "mcp_tool_errors_total":
                    errors[tool] += int(val)

            all_tools = set(calls.keys()) | set(errors.keys())
            if tool_names:
                all_tools.update(tool_names)

            results = {}
            for tool in sorted(all_tools):
                c = calls[tool]
                e = errors[tool]
                s = max(0, c - e)
                rate = 100.0 if c == 0 else round((s / c) * 100.0, 1)
                results[tool] = {
                    "calls": c,
                    "errors": e,
                    "successes": s,
                    "success_rate_percent": rate,
                }
            return results

