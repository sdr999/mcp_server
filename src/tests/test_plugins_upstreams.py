"""Tests for plugins.upstreams: federation to remote MCP servers, exercised
in-memory (FastMCP Client can connect directly to a FastMCP instance, so no
ports/network are involved)."""
import asyncio

import pytest
from fastmcp import FastMCP

from plugins.upstreams import UpstreamError, UpstreamRegistry


def _upstream_server():
    up = FastMCP(name="up")

    @up.tool
    def greet(who: str) -> str:
        return f"hello {who}"

    @up.tool
    def boom(x: int) -> int:
        raise RuntimeError("remote fail")

    return up


def _reg(**servers):
    return UpstreamRegistry(servers)


def test_list_and_list_tools():
    reg = _reg(demo={"target": _upstream_server()})
    assert [u["name"] for u in reg.list()] == ["demo"]
    tools = asyncio.run(reg.list_tools("demo"))
    assert {t["name"] for t in tools} == {"greet", "boom"}


def test_call_tool_success():
    reg = _reg(demo={"target": _upstream_server()})
    res = asyncio.run(reg.call_tool("demo", "greet", {"who": "world"}))
    assert res["upstream"] == "demo" and res["tool"] == "greet"
    assert res["is_error"] is False
    assert res["structured_content"] == {"result": "hello world"}


def test_remote_tool_error_is_reported_in_band():
    reg = _reg(demo={"target": _upstream_server()})
    res = asyncio.run(reg.call_tool("demo", "boom", {"x": 1}))
    assert res["is_error"] is True


def test_unknown_upstream_raises_keyerror():
    reg = _reg()
    with pytest.raises(KeyError):
        asyncio.run(reg.list_tools("nope"))
    with pytest.raises(KeyError):
        asyncio.run(reg.call_tool("nope", "greet", {}))


def test_runtime_add_and_remove():
    reg = _reg()
    reg.add("x", "http://host/sse", token="tok")
    spec = reg.get("x")
    assert spec["url"] == "http://host/sse" and spec["token"] == "tok"

    assert reg.remove("x") is True
    assert reg.remove("x") is False


def test_unreachable_upstream_raises_upstreamerror():
    # A refused connection surfaces as UpstreamError, not a raw exception.
    reg = UpstreamRegistry({"bad": {"url": "http://127.0.0.1:9/sse"}}, timeout=2)
    with pytest.raises(UpstreamError):
        asyncio.run(reg.list_tools("bad"))
