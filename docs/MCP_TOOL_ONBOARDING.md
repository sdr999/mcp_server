# Tool Onboarding — the Azure-sync replacement

`src/main.py` has no remote tool source: there's no file share to drop a
`.py` file into. Instead it exposes an **onboarding endpoint** so a tool
(source + its pip dependencies) can be submitted over HTTP, gated by the
same admin token as the rest of `/admin/*`.

The endpoint has **no hard dependency** of its own: dependency risk scoring
and installation are implemented with the standard library only
(`ast`, `difflib`, `importlib`, `urllib`, `subprocess` via `asyncio`). The
optional PyPI metadata check is best-effort over the network with a short
timeout — if it's unreachable, the server doesn't fail, it just scores the
package more conservatively (see below).

## The flow

```
POST /admin/tools/onboard  { name, source, requirements? }
        │
        ├─ 1. validate name (safe module stem) + source (must parse)
        ├─ 2. detect imports the source needs, merge with declared requirements
        │     (each tagged declared / inferred / guessed)
        ├─ 3. risk-assess every DIRECT dependency
        ├─ 4. resolve + risk-assess the full TRANSITIVE closure
        │     (pip --dry-run --report; network-gated)
        │
        ├─ any dependency (direct OR transitive) is HIGH risk or malformed,
        │  a guessed dependency name isn't allowlisted, the closure can't be
        │  resolved, or auto-install is disabled while a new install is needed
        │        │
        │        └─► held PENDING — nothing installed, nothing loaded
        │            (202 Accepted; appears in GET /admin/tools/pending)
        │
        └─ otherwise
                 │
                 ├─ pip install the missing (low/medium risk) dependencies
                 ├─ on install failure -> also falls back to PENDING
                 ├─ import OFF the serving loop, bounded by the import timeout
                 └─ on success -> tool file is written to the live tools
                    directory and hot-loaded immediately (201 Created);
                    a submission that still fails to load is rolled back and
                    held PENDING with the real reason (never a false success)
```

**Dependency origins.** A requirement is `declared` (listed in
`requirements`), `inferred` (detected from an import with a known
import→distribution mapping, e.g. `import dotenv` → `python-dotenv`), or
`guessed` (detected from an import with no known mapping, so the import name
is used verbatim as the package name). Because import names and PyPI
distribution names frequently differ, a **guessed** dependency that isn't
allowlisted is held pending for an admin to confirm — declare the real
package name explicitly, or add it to the allowlist.

**Transitive closure.** Direct dependencies aren't the whole story: a benign
top-level package can pull in anything. Before installing, onboarding runs
`pip install --dry-run --report` to resolve the complete closure and
risk-assesses every transitively-pulled package too; a high-risk transitive
dependency holds the whole submission. This step needs network access and is
skipped when `MCP_TOOL_RISK_NETWORK_CHECK=false` (offline deployments assess
only the direct, declared/inferred dependencies).

**Concurrency & isolation.** pip subprocesses (resolution + install) are
serialized by an install lock, and tool imports are serialized against the
filesystem-watcher reload via a shared loader lock, so concurrent onboards
can't corrupt the environment or race `importlib`. Pending submissions are
stored with a `.py.pending` suffix so held (unreviewed) code isn't importable
via `sys.path`.

An admin can override either outcome for anything sitting in the pending
queue:

* `GET  /admin/tools/pending/{name}` — full pending record **including the
  held source**, so an admin can review exactly what they're approving.
* `POST /admin/tools/pending/{name}/approve` — force-installs (if needed) and
  loads the submission regardless of its risk score.
* `POST /admin/tools/pending/{name}/reject` — discards the submission.

All routes require `MCP_ADMIN_TOKEN` like the rest of `/admin/*` (disabled with
`503` if unset). In `api_key` mode the `/admin/*` routes are exempt from the
api-key middleware — they carry their own independent admin Bearer token, which
would otherwise collide with the api key on the `Authorization` header. A
separate kill switch, `MCP_TOOL_ONBOARD_ENABLED=false`, turns onboarding off
entirely (`503`) while leaving reload/disable/enable untouched.

### Request shape, conflicts, and limits

`onboard` accepts `{name, source, requirements?, overwrite?}`. Onboarding a
name that already exists as a live tool or a pending submission returns **409**
unless `overwrite: true` is set. An overwrite that fails to load **restores the
previous working version** — a bad update never clobbers a running tool. The
source is capped at 1 MiB and `requirements` at 50 entries (`413` / `400`).

### What gets exposed as a tool (exposure policy & manifest)

A submitted file may contain any number of functions; only the ones **declared
as tools** are registered — the rest stay as ordinary module functions the tool
can call. Which functions count is decided by the authoring contract (see
`MCP_SERVER_FEATURES.md` §1): `@tool(...)`, `TOOLS = [...]`, `register(mcp)`,
or the legacy "function name == file stem" fallback.

For onboarded (over-the-wire) code the legacy fallback is **rejected by
default** (`MCP_TOOL_ONBOARD_REQUIRE_EXPLICIT=true`): a function shouldn't
become a callable tool by filename coincidence. Onboarded files must opt in
explicitly with `@tool` / `TOOLS` / `register`. (The trusted local tools
directory still accepts the legacy convention.)

Every onboard/pending record includes a **`tool_manifest`** — a preview of the
exposed surface, so both the policy and a human reviewer can see exactly what a
file exposes before it goes live:

```jsonc
"tool_manifest": {
  "mechanism": "decorator",
  "tools": [ { "name": "current_weather", "description": "...",
              "mechanism": "decorator", "parameters": { /* JSON schema */ } } ],
  "not_exposed": [ { "function": "_celsius_to_f", "reason": "not decorated with @tool" },
                   { "function": "_fetch_raw",    "reason": "not decorated with @tool" } ],
  "warnings": []
}
```

A file that exposes **no** tool is held pending with an actionable reason that
lists the functions it found (rather than a generic "no valid tools"), and
`MCP_TOOL_ONBOARD_MAX_TOOLS` bounds how many tools one file may expose.

### Signed-tools mode

When `MCP_REQUIRE_SIGNED_TOOLS=true` the loader only accepts files listed in a
trusted manifest, so an onboarded file could never load. Onboarding therefore
rejects up front with a clear `400` rather than silently holding everything
pending — publish through the signed manifest instead.

### Metrics & audit

`/metrics` exposes `mcp_tool_onboards_total{result=...}` (onboarded / pending /
approved / rejected) and a `mcp_tools_pending` gauge. Every onboard / approve /
reject also appends a JSON line to `MCP_TOOL_AUDIT_LOG`
(`logs/onboarding_audit.log` by default): `{ts, action, name, result, detail}`.
The server uses a single shared admin token, so the audit records *what*
happened, not *who* did it — per-admin identity would need per-admin tokens.

## Risk scoring (`plugins/dependency_risk.py`)

Every dependency spec (e.g. `requests==2.31.0`) is scored 0–100 from
independent heuristics:

| Signal | Effect |
|--------|--------|
| Name is on the trusted allowlist | score **0**, short-circuits everything else |
| Name is on the denylist | score **100**, short-circuits everything else |
| Spec doesn't match the strict `name[extras]==version` grammar | score **100** — never passed to pip |
| Already importable locally | **−20** (no install action even needed) |
| Not pinned to an exact version | **+25** |
| Name closely resembles a popular package but isn't an exact match | **+60** (typosquat pattern, e.g. `reqeusts` vs `requests`) |
| *(network)* not found on PyPI | **+70** |
| *(network)* published <30 days ago | **+30** |
| *(network)* fewer than 3 releases ever | **+15** |
| *(network)* lookup failed / unreachable | **+20** (fails conservative, never fails open) |

`score ≥ 50` → **high** (always held pending); `≥ 20` → **medium** (auto-onboards
unless `MCP_TOOL_AUTOINSTALL_DEPS=false`); else **low**.

The spec grammar (`^name(\[extras\])?(==version)?$`) is intentionally strict:
it cannot contain shell metacharacters, `pip` flags, VCS URLs, or `-e`/editable
installs, so a validated spec is always safe to pass to
`pip install <spec>` (invoked via `asyncio.create_subprocess_exec`, never a
shell).

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TOOL_ONBOARD_ENABLED` | `true` | Master switch for the onboarding endpoints. |
| `MCP_TOOL_AUTOINSTALL_DEPS` | `true` | `false` ⇒ any submission needing a new dependency is held pending regardless of its score (tools with zero new deps still onboard immediately). |
| `MCP_TOOL_RISK_NETWORK_CHECK` | `true` | Enables the PyPI metadata lookup. `false` runs fully offline (air-gapped), at the cost of missing the "not on PyPI" / "brand new package" signals. |
| `MCP_TOOL_RISK_NETWORK_TIMEOUT_SEC` | `3` | Timeout for the PyPI lookup. |
| `MCP_TOOL_INSTALL_TIMEOUT_SEC` | `120` | Timeout for the `pip install` subprocess. |
| `MCP_TOOL_DEPENDENCY_ALLOWLIST` | — | Path (relative to `src/`) to a JSON array of extra trusted package names. |
| `MCP_TOOL_DEPENDENCY_DENYLIST` | — | Path (relative to `src/`) to a JSON array of extra denylisted package names. |
| `MCP_TOOL_INSTALL_ONLY_BINARY` | `false` | `true` ⇒ pass `--only-binary :all:` to pip so it never runs a package's `setup.py` during install/resolution. |
| `MCP_TOOL_AUDIT_LOG` | `logs/onboarding_audit.log` | Path (relative to `src/`) for the append-only onboarding audit log. |
| `MCP_TOOL_ONBOARD_REQUIRE_EXPLICIT` | `true` | Require onboarded files to declare tools with `@tool`/`TOOLS`/`register`; reject the legacy filename-match fallback. |
| `MCP_TOOL_ONBOARD_MAX_TOOLS` | `0` | Max tools one onboarded file may expose (`0` = no limit). |

## Example

```bash
ADM=(-H "Authorization: Bearer $MCP_ADMIN_TOKEN" -H "Content-Type: application/json")

# A tool with no new dependencies onboards immediately.
curl -s "${ADM[@]}" -X POST $BASE/admin/tools/onboard -d '{
  "name": "reverse_text",
  "source": "def reverse_text(text: str) -> str:\n    return text[::-1]\n"
}'
# {"name":"reverse_text","status":"onboarded", ...}

# A typosquatted dependency name is held pending, never installed.
curl -s "${ADM[@]}" -X POST $BASE/admin/tools/onboard -d '{
  "name": "typo_tool",
  "source": "def typo_tool():\n    return 1\n",
  "requirements": ["reqeusts==2.0"]
}'
# {"name":"typo_tool","status":"pending","hold_reason":"one or more dependencies were assessed as high risk", ...}

curl -s "${ADM[@]}" $BASE/admin/tools/pending
# {"pending":[{"name":"typo_tool", ...}]}

# An admin reviews it and either approves (forces install+load) or rejects it.
curl -s "${ADM[@]}" -X POST $BASE/admin/tools/pending/typo_tool/reject
curl -s "${ADM[@]}" -X POST $BASE/admin/tools/pending/typo_tool/approve
```

## Self-Healing Tool Onboarding Engine

The server includes an automated **Self-Healing Engine** (`src/plugins/auto_healer.py`) that analyzes submitted tool source code, identifies fixable code or dependency issues, and generates an **Auto-Fix Proposal** with corrected source code and PyPI requirements.

### Self-Healing Capabilities

1. **Comment & Formatting Preservation (Line-Token Rewriting)**:
   - Uses line-token AST position rewriting (`lineno`) instead of standard `ast.unparse`. All user comments, docstring formatting, and code style are preserved 100%.
2. **Missing Import Insertion**:
   - Automatically prepends `from tools_sdk import tool` at line 1 if `@tool` is used or added.
3. **Docstring ➔ Tool Description Auto-Extraction**:
   - Parses function docstrings (e.g. `"""Calculates account balance."""`) and auto-populates `@tool(description="Calculates account balance.")` above target functions.
4. **PyPI Dependency Auto-Inference**:
   - Maps imported modules to PyPI distributions (`yaml` ➔ `pyyaml`, `PIL` ➔ `pillow`, `cv2` ➔ `opencv-python`, `requests` ➔ `requests`, `dotenv` ➔ `python-dotenv`, `fitz` ➔ `pymupdf`, `docx` ➔ `python-docx`, `pptx` ➔ `python-pptx`, `git` ➔ `gitpython`, `dns` ➔ `dnspython`).
5. **Untyped Parameter Auto-Annotation**:
   - Auto-annotates untyped parameters (`arg` ➔ `arg: str`) to ensure FastMCP schema generation succeeds.
6. **Missing Colon Syntax Fix**:
   - Fixes common syntax errors on function definition lines missing trailing colons (`def func()`).

### Self-Healing Endpoints

#### 1. Dry-Run Auto-Fix Proposal (`POST /admin/tools/validate_source`)
Submit source code and optional target `name` to receive a full dry-run analysis and proposal without modifying server state:

```json
POST /admin/tools/validate_source
{
  "name": "get_balance",
  "source": "# Calculate balance\ndef get_balance(user_id: int) -> dict:\n    \"\"\"Calculates account balance.\"\"\"\n    return {'user_id': user_id, 'balance': 100.0}"
}
```

**Response (`200 OK`)**:
```json
{
  "syntax_ok": true,
  "has_autofix": true,
  "original_source": "...",
  "corrected_source": "from tools_sdk import tool\n\n# Calculate balance\n@tool(description=\"Calculates account balance.\")\ndef get_balance(user_id: int) -> dict:\n    \"\"\"Calculates account balance.\"\"\"\n    return {'user_id': user_id, 'balance': 100.0}",
  "suggested_requirements": [],
  "autofix_summary": [
    "Auto-inserted '@tool(description=\"Calculates account balance.\")' decorator above function 'get_balance'.",
    "Added missing 'from tools_sdk import tool' import at top of file."
  ],
  "tools_found": ["get_balance"]
}
```

#### 2. Auto-Healed Onboarding (`POST /admin/tools/onboard`)
Passing `"auto_heal": true` (default in HTTP API) automatically applies `corrected_source` and `suggested_requirements` during onboarding:

```json
POST /admin/tools/onboard
{
  "name": "get_balance",
  "source": "def get_balance(user_id: int) -> dict:\n    return {'balance': 100.0}",
  "auto_heal": true
}
```

#### 3. One-Click Tool Reversion (`POST /admin/tools/{name}/revert`)
Reverts an auto-healed tool back to the exact original Python source code submitted prior to self-healing:

```bash
POST /admin/tools/get_balance/revert
```

---

## What this does *not* do

* It does not sandbox tool **imports** — a submitted module's top-level code
  still runs in-process when it's loaded (same as any file dropped into the
  tools directory today), though the import runs off the serving loop bounded
  by `MCP_TOOL_IMPORT_TIMEOUT_SEC` so it can't freeze the server. Runtime
  **calls** can still be sandboxed per-tool with `MCP_SANDBOX_TOOLS=true` (see
  MCP_SERVER_FEATURES.md §7); this is orthogonal and unaffected by onboarding.
* The transitive-closure assessment covers package **names** (denylist,
  typosquat, allowlist, brand-new/unknown), not the contents of a specific
  release — it is not a malware scanner (see next point).
* It is not a malware scanner. The heuristics catch unpinned dependencies,
  obvious typosquats, brand-new/unknown packages, and denylisted names — not
  a compromised release of an otherwise-legitimate, well-established package.
* `pip install` still runs in the same Python environment as the server
  (there's no per-tool virtualenv). Treat the admin token accordingly — it
  is equivalent to code-execution access on the host.

