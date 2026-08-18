"""Lightweight in-memory TF-IDF keyword log search index with secret scrubbing."""
from __future__ import annotations

import collections
import datetime
import math
import re
import threading
from typing import Dict, List, Any, Optional

from ..observability import SecretMaskingFilter


class LogSearchIndex:
    """Bounded in-memory ring-buffer search index for tool execution logs."""

    def __init__(self, max_capacity: int = 1000):
        self._lock = threading.Lock()
        self._max_capacity = max_capacity
        self._buffer: collections.deque = collections.deque(maxlen=max_capacity)
        self._masker = SecretMaskingFilter()

    def _clean_text(self, obj: Any) -> str:
        # Key-based secret redaction only fires on dicts; stringifying first
        # bypassed it and left password/api_key/token VALUES in the searchable
        # index. Redact the dict structurally, THEN stringify + mask bearer tokens.
        if isinstance(obj, dict):
            obj = self._masker._redact_dict(obj)
        return self._masker.mask_text(str(obj or ""))


    def _tokenize(self, text: str) -> List[str]:
        words = re.findall(r"\w+", text.lower())
        return [w for w in words if len(w) > 2]

    def add_execution_log(
        self,
        tool_name: str,
        status: str,
        duration_sec: float,
        input_payload: Optional[Dict[str, Any]] = None,
        output_payload: Optional[Dict[str, Any]] = None,
        error_msg: Optional[str] = None,
        tenant_id: str = "default",
    ) -> None:
        clean_input = self._clean_text(input_payload)
        clean_output = self._clean_text(output_payload)
        clean_error = self._clean_text(error_msg)

        combined_text = f"{tool_name} {status} {tenant_id} {clean_input} {clean_output} {clean_error}"
        tokens = self._tokenize(combined_text)

        entry = {
            "id": f"log-{datetime.datetime.now(datetime.timezone.utc).timestamp()}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tool_name": tool_name,
            "tenant_id": tenant_id,
            "status": status,
            "duration_sec": round(duration_sec, 4),
            "input": clean_input[:300],
            "output": clean_output[:300],
            "error": clean_error[:300],
            "tokens": set(tokens),
        }

        with self._lock:
            self._buffer.append(entry)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            with self._lock:
                return [self._format_result(item, 0.0) for item in list(self._buffer)[-limit:]]

        results = []
        with self._lock:
            snapshot = list(self._buffer)

        total_docs = len(snapshot) or 1
        for item in snapshot:
            score = 0.0
            item_tokens = item["tokens"]
            for q_term in query_tokens:
                if q_term in item_tokens:
                    # TF-IDF scoring weight approximation
                    score += 1.0 + math.log(total_docs / (sum(1 for d in snapshot if q_term in d["tokens"]) or 1))
            if score > 0:
                results.append((score, item))

        results.sort(key=lambda x: x[0], reverse=True)
        return [self._format_result(item, score) for score, item in results[:limit]]

    def _format_result(self, item: Dict[str, Any], score: float) -> Dict[str, Any]:
        d = dict(item)
        d["relevance_score"] = round(score, 2)
        d.pop("tokens", None)
        return d

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "indexed_entries_count": len(self._buffer),
                "max_capacity": self._max_capacity,
            }
