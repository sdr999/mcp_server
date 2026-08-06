"""Sandbox Execution Drivers: Subprocess (Local Dev) & Docker (Production Container)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseSandboxDriver, SandboxConfig, SandboxExecutionResult
from .egress import EgressFilter

log = logging.getLogger("MCP_logger")

MAX_OUTPUT_BYTES = 5 * 1024 * 1024  # 5MB log ceiling (Log bombing fix)


class SubprocessSandboxDriver(BaseSandboxDriver):
    """Local Development Driver: Executes tool in isolated subprocess via tool_runner.py."""

    async def execute(
        self,
        runner_path: Path,
        module_name: str,
        qualname: str,
        kwargs: Dict[str, Any],
        syspath: List[str],
        config: Optional[SandboxConfig] = None,
    ) -> SandboxExecutionResult:
        cfg = config or self.config
        timeout = cfg.timeout_seconds
        start_time = time.perf_counter()

        request_data = json.dumps(
            {"module": module_name, "qualname": qualname, "args": kwargs, "syspath": syspath}
        ).encode("utf-8")

        env = os.environ.copy()
        if cfg.egress_domains:
            egress = EgressFilter(cfg.egress_domains)
            env.update(egress.build_proxy_env())

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(runner_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(request_data), timeout=timeout
                )
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    proc.kill()
                    await proc.wait()
                return SandboxExecutionResult(
                    ok=False,
                    error=f"Execution exceeded {timeout}s timeout and was terminated",
                    execution_time_seconds=time.perf_counter() - start_time,
                    engine_used="subprocess",
                    exit_code=-1,
                )

            stdout_str = stdout_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr_str = stderr_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            duration = time.perf_counter() - start_time

            if proc.returncode != 0 and not stdout_bytes:
                return SandboxExecutionResult(
                    ok=False,
                    error=f"Process exited with non-zero status {proc.returncode}: {stderr_str[:300]}",
                    stdout=stdout_str,
                    stderr=stderr_str,
                    execution_time_seconds=duration,
                    engine_used="subprocess",
                    exit_code=proc.returncode or 1,
                )

            if not stdout_bytes:
                return SandboxExecutionResult(
                    ok=False,
                    error="Tool runner produced empty output",
                    stderr=stderr_str,
                    execution_time_seconds=duration,
                    engine_used="subprocess",
                    exit_code=proc.returncode or 1,
                )

            payload = json.loads(stdout_str.strip())
            if not payload.get("ok"):
                return SandboxExecutionResult(
                    ok=False,
                    error=payload.get("error", "Sandboxed tool execution failed"),
                    stdout=stdout_str,
                    stderr=stderr_str,
                    execution_time_seconds=duration,
                    engine_used="subprocess",
                    exit_code=proc.returncode or 1,
                )

            return SandboxExecutionResult(
                ok=True,
                result=payload.get("result"),
                stdout=stdout_str,
                stderr=stderr_str,
                execution_time_seconds=duration,
                engine_used="subprocess",
                exit_code=0,
            )

        except Exception as exc:
            log.error("Subprocess sandbox execution failed: %s", exc)
            return SandboxExecutionResult(
                ok=False,
                error=f"Subprocess driver error: {exc}",
                execution_time_seconds=time.perf_counter() - start_time,
                engine_used="subprocess",
                exit_code=1,
            )

    async def cleanup(self) -> None:
        pass


class DockerSandboxDriver(BaseSandboxDriver):
    """Production Driver: Spawns sandboxed container execution with security controls."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        super().__init__(config)
        self._docker_available: Optional[bool] = None

    def is_docker_available(self) -> bool:
        """Check if docker CLI/daemon is accessible on the host node."""
        if self._docker_available is not None:
            return self._docker_available
        try:
            import subprocess
            res = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
            self._docker_available = res.returncode == 0
        except Exception:
            self._docker_available = False
        return self._docker_available

    async def execute(
        self,
        runner_path: Path,
        module_name: str,
        qualname: str,
        kwargs: Dict[str, Any],
        syspath: List[str],
        config: Optional[SandboxConfig] = None,
    ) -> SandboxExecutionResult:
        cfg = config or self.config

        # Fallback to SubprocessSandboxDriver if Docker is unavailable
        if not self.is_docker_available():
            log.warning("Docker daemon unavailable; falling back to SubprocessSandboxDriver")
            fallback = SubprocessSandboxDriver(cfg)
            return await fallback.execute(runner_path, module_name, qualname, kwargs, syspath, cfg)

        start_time = time.perf_counter()
        request_data = json.dumps(
            {"module": module_name, "qualname": qualname, "args": kwargs, "syspath": syspath}
        ).encode("utf-8")

        # Docker security flags
        cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--label", "mcp.managed=true",
            "--label", f"mcp.created_at={int(time.time())}",
            "--read-only",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={cfg.tmpfs_size_mb}m",
            "--shm-size", f"{cfg.shm_size_mb}m",
            "--memory", f"{cfg.memory_limit_mb}m",
            "--cpus", str(cfg.cpu_count),
            "--pids-limit", str(cfg.max_processes),
            "--log-driver", "json-file",
            "--log-opt", f"max-size={cfg.log_max_size_mb}m",
            "--log-opt", "max-file=2",
        ]

        if not cfg.allow_network and not cfg.egress_domains:
            cmd.extend(["--network", "none"])

        cmd.extend(["python:3.12-slim", "python", "-c", "import sys; exec(sys.stdin.read())"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(request_data), timeout=cfg.timeout_seconds
                )
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    proc.kill()
                    await proc.wait()
                return SandboxExecutionResult(
                    ok=False,
                    error=f"Container execution exceeded {cfg.timeout_seconds}s timeout",
                    execution_time_seconds=time.perf_counter() - start_time,
                    engine_used="docker",
                    exit_code=-1,
                )

            duration = time.perf_counter() - start_time
            stdout_str = stdout_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr_str = stderr_bytes[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

            # Check for OOM exit code (137)
            if proc.returncode == 137:
                return SandboxExecutionResult(
                    ok=False,
                    error=f"Container killed due to Out-Of-Memory limit ({cfg.memory_limit_mb}MB)",
                    stdout=stdout_str,
                    stderr=stderr_str,
                    execution_time_seconds=duration,
                    engine_used="docker",
                    oom_killed=True,
                    exit_code=137,
                )

            if proc.returncode != 0:
                return SandboxExecutionResult(
                    ok=False,
                    error=f"Container exited with code {proc.returncode}: {stderr_str[:300]}",
                    stdout=stdout_str,
                    stderr=stderr_str,
                    execution_time_seconds=duration,
                    engine_used="docker",
                    exit_code=proc.returncode or 1,
                )

            payload = json.loads(stdout_str.strip())
            return SandboxExecutionResult(
                ok=payload.get("ok", False),
                result=payload.get("result"),
                error=payload.get("error"),
                stdout=stdout_str,
                stderr=stderr_str,
                execution_time_seconds=duration,
                engine_used="docker",
                exit_code=0,
            )

        except Exception as exc:
            log.error("Docker sandbox driver failure: %s", exc)
            return SandboxExecutionResult(
                ok=False,
                error=f"Docker driver error: {exc}",
                execution_time_seconds=time.perf_counter() - start_time,
                engine_used="docker",
                exit_code=1,
            )

    async def cleanup(self) -> None:
        pass
