"""Subprocess entry point for sandboxed tool execution.

Reads a JSON request from stdin, imports the target tool module, invokes the
function with the given arguments, and writes a JSON result to stdout. Runs in a
separate process so a tool that crashes, hangs, or over-consumes resources cannot
take down the server. On POSIX, optional CPU/memory rlimits are applied.

Request  : {"syspath": [...], "module": "...", "qualname": "...", "args": {...},
            "limits": {"cpu": <s>, "mem": <bytes>}}
Response : {"ok": true, "result": <json>} | {"ok": false, "error": "..."}

Isolation caveats (documented in docs/MCP_SERVER_FEATURES.md):
- This is PROCESS isolation, not an OS security sandbox. For strong isolation run
  the server in a locked-down container / restricted user.
- Arguments and results must be JSON-serializable. Tools requiring an MCP Context
  or returning rich streaming content are not supported in sandbox mode.
"""
import functools
import importlib
import inspect
import json
import sys


def _apply_limits(limits: dict) -> None:
    if not limits:
        return
    try:
        import resource  # POSIX only
    except Exception:
        return  # Windows: rely on process boundary + parent-side timeout
    try:
        if limits.get("cpu"):
            cpu = int(limits["cpu"])
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        if limits.get("mem"):
            mem = int(limits["mem"])
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except Exception:
        pass


def _resolve(module, qualname: str):
    return functools.reduce(getattr, qualname.split("."), module)


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def main() -> int:
    try:
        req = json.loads(sys.stdin.read())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"bad request: {exc}"}))
        return 1

    for path in req.get("syspath", []):
        if path not in sys.path:
            sys.path.insert(0, path)
    _apply_limits(req.get("limits"))

    # Set trace_id if passed from parent server process
    trace_id = req.get("trace_id") or os.environ.get("MCP_TRACE_ID")
    if trace_id:
        try:
            from plugins.observability import trace_id_ctx
            trace_id_ctx.set(trace_id)
        except Exception:
            pass


    import contextlib
    import io

    # Redirect the tool's own stdout so only our JSON envelope reaches the parent.
    tool_stdout = io.StringIO()
    try:
        module = importlib.import_module(req["module"])
        fn = _resolve(module, req["qualname"])
        with contextlib.redirect_stdout(tool_stdout):
            result = fn(**req.get("args", {}))
            if inspect.isawaitable(result):
                import asyncio
                result = asyncio.new_event_loop().run_until_complete(result)
        sys.stdout.write(json.dumps({"ok": True, "result": _jsonable(result)}))
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
