"""Versioned prompt repository and template hydration engine."""
from __future__ import annotations

import logging
import re
import threading
from typing import Dict, Any, Optional, List

log = logging.getLogger("MCP_logger")


def _version_key(v: str) -> tuple:
    """Sort key that orders version strings numerically (v1.10.0 > v1.9.0)."""
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums) if nums else (0,)


class PromptRepository:
    """Thread-safe versioned prompt template repository."""

    def __init__(self):
        self._lock = threading.Lock()
        self._prompts: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def register_prompt(
        self,
        name: str,
        template: str,
        version: str = "v1.0.0",
        description: str = "",
        variants: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        entry = {
            "name": name,
            "version": version,
            "template": template,
            "description": description,
            "variants": variants or {"default": template},
        }

        with self._lock:
            if name not in self._prompts:
                self._prompts[name] = {}
            self._prompts[name][version] = entry

        log.info("Registered prompt '%s' version '%s'", name, version)
        return entry

    def get_prompt(self, name: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            versions = self._prompts.get(name, {})
            if not versions:
                return None
            if version and version in versions:
                return dict(versions[version])
            # Numeric (semver) ordering, not lexicographic -- otherwise 'v1.10.0'
            # sorts before 'v1.9.0' and callers get a stale template.
            latest_version = max(versions.keys(), key=_version_key)
            return dict(versions[latest_version])

    def hydrate(self, template: str, variables: Optional[Dict[str, Any]] = None) -> str:
        if not variables:
            return template
        result = template
        for k, v in variables.items():
            result = re.sub(r"\{\{\s*" + re.escape(str(k)) + r"\s*\}\}", str(v), result)
        return result

    def list_prompts(self) -> List[Dict[str, Any]]:
        results = []
        with self._lock:
            for name, versions in self._prompts.items():
                for ver, data in versions.items():
                    results.append({
                        "name": name,
                        "version": ver,
                        "description": data["description"],
                        "variants_count": len(data["variants"]),
                    })
        return results
