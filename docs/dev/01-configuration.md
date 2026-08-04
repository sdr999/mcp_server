# 01 — Configuration (`plugins/config.py`)

**Job:** turn CLI args + environment variables into one immutable
`AppContext`, and fail fast on invalid config. No network I/O, no side effects
beyond reading `config/.env`, so it's trivially unit-testable.

## The `AppContext`

Everything the rest of the app needs is on one frozen-ish dataclass, built once
at startup and threaded through `build_app`. This keeps config *reading* in one
place; no other module calls `os.environ`.

```python
@dataclass
class AppContext:
    base_dir: Path
    tools_dir: Path
    env: dict
    auth_type: str                 # "" | none | api_key | bearer_jwt
    api_key_header: str
    api_key_value: str
    jwks_url: str
    ...
    admin_token: str
    require_signed: bool
    signing_key: Optional[str]
    # onboarding knobs have defaults so tests can omit them
    onboard_enabled: bool = True
    onboard_autoinstall: bool = True
    onboard_network_check: bool = True
    onboard_require_explicit: bool = True
    onboard_max_tools: int = 0
    ...
```

## Environment precedence: OS wins, `.env` is the fallback

The subtlety is that a **blank** OS value (`KEY=""`) must not shadow the
`.env` fallback — otherwise an empty exported var silently disables a feature.

```python
def merge_env(os_env, fallbacks: dict) -> dict:
    """OS env wins when set and non-blank; otherwise use the config/.env fallback."""
    env = dict(os_env)
    for key, value in (fallbacks or {}).items():
        if value is None:
            continue
        current = env.get(key)
        if current is None or str(current).strip() == "":   # unset OR blank
            env[key] = value
    return env
```

`load_environment` then aliases the merged dict onto the framework's global so
tool modules read the same config the server does:

```python
def load_environment(base_dir: Path) -> dict:
    env_path = base_dir / "config" / ".env"
    fallbacks = dotenv_values(str(env_path)) if env_path.exists() else {}
    env = merge_env(os.environ, fallbacks)
    global_variables.env = env      # framework + tools see identical config
    return env
```

## Safe `--config` decoding (path-traversal defense)

`--config` is a base64-encoded path **relative to `src/`**, used to point the
server at a different tools directory. Because it can come from a deployment
system, it's treated as hostile input: absolute paths, `..` segments, and
Windows drive prefixes are rejected, and the resolved path must stay inside
`base_dir`.

```python
def decode_config_path(raw: str, base_dir: Path) -> Tuple[str, Path]:
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    decoded = base64.b64decode(raw).decode("utf-8").strip()

    if not decoded:
        raise ValueError("--config decoded to an empty path")
    if decoded.startswith(("/", "\\")) or ".." in Path(decoded).parts or ":" in decoded[:3]:
        raise ValueError(f"--config tool path is not a safe relative path: {decoded!r}")

    base_resolved = base_dir.resolve()
    local = (base_dir / decoded).resolve()
    if not local.is_relative_to(base_resolved):   # correct containment check
        raise ValueError(f"--config path escapes base dir: {decoded!r}")
    return decoded, local
```

> **Why `is_relative_to` and not a string prefix check?** A `startswith`
> comparison has the classic `/base` vs `/base-evil` bug. Resolving both paths
> and using `is_relative_to` is the correct containment test.

## Fail-fast validation

`validate_context` runs right after `build_context` in `main.py`, so a
misconfigured server dies at boot with a clear message instead of failing on
the first request.

```python
def validate_context(ctx: AppContext) -> None:
    if ctx.auth_type not in ("", "none", "api_key", "bearer_jwt"):
        raise RuntimeError(f"MCP_AUTH_TYPE must be none|api_key|bearer_jwt, got {ctx.auth_type!r}")
    if ctx.auth_type == "bearer_jwt" and not ctx.jwks_url:
        raise RuntimeError("JWKS_URL must be set when MCP_AUTH_TYPE=bearer_jwt")
    if ctx.auth_type == "api_key" and not ctx.api_key_value:
        raise RuntimeError("MCP_API_KEY_VALUE must be set when MCP_AUTH_TYPE=api_key")
```

## How `main.py` uses it

```python
ctx = build_context(argv, base_dir=SRC_DIR)
validate_context(ctx)
ctx.tools_dir.mkdir(parents=True, exist_ok=True)   # auto-create the tools dir
...
app, _mcp = build_app(ctx)
uvicorn.run(app, host=ctx.host, port=ctx.port, log_level="info")
```

## Gotchas / design notes

- `build_context` takes an optional `base_dir` so tests can point it at a
  `tmp_path` instead of the real `src/`.
- A missing `config/.env` is *fine* — the server has no required external
  dependency. Only OS env is needed.
- Backward-compat shim: `MCP_AUTHENTICATION_FLAG=true` maps to
  `auth_type=bearer_jwt` when `MCP_AUTH_TYPE` is unset.
- The full env-var table lives in `config/.env.example`.
