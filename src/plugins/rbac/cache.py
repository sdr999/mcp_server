"""L1 In-Memory Decision Cache for PolicyEvaluator (Phase 2)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

log = logging.getLogger("MCP_logger")


class DecisionCache:
    """Thread-safe LRU in-memory decision cache with TTL invalidation.
    Cache key: (principal_id, org_id, workspace_id, action, resource)
    """

    def __init__(self, maxsize: int = 10000, ttl_sec: float = 300.0):
        self.maxsize = maxsize
        self.ttl_sec = ttl_sec
        self._cache: Dict[Tuple[str, str, str, str, str], Tuple[object, float]] = {}
        self._lock = threading.Lock()

    def make_key(
        self,
        principal_id: str,
        org_id: str,
        workspace_id: str,
        action: str,
        resource: str,
    ) -> Tuple[str, str, str, str, str]:
        return (principal_id, org_id, workspace_id or "default", action, resource)

    def get(
        self,
        principal_id: str,
        org_id: str,
        workspace_id: str,
        action: str,
        resource: str,
    ) -> Optional[object]:
        key = self.make_key(principal_id, org_id, workspace_id, action, resource)
        now = time.time()
        with self._lock:
            if key in self._cache:
                result, exp = self._cache[key]
                if now < exp:
                    return result
                del self._cache[key]
        return None

    def put(
        self,
        principal_id: str,
        org_id: str,
        workspace_id: str,
        action: str,
        resource: str,
        result: object,
    ) -> None:
        key = self.make_key(principal_id, org_id, workspace_id, action, resource)
        exp = time.time() + self.ttl_sec
        with self._lock:
            if len(self._cache) >= self.maxsize:
                # Evict oldest entry
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key] = (result, exp)

    def invalidate(
        self,
        principal_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> int:
        """Evict cached decisions for a specific principal or org."""
        count = 0
        with self._lock:
            keys_to_del = []
            for k in self._cache:
                pid, oid, _, _, _ = k
                if principal_id and pid == principal_id:
                    keys_to_del.append(k)
                elif org_id and oid == org_id:
                    keys_to_del.append(k)
            for k in keys_to_del:
                del self._cache[k]
                count += 1
        return count

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
