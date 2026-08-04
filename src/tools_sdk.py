"""Lightweight, server-agnostic SDK for authoring MCP tools.

A tool module dropped into the tools directory may expose its tools in any of the
following ways. The loader (`multiple_mcp_main.ToolLoader`) resolves them in this
order and uses the FIRST mechanism that yields at least one tool:

1. ``def register(registrar): ...``   — full control; call ``registrar.add_tool(fn_or_tool)``.
2. ``TOOLS = [fn, ...]`` or ``{"name": fn, ...}``  — explicit export.
3. ``@tool(...)``-decorated functions — discovered by scanning the module.
4. Legacy fallback: a function whose name equals the module's file stem
   (e.g. ``my_tool.py`` -> ``def my_tool(...)``). Kept for backward compatibility.

The ``@tool`` decorator only *tags* a function with metadata; it imports nothing
from the server, so tool modules stay decoupled from FastMCP.

Example
-------
    from tools_sdk import tool

    @tool(name="weather", description="Current weather for a city")
    def get_weather(city: str) -> str:
        ...

    @tool()                      # name defaults to the function name
    def search(query: str) -> list:
        ...
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

# Attribute used to tag a decorated function with its tool metadata.
TOOL_MARKER = "__mcp_tool__"


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    *,
    tags: Optional[Iterable[str]] = None,
) -> Callable[[Callable], Callable]:
    """Tag a function as an MCP tool.

    Args:
        name: Tool name exposed to clients. Defaults to the function's own name,
            so the tool name no longer has to match the file name.
        description: Human-readable description. Defaults to the function docstring
            (resolved later by FastMCP if left as None).
        tags: Optional set of tags.
    """

    def decorator(fn: Callable) -> Callable:
        setattr(
            fn,
            TOOL_MARKER,
            {
                "name": name or getattr(fn, "__name__", None),
                "description": description,
                "tags": set(tags) if tags else None,
            },
        )
        return fn

    return decorator


def is_tool(obj: object) -> bool:
    """True if `obj` is a callable tagged by :func:`tool`."""
    return callable(obj) and hasattr(obj, TOOL_MARKER)
