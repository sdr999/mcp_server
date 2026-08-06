"""Per-tool network egress filtering & domain whitelist resolution."""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Set
from urllib.parse import urlparse

log = logging.getLogger("MCP_logger")

DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")
IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


class EgressFilter:
    """Parses and validates egress target rules for sandboxed tools."""

    def __init__(self, allowed_targets: Optional[List[str]] = None):
        self.allowed_domains: Set[str] = set()
        self.allowed_ips: Set[str] = set()
        if allowed_targets:
            for target in allowed_targets:
                self.add_target(target)

    def add_target(self, target: str) -> None:
        """Add a target host/domain/IP to the whitelist."""
        clean = target.strip().lower()
        if clean.startswith("http://") or clean.startswith("https://"):
            parsed = urlparse(clean)
            clean = parsed.hostname or clean

        if IP_RE.match(clean):
            self.allowed_ips.add(clean)
        elif DOMAIN_RE.match(clean) or clean == "localhost":
            self.allowed_domains.add(clean)
        else:
            log.warning("Invalid egress target rule %r; ignoring", target)

    def is_allowed(self, host_or_url: str) -> bool:
        """Check if a host or URL is permitted by the egress filter."""
        clean = host_or_url.strip().lower()
        if clean.startswith("http://") or clean.startswith("https://"):
            parsed = urlparse(clean)
            clean = parsed.hostname or clean

        if clean in self.allowed_domains or clean in self.allowed_ips:
            return True

        # Subdomain match (e.g. api.github.com matches github.com)
        for domain in self.allowed_domains:
            if clean.endswith(f".{domain}"):
                return True

        return False

    def build_proxy_env(self, proxy_url: str = "http://mcp-proxy:3128") -> dict:
        """Generate HTTP_PROXY environment variables for sandbox containers."""
        if not self.allowed_domains and not self.allowed_ips:
            return {}
        return {
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "MCP_EGRESS_ALLOWED": ",".join(sorted(self.allowed_domains | self.allowed_ips)),
        }
