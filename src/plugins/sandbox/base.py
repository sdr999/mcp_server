"""Base interface and data models for Phase 2 Sandboxing Engine."""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SandboxConfig:
    """Execution constraints and configuration for sandboxed tool execution."""

    timeout_seconds: float = 30.0
    memory_limit_mb: int = 128
    cpu_count: float = 0.5
    max_processes: int = 64
    read_only_root: bool = True
    tmpfs_size_mb: int = 64
    shm_size_mb: int = 256
    log_max_size_mb: int = 5
    allow_network: bool = False
    egress_domains: List[str] = field(default_factory=list)
    sandbox_engine: str = "auto"  # "auto" | "docker" | "subprocess"
    pool_size: int = 5


@dataclass
class SandboxExecutionResult:
    """Result payload returned after sandboxed tool execution."""

    ok: bool
    result: Any = None
    error: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    execution_time_seconds: float = 0.0
    engine_used: str = "subprocess"
    oom_killed: bool = False
    exit_code: int = 0


class BaseSandboxDriver(abc.ABC):
    """Abstract base class for all sandbox execution drivers."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()

    @abc.abstractmethod
    async def execute(
        self,
        runner_path: Path,
        module_name: str,
        qualname: str,
        kwargs: Dict[str, Any],
        syspath: List[str],
        config: Optional[SandboxConfig] = None,
    ) -> SandboxExecutionResult:
        """Execute a tool in an isolated sandbox environment."""
        pass

    @abc.abstractmethod
    async def cleanup(self) -> None:
        """Clean up driver resources (e.g. idle containers, temp files)."""
        pass
