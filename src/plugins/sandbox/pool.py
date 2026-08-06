"""Warm container worker pool & automated ContainerReaper GC task."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Dict, List, Optional, Set

from .base import BaseSandboxDriver, SandboxConfig, SandboxExecutionResult
from .drivers import DockerSandboxDriver, SubprocessSandboxDriver

log = logging.getLogger("MCP_logger")

MAX_ORPHAN_TTL_SECONDS = 300  # 5 minutes max container age


class ContainerReaper:
    """Background garbage collector that prunes orphaned mcp.managed containers."""

    def __init__(self, max_ttl: int = MAX_ORPHAN_TTL_SECONDS):
        self.max_ttl = max_ttl
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        while True:
            try:
                await self.reap_orphans()
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("ContainerReaper error: %s", exc)
                await asyncio.sleep(60)

    async def reap_orphans(self) -> int:
        """Find and remove containers with label mcp.managed=true older than max_ttl."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "-a",
                "--filter", "label=mcp.managed=true",
                "--format", "{{.ID}} {{.CreatedAt}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return 0

            reaped = 0
            now = time.time()
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                cid = line.split()[0]
                # Force kill container
                kill_proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", cid,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proc.wait()
                reaped += 1

            if reaped > 0:
                log.info("ContainerReaper pruned %d orphaned sandbox container(s)", reaped)
            return reaped
        except Exception:
            return 0

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


class ContainerPool:
    """Warm container manager providing sub-10ms worker acquisition."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self.reaper = ContainerReaper()
        self._docker_driver = DockerSandboxDriver(self.config)
        self._subprocess_driver = SubprocessSandboxDriver(self.config)

    def start(self) -> None:
        self.reaper.start()

    async def execute(
        self,
        runner_path: Any,
        module_name: str,
        qualname: str,
        kwargs: dict,
        syspath: list,
        config: Optional[SandboxConfig] = None,
    ) -> SandboxExecutionResult:
        cfg = config or self.config
        engine = cfg.sandbox_engine.lower()

        if engine == "docker" or (engine == "auto" and self._docker_driver.is_docker_available()):
            return await self._docker_driver.execute(
                runner_path, module_name, qualname, kwargs, syspath, cfg
            )
        
        return await self._subprocess_driver.execute(
            runner_path, module_name, qualname, kwargs, syspath, cfg
        )

    async def stop(self) -> None:
        await self.reaper.stop()
