# 08 — CLI & Sandbox (`plugins/cli.py`, `tool_runner.py`)

Two smaller but useful pieces: offline CLI utilities for CI, and the subprocess
sandbox for tool execution.

## CLI utilities (`plugins/cli.py`)

`main.py` dispatches to these when `--validate` or `--sign` is passed; neither
starts a server or touches the network.

### `--validate DIR` — a CI gate

Loads a local tools directory and prints JSON stats. Exit `0` if every module
yields a tool, `1` if any failed/empty, `2` if the dir is missing. Wire it into
CI to catch broken tools before they ship.

```python
def run_validate(tools_dir: Path, src_dir: Path) -> int:
    if not tools_dir.exists():
        print(json.dumps({"error": f"directory not found: {tools_dir}"})); return 2
    sys.path.insert(0, str(tools_dir.resolve().parent))
    sys.path.insert(0, str(src_dir))                       # tools_sdk importable
    loader = ToolLoader(FastMCP(name="validate"), tools_dir, src_dir=src_dir)
    loader.load_all()
    stats = loader.stats()
    print(json.dumps({"stats": stats, "tools": [t["name"] for t in loader.catalog()]}, indent=2))
    return 1 if stats["failed_modules"] else 0
```

```console
$ python main.py --validate ./tools
{ "stats": {"loaded_modules": 1, "total_tools": 1, "failed_modules": 0, ...},
  "tools": ["text_analyzer"] }
```

### `--sign DIR` — generate a signed manifest

Writes `tools.manifest.json` (SHA-256 of each file, plus an HMAC signature if
`MCP_TOOL_SIGNING_KEY` is set). This is the input to signed-tools enforcement
(doc 03).

```python
def run_sign(tools_dir, signing_key, manifest_name="tools.manifest.json") -> int:
    tools = {p.name: sha256_file(p) for p in sorted(tools_dir.glob("*.py")) if p.name != "__init__.py"}
    manifest = {"algorithm": "sha256", "tools": tools}
    if signing_key:
        manifest["signature"] = manifest_signature(tools, signing_key)
    (tools_dir / manifest_name).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps({"status": "written", "tools": len(tools), "signed": bool(signing_key)}))
    return 0
```

The HMAC covers the canonicalized tools map, so the manifest itself can't be
tampered with when a key is configured:

```python
def manifest_signature(tools: dict, signing_key: str) -> str:
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()
```

## Subprocess sandbox (`tool_runner.py`)

When `MCP_SANDBOX_TOOLS=true`, each tool *call* runs in a short-lived
subprocess (crash/hang/resource isolation). The parent (`tool_loader._run_sandboxed`)
speaks a tiny JSON protocol to this entry point over stdin/stdout.

**Protocol:**
- Request: `{"syspath": [...], "module": "...", "qualname": "...", "args": {...}, "limits": {"cpu": s, "mem": bytes}}`
- Response: `{"ok": true, "result": <json>}` or `{"ok": false, "error": "..."}`

```python
def main() -> int:
    req = json.loads(sys.stdin.read())
    for path in req.get("syspath", []):
        if path not in sys.path:
            sys.path.insert(0, path)
    _apply_limits(req.get("limits"))                       # POSIX rlimits (CPU/mem)

    tool_stdout = io.StringIO()                            # keep the tool's stdout out of our JSON
    try:
        module = importlib.import_module(req["module"])
        fn = _resolve(module, req["qualname"])
        with contextlib.redirect_stdout(tool_stdout):
            result = fn(**req.get("args", {}))
            if inspect.isawaitable(result):
                result = asyncio.new_event_loop().run_until_complete(result)
        sys.stdout.write(json.dumps({"ok": True, "result": _jsonable(result)})); return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})); return 1
```

The parent enforces the wall-clock timeout and kills a hung subprocess:

```python
# tool_loader._run_sandboxed
try:
    out, err = await asyncio.wait_for(proc.communicate(request), timeout=timeout)
except asyncio.TimeoutError:
    proc.kill(); ...
    raise RuntimeError(f"tool execution exceeded {timeout}s and was killed")
```

### What it is and isn't

- **Is:** process isolation — a segfault / `sys.exit` / infinite loop / memory
  blow-up in a tool call kills only that subprocess; CPU/memory bounded by
  POSIX rlimits (`MCP_SANDBOX_MEM_MB`, `MCP_SANDBOX_CPU_SEC`).
- **Isn't:** an OS security sandbox — no namespaces/seccomp; the tool still runs
  as the server's user. For hard boundaries, run the server (or subprocess) in a
  locked-down container. Combine with signed tools to also control *what* loads.
- **Limits:** args/results must be JSON-serializable; tools needing an MCP
  `Context` or returning streaming content aren't supported in sandbox mode.

## Gotchas / design notes

- Sandbox mode adds subprocess-startup latency per call — enable it where
  isolation matters more than speed.
- `--validate` and `--sign` resolve env the same way the server does
  (`load_environment`), so `MCP_TOOL_SIGNING_KEY` / `MCP_TOOL_MANIFEST` are
  honored.
