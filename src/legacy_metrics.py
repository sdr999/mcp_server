"""Legacy in-memory Prometheus metrics registry.

Preserved for fallback when OpenTelemetry is disabled or unavailable.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable, Dict, Tuple


def _label_key(labels: dict) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))


def _fmt_labels(key: Tuple[Tuple[str, str], ...]) -> str:
    if not key:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in key)
    return "{" + inner + "}"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class LegacyMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[Tuple[str, tuple], float] = defaultdict(float)
        self._sum: Dict[Tuple[str, tuple], float] = defaultdict(float)
        self._count: Dict[Tuple[str, tuple], float] = defaultdict(float)
        self._gauges: Dict[str, Tuple[str, Callable[[], float]]] = {}
        self._help: Dict[str, str] = {}

    def declare(self, name: str, help_text: str) -> None:
        self._help[name] = help_text

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        with self._lock:
            self._counters[(name, _label_key(labels))] += value

    def observe(self, name: str, value: float, **labels) -> None:
        with self._lock:
            key = (name, _label_key(labels))
            self._sum[key] += value
            self._count[key] += 1

    def gauge(self, name: str, fn: Callable[[], float], help_text: str = "") -> None:
        self._gauges[name] = (help_text, fn)

    def render(self) -> str:
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
            for (name, key), value in sorted(self._counters.items()):
                _help_type(name, "counter")
                lines.append(f"{name}{_fmt_labels(key)} {value}")
            for name, (help_text, fn) in sorted(self._gauges_cache if hasattr(self, '_gauges_cache') else self._gauges.items()):
                if help_text:
                    self._help.setdefault(name, help_text)
                _help_type(name, "gauge")
                try:
                    lines.append(f"{name} {float(fn())}")
                except Exception:
                    pass
            summaries = set(k[0] for k in self._sum)
            for name in sorted(summaries):
                _help_type(name, "summary")
                for (n, key), s in sorted(self._sum.items()):
                    if n != name:
                        continue
                    lbl = _fmt_labels(key)
                    lines.append(f"{name}_sum{lbl} {s}")
        return "\n".join(lines) + "\n"

    def get_tool_stats(self, tool_names: list[str] | None = None) -> dict[str, dict]:
        with self._lock:
            calls: dict[str, int] = defaultdict(int)
            errors: dict[str, int] = defaultdict(int)

            for (m_name, labels_tuple), val in self._counters.items():
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

