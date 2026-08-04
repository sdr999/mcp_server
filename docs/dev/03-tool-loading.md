# 03 — Tool Loading (`tools_sdk.py`, `plugins/tool_loader.py`, `plugins/signing.py`)

**Job:** turn `.py` files in the tools directory into registered MCP tools —
safely (one bad file never takes down the server), explainably (we can say what
was exposed and why), and without blocking the event loop.

## The authoring contract (`tools_sdk.py`)

A tool file may expose tools in four ways. The `@tool` decorator only *tags* a
function with metadata — it imports nothing from the server, so tool modules
stay decoupled from FastMCP.

```python
TOOL_MARKER = "__mcp_tool__"

def tool(name=None, description=None, *, tags=None):
    def decorator(fn):
        setattr(fn, TOOL_MARKER, {
            "name": name or getattr(fn, "__name__", None),
            "description": description,
            "tags": set(tags) if tags else None,
        })
        return fn
    return decorator
```

The four mechanisms, in precedence order (first that yields a tool wins):

| # | Mechanism | Example |
|---|-----------|---------|
| 1 | `register(registrar)` | `def register(mcp): mcp.add_tool(fn)` |
| 2 | `TOOLS` export | `TOOLS = [fn]` or `{"name": fn}` |
| 3 | `@tool(...)` scan | `@tool(name="weather")` |
| 4 | Legacy fallback | file `weather.py` → `def weather(...)` |

## Resolution with an explainable report

The resolver returns both the tools **and** a `ResolutionReport` — which
mechanism won, every function it saw, which were exposed, and why the rest were
not. Onboarding uses this to preview the tool surface and enforce policy
(doc 07); the loader itself just registers.

```python
@dataclass
class ResolutionReport:
    mechanism: Optional[str] = None                 # register|TOOLS|decorator|legacy
    functions_seen: List[str] = field(default_factory=list)
    selected: List[str] = field(default_factory=list)
    excluded: List[Tuple[str, str]] = field(default_factory=list)  # (fn, reason)
    warnings: List[str] = field(default_factory=list)
```

The `excluded` list keys off *function* names, not tool names — important
because `@tool(name="x")` renames. So the exposed set is tracked as function
names:

```python
decorated = [(k, v) for k, v in vars(module).items()
             if callable(v) and hasattr(v, TOOL_MARKER)]
if decorated:
    for _fname, fn in decorated:
        _safe_add(fn, None)
    if results:
        # exposed_fns = the decorated function names; excluded = seen − exposed
        return _finish("decorator", {k for k, _ in decorated}, "not decorated with @tool")
```

For the classic "3 functions, 1 tool + 2 helpers" file, the report yields
`selected=["current_weather"]`, `excluded=[("_celsius_to_f","not decorated..."),
("_fetch_raw","...")]`. Helpers are never registered.

## The `prepare` / `commit` split — the core concurrency idea

Importing a module is slow and can hang or crash; mutating the FastMCP registry
is fast and must happen on the serving loop. So loading is two phases:

- **`prepare(path)`** — verify (signing) + import + resolve. Safe to run in a
  thread. Returns a `_LoadPlan`; **never touches the registry**.
- **`commit(plan)`** — `add_tool` / `remove_tool`. Must run on the event loop;
  contains no `await`, so it's atomic w.r.t. other coroutines.

```python
@dataclass
class _LoadPlan:
    module_name: str
    mtime: Optional[float]
    resolved: List[Tuple[str, "FunctionTool"]]
    failure: Optional[str] = None        # "deleted" | "import error: ..." | ...
    resolution: Optional[ResolutionReport] = None
```

```python
def prepare(self, file_path):
    ...
    try:
        module = self._import(module_name)
    except Exception as exc:
        return _LoadPlan(module_name, mtime, [], failure=f"import error: {exc}")
    resolved, report = self._resolve_with_report(module, module_name)
    return _LoadPlan(module_name, mtime, resolved, resolution=report)
```

`commit` applies duplicate-name policy (**first registration wins**), records
per-tool catalog metadata, and updates metrics:

```python
for name, tool_obj in plan.resolved:
    owner = self._name_owner.get(name)
    if owner and owner != module_name:
        log.warning("Tool name %r from %s ignored: already provided by %s (first wins)", ...)
        continue
    self.mcp.add_tool(tool_obj)
    self._name_owner[name] = module_name
    self._tool_info[name] = {"name": name, "module": module_name, ...}
```

## Fault isolation

A broken file must never abort the server or its siblings. Failures are caught
at every level:

- **Bad import / `register()` raises / syntax error** → recorded as a module
  failure, logged, skipped.
- **One malformed tool among several** → that tool is skipped, the rest load
  (`_safe_add` wraps `_to_tool` in try/except).
- **Slow/hanging import** → bounded by a timeout (see doc 04, `prepare_with_timeout`).

```python
def _safe_add(obj, explicit_name):
    try:
        results.append(self._to_tool(obj, explicit_name))
    except Exception as exc:
        log.error("Skipping invalid tool %r in %s: %s", ident, module_name, exc)
```

Introspection for `/status` and `/tools`:

```python
def stats(self):
    return {"loaded_modules": ..., "total_tools": ..., "failed_modules": len(self._failures),
            "disabled_tools": len(self._disabled), "failures": dict(self._failures)}
```

## Metrics + optional sandbox wrapping

When metrics or sandbox mode is on, each tool callable is wrapped. `functools.wraps`
preserves the signature so FastMCP still builds the right input schema.

```python
@functools.wraps(original)
async def wrapper(**kwargs):
    start = time.perf_counter()
    METRICS.inc("mcp_tool_calls_total", tool=tool_name)
    try:
        if sandbox:
            return await _run_sandboxed(runner, module_name, qualname, kwargs, syspath, timeout, limits)
        result = original(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception:
        METRICS.inc("mcp_tool_errors_total", tool=tool_name)
        raise
    finally:
        METRICS.observe("mcp_tool_duration_seconds", time.perf_counter() - start, tool=tool_name)
```

The sandbox path runs the call in a subprocess (`tool_runner.py`, doc 08).

## Admin operations on the registry

- `disable(name)` / `enable(name)` — unregister a tool and keep it unregistered
  across reloads (persisted in `_disabled`); `enable` invalidates mtime so the
  follow-up `load_path` actually re-imports.
- `module_outcome(module_name)` → `(registered_names, failure_reason)` — lets
  onboarding report a *truthful* result instead of assuming success.
- `invalidate(module_name)` — drop the cached mtime so an overwrite re-imports.
- `get_tool(name)` → the registered `FunctionTool` (or `None` if
  unknown/disabled), so it can be executed by name via `POST /tools/{name}/call`
  (doc 05). The loader keeps a `_tools` name→object map maintained in
  `commit`/`unload`/`disable`.

## Signed tools (`plugins/signing.py`)

Supply-chain hardening: with `MCP_REQUIRE_SIGNED_TOOLS=true`, a file is imported
only if it's in a trusted manifest with a matching SHA-256. If a signing key is
set, the manifest's own HMAC must verify first (tamper protection).

```python
class ToolVerifier:
    def verify(self, file_path):
        if not self.require:
            return True, ""
        if not self.trusted:
            return False, "no trusted manifest"
        want = self.entries.get(file_path.name)
        if not want:
            return False, "not listed in manifest"
        if not hmac.compare_digest(sha256_file(file_path), want):
            return False, "hash mismatch"
        return True, ""
```

`prepare` calls `verify` before importing; a failure becomes a `_LoadPlan`
failure (`"unsigned/untrusted: ..."`), never an exception.

## Gotchas / design notes

- **Duplicate tool names across files**: first wins, later logged + skipped.
- **`_resolve_tools` vs `_resolve_with_report`**: the former is a thin back-compat
  shim returning just the list; production uses the report version.
- Tool names are decoupled from file names (mechanisms 1–3), so one file can
  export several explicitly-named tools.
