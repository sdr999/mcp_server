"""Unit and integration tests for Phase 2 Containerized Sandboxing Engine & Egress Filter."""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from plugins.sandbox.base import SandboxConfig, SandboxExecutionResult
from plugins.sandbox.drivers import SubprocessSandboxDriver, DockerSandboxDriver
from plugins.sandbox.egress import EgressFilter
from plugins.sandbox.pool import ContainerPool, ContainerReaper


@pytest.mark.anyio
async def test_subprocess_sandbox_driver_execution():
    driver = SubprocessSandboxDriver()
    runner = Path("src/tool_runner.py")
    if not runner.exists():
        runner = Path("../src/tool_runner.py")

    # Execute valid function (e.g. json.dumps)
    res = await driver.execute(
        runner_path=runner,
        module_name="json",
        qualname="dumps",
        kwargs={"obj": 42},
        syspath=[],
        config=SandboxConfig(timeout_seconds=5.0),
    )

    assert res.ok is True
    assert res.result == "42"
    assert res.engine_used == "subprocess"


@pytest.mark.anyio
async def test_subprocess_sandbox_driver_timeout(tmp_path):
    driver = SubprocessSandboxDriver()
    runner = Path("src/tool_runner.py")
    if not runner.exists():
        runner = Path("../src/tool_runner.py")

    # Create a temporary slow tool file
    slow_tool_dir = tmp_path / "slow_tools"
    slow_tool_dir.mkdir()
    (slow_tool_dir / "__init__.py").write_text("")
    (slow_tool_dir / "slow.py").write_text("import time\n\ndef slow_fn(secs=2.0):\n    time.sleep(secs)\n    return 'done'\n")

    res = await driver.execute(
        runner_path=runner,
        module_name="slow_tools.slow",
        qualname="slow_fn",
        kwargs={"secs": 5.0},
        syspath=[str(tmp_path)],
        config=SandboxConfig(timeout_seconds=0.1),
    )

    assert res.ok is False
    assert any(k in res.error.lower() for k in ("exceeded", "terminated", "timeout"))


def test_egress_filter_domain_parsing():
    filter_obj = EgressFilter(["api.github.com", "https://supabase.co/auth/v1", "192.168.1.100"])

    assert filter_obj.is_allowed("api.github.com") is True
    assert filter_obj.is_allowed("sub.api.github.com") is True
    assert filter_obj.is_allowed("supabase.co") is True
    assert filter_obj.is_allowed("192.168.1.100") is True

    # Disallowed domains
    assert filter_obj.is_allowed("malicious-site.com") is False
    assert filter_obj.is_allowed("google.com") is False


def test_egress_filter_proxy_env():
    filter_obj = EgressFilter(["api.github.com"])
    env = filter_obj.build_proxy_env("http://mcp-proxy:3128")

    assert env["HTTP_PROXY"] == "http://mcp-proxy:3128"
    assert env["HTTPS_PROXY"] == "http://mcp-proxy:3128"
    assert "api.github.com" in env["MCP_EGRESS_ALLOWED"]


@pytest.mark.anyio
async def test_container_pool_acquisition_and_fallback():
    pool = ContainerPool(SandboxConfig(sandbox_engine="subprocess"))
    pool.start()

    runner = Path("src/tool_runner.py")
    if not runner.exists():
        runner = Path("../src/tool_runner.py")

    res = await pool.execute(
        runner_path=runner,
        module_name="json",
        qualname="dumps",
        kwargs={"obj": "hello"},
        syspath=[],
    )

    assert res.ok is True
    assert res.result == '"hello"'
    await pool.stop()


@pytest.mark.anyio
async def test_container_reaper_lifecycle():
    reaper = ContainerReaper(max_ttl=10)
    reaper.start()
    reaped_count = await reaper.reap_orphans()
    assert isinstance(reaped_count, int)
    await reaper.stop()
