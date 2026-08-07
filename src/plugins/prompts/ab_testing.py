"""Deterministic MD5-hashed A/B testing variant manager."""
from __future__ import annotations

import hashlib
import logging
from typing import Dict, Any, List

log = logging.getLogger("MCP_logger")


class ABTestManager:
    """Handles deterministic MD5 sticky variant allocation per tenant / principal."""

    def select_variant(self, tenant_id: str, prompt_name: str, variants: Dict[str, str]) -> tuple[str, str]:
        if not variants:
            return "default", ""
        if len(variants) == 1:
            key = list(variants.keys())[0]
            return key, variants[key]

        variant_keys = sorted(variants.keys())
        hash_val = int(hashlib.md5(f"{tenant_id}:{prompt_name}".encode("utf-8")).hexdigest(), 16) % 100
        idx = hash_val % len(variant_keys)
        selected_key = variant_keys[idx]
        return selected_key, variants[selected_key]
