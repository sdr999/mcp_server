# Action Log — MCP Plugin Refactor & Secure Tool Onboarding

Branch: `claude/mcp-plugin-components-refactor-za9z1p`
Date: 2026-07-20

A chronological record of the work done on this branch: rebuilding
`src/main.py` as a plugin-based MCP tool server, adding a risk-gated tool
onboarding endpoint to replace the removed Azure sync, and a first batch of
hardening fixes from a code review. Newest phase last.

---

## Phase 0 — Setup

- Switched to branch `claude/mcp-plugin-components-refactor-za9z1p`.
- Fetched and merged `origin/mcp`, which brought in the reference material the
  work is based on:
  - `docs/MCP_SERVER_FEATURES.md`, `docs/MCP_AUTH_GUIDE.md`
  - `src/multiple_mcp_main.py` (the Azure-backed "multiple MCP server"),
    `src/tools_sdk.py`, `src/metrics.py`, `src/tool_runner.py`, and the
    existing test suite.
- Installed the runtime dependencies (`fastmcp`, `watchdog`, `python-dotenv`,
  `starlette`, `uvicorn`, `pytest`) plus the local `agentic_framework` /
  `agentic_adapters` wheels, so the server could actually be run and tested.

---

## Phase 1 — Rebuild `src/main.py` as a secure, plugin-based server

**Commit:** `feb13ba` — *Rebuild src/main.py as a secure, plugin-based MCP tool server*

Reproduced the architecture of `multiple_mcp_main.py` (fault-isolated tool
loading, API-key/OAuth auth, admin API, signed-tool manifests, metrics,
subprocess sandboxing) **with no Azure or any remote file-share dependency** —
tools are always served from a local directory with filesystem hot-reload —
and split each concern into its own module under `src/plugins/`.

### Files created

| File | Responsibility |
|------|-----------------|
| `src/plugins/__init__.py` | Package overview. |
| `src/plugins/config.py` | CLI + env parsing into `AppContext`; traversal-safe `--config` path resolution. |
| `src/plugins/signing.py` | Signed-tool manifest (SHA-256 + optional HMAC). |
| `src/plugins/tool_loader.py` | Fault-isolated tool discovery/registration, metrics wrapping, subprocess sandboxing. |
| `src/plugins/watcher.py` | Local filesystem watcher (only source of hot-reload). |
| `src/plugins/notifications.py` | Best-effort `tools/list_changed` push. |
| `src/plugins/security.py` | FastMCP + JWT verifier, API-key middleware, admin-token guard. |
| `src/plugins/routes.py` | `/healthz`, `/readyz`, `/status`, `/tools`, `/metrics`, `/admin/*`. |
| `src/plugins/cli.py` | `--validate` / `--sign` utilities. |
| `src/plugins/app.py` | Wires the plugins into one ASGI app + lifespan. |
| `src/tools/text_analyzer.py` | Sample tool (migrated from the old inline demo) using the `@tool` contract. |
| `docs/MCP_MAIN_SERVER.md` | Documents the new server and how it differs from `multiple_mcp_main.py`. |

### Files modified

- `src/main.py` — reduced to a thin, side-effect-free entry point delegating to the plugins.
- `requirements.txt` — pinned the MCP server dependencies.
- `docs/MCP_SERVER_FEATURES.md` — cross-linked the new server doc.
- `.gitignore` — added (`__pycache__`, `.env`, `.pytest_cache`, etc.).

### Behavioural differences from `multiple_mcp_main.py`

- No Azure config is read; `/status` always reports `"source": "local"`.
- `POST /admin/resync` returns `409` (nothing to resync; the watcher covers local edits).

### Tests added

- `src/tests/test_plugins_config.py` — env precedence, safe `--config` resolution.
- `src/tests/test_plugins_tool_loader.py` — signing, disable/enable, fault isolation, sandbox.
- `src/tests/test_main_server.py` — in-process ASGI integration (boot, readiness, auth matrix, admin).

### Verification

- 25 tests passing.
- `--validate` CI gate exercised.
- Live server run (`curl` against `/healthz`, `/readyz`, `/status`, `/tools`,
  `/metrics`, `/admin/resync`) — auth and admin behaviour confirmed.

---

## Phase 2 — Risk-gated tool onboarding endpoint

**Commit:** `3177bcc` — *Add risk-gated tool onboarding endpoint (Azure sync replacement)*

Since there is no remote tool source, added an HTTP endpoint to submit a tool
(source + pip dependencies), gated by the existing admin token. Dependencies
are **risk-scored with no new hard dependency** (stdlib heuristics + a
best-effort PyPI check): low/medium risk auto-installs and hot-loads; high
risk (or any malformed spec, or auto-install disabled) is **held pending** for
an admin to approve or reject.

### Files created

| File | Responsibility |
|------|-----------------|
| `src/plugins/dependency_risk.py` | Stdlib-only risk scoring: allow/deny lists, version pinning, typosquat similarity, best-effort PyPI metadata (fails conservative, never open). Import→package name map + missing-import detection. |
| `src/plugins/onboarding.py` | `OnboardingManager`: validate → assess → install-or-hold → load; pending store; `approve` / `reject`. |
| `docs/MCP_TOOL_ONBOARDING.md` | Documents the flow, risk table, config knobs, and limitations. |
| `src/tests/test_plugins_dependency_risk.py` | Risk heuristics (offline/deterministic). |
| `src/tests/test_plugins_onboarding.py` | Onboard/approve/reject/pending flow. |

### Files modified

- `src/plugins/routes.py` — added `POST /admin/tools/onboard`,
  `GET /admin/tools/pending`, `POST /admin/tools/pending/{name}/approve`,
  `POST /admin/tools/pending/{name}/reject`.
- `src/plugins/config.py` — 7 new `MCP_TOOL_ONBOARD_*` / risk config knobs on `AppContext`.
- `src/plugins/app.py` — construct and wire the `OnboardingManager`.
- `src/main.py`, `docs/MCP_MAIN_SERVER.md`, `.gitignore` — docstring, endpoint table, ignore runtime pending dir.

### Security properties

- Strict `name[extras]==version` spec grammar — no shell metacharacters,
  flags, VCS URLs, or editable installs can reach `pip`.
- `pip install` runs via `asyncio.create_subprocess_exec` (never a shell),
  only after every spec passes the grammar.
- All admin routes gated by `MCP_ADMIN_TOKEN`; kill switches
  `MCP_TOOL_ONBOARD_ENABLED` / `MCP_TOOL_AUTOINSTALL_DEPS`.

### Verification

- 54 tests passing (34 new).
- Live server run: onboarded a dependency-free tool immediately; held a
  denylisted typosquat (`reqeusts`) pending; rejected it; onboarded a tool
  with an already-installed low-risk dependency.

---

## Phase 3 — Code review (SDE-3) + Batch 1 hardening

Reviewed the onboarding implementation and produced a prioritized plan of
~20 issues/edge-cases/improvements across P0–P2. Two P0 bugs were confirmed by
running throwaway scripts against the real code before any fix:

1. **Denylist bypass via name normalization** — `evil_pkg` scored *low*
   against a denylist containing `evil-pkg` (same PyPI distribution).
2. **False `"onboarded"` status** — a source that parsed but registered no
   tool still returned `201 {"status":"onboarded"}` while `/tools` was empty.

Then implemented **Batch 1** of the plan.

**Commit:** `0d7d000` — *Harden tool onboarding: normalization, truthful load, timeout, install cache*

### Fixes

| # | Fix | Where |
|---|-----|-------|
| 1 | PEP 503 `canonical_name()` on all allow/deny/typosquat comparisons + declared-vs-inferred dedup | `dependency_risk.py`, `onboarding.py` |
| 2 | Truthful load result: `ToolLoader.module_outcome()`; failed brand-new submissions roll back; `unload_module` clears stale failure records | `tool_loader.py`, `onboarding.py` |
| 4 | Submitted code imported **off-loop, bounded by `MCP_TOOL_IMPORT_TIMEOUT_SEC`** (was inline on the serving loop) | `onboarding.py`, `app.py` |
| 5 | `importlib.invalidate_caches()` after a successful pip install | `onboarding.py` |
| 11 (partial) | Shared `asyncio.Lock` serializing tool imports between the reload drain and onboarding | `app.py`, `onboarding.py` |

**Why the lock was pulled in early:** fix #4 made the off-loop import `await`,
which let the filesystem watcher's drain import the *same module* concurrently
in another executor thread and race `importlib` (a real `KeyError` observed
mid-work). The lock makes the two mutually exclusive.

### Files modified

- `src/plugins/dependency_risk.py` — `canonical_name()`; canonicalize sets/keys/typosquat/`spec_name`/`load_name_set`.
- `src/plugins/onboarding.py` — async `_write_live` (off-loop + timeout + rollback + truthful outcome), `import_timeout`, shared lock, `invalidate_caches`, truthful `approve`.
- `src/plugins/tool_loader.py` — `invalidate()`, `module_outcome()`, `unload_module` clears `_failures`.
- `src/plugins/app.py` — create shared `loader_lock`, thread it into the drain and onboarding.
- `src/tests/test_plugins_dependency_risk.py`, `src/tests/test_plugins_onboarding.py` — 7 regression tests.

### Verification against real conditions (live server run)

| Check | Result |
|-------|--------|
| Real pip install + in-process import (#5) | `inflection` went absent → installed; tool imported it immediately |
| Truthful outcome (#2) | import-error & no-tool sources held pending with the real reason, rolled back; `/status` `failed_modules: 0` |
| Hang isolation (#4) | `/healthz` returned 200 on **12/12** probes while a submitted `sleep(30)` import was bounded out at 2s |
| Concurrency lock | two simultaneous onboards both loaded; no import race in the log |
| Normalization bypass (#1) | denylist `evil-pkg` (loaded from a real config file) caught `evil_pkg==1.0` → high/pending/not installed |
| Approve truthful failure | approving a still-failing tool stayed pending → HTTP 502 |

Environment restored afterward (test tool files removed, `inflection` uninstalled).

- Full plugin suite: **61 tests passing.**

---

## Phase 4 — Batch 2 hardening (supply-chain + isolation)

**Commit:** `5502fc0` — *Batch 2: transitive-closure risk, guessed-dep gating, isolated pending store*

### Fixes

| # | Fix | Where |
|---|-----|-------|
| 3 | **Transitive-closure assessment**: resolve `pip install --dry-run --report` and risk-assess every transitively-pulled package before installing; a high-risk transitive dep holds the whole submission (network-gated). | `onboarding.py` (`_pip_resolve_closure`) |
| 6 | **Declared/inferred/guessed origins**: `classify_import()` distinguishes reliable import→dist mappings from guesses; a guessed, non-allowlisted dependency is held for admin confirmation. | `dependency_risk.py`, `onboarding.py` |
| 10 | **Non-importable pending store**: held submissions are stored as `{name}.py.pending`, so unreviewed code under a sys.path dir can't be imported. | `onboarding.py` |
| 11 (rest) | **Serialize concurrent pip**: an install lock guards resolve + install so two onboards don't run pip against the same env at once. | `onboarding.py` |

### Files modified

- `src/plugins/dependency_risk.py` — `classify_import()`; `origin` field on `RiskReport` threaded through `assess_requirement`.
- `src/plugins/onboarding.py` — `_pip_resolve_closure`, closure gating, guessed-dep gate, `_install_lock`, `.py.pending` store, origin-tagged `_build_specs`.
- `src/tests/test_plugins_onboarding.py` — 6 new tests (closure high-risk/clean/unresolvable, guessed gating, pending-store isolation).
- `docs/MCP_TOOL_ONBOARDING.md` — flow diagram, origins, closure, concurrency/isolation, updated caveats.

### Verification against real conditions (live server run)

| Check | Result |
|-------|--------|
| Transitive gating (#3) | `python-slugify` (clean) held pending because its real transitive `text-unidecode` was denylisted; **nothing installed** |
| Clean closure (#3) | real `pip --dry-run` resolved the closure, both packages installed, tool loaded |
| Guessed dep (#6) | `import someobscurelib` held pending with the "declare or allowlist" reason; nothing installed |
| Pending store (#10) | stored as `heldtool.py.pending`; `import tools_pending.heldtool` fails |
| Concurrent installs (#11) | two simultaneous onboards each did a real pip install (humanize + inflection); both succeeded, no race in the log |

- Full plugin suite: **67 tests passing** (6 new).

---

## Phase 5 — Batch 3 + 4 hardening (finish all remaining review items)

**Commit:** `c3271f0` — *Batch 3+4: finish onboarding hardening (auth, conflicts, limits, metrics, audit)*

Implemented every remaining item from the review in one pass.

### Fixes

| # | Fix | Where |
|---|-----|-------|
| 7 | **Signed-tools mode rejects onboarding up front** (`400`) instead of silently holding everything pending. | `onboarding.py` |
| 8 | **Overwrite/conflict**: duplicate name → `409` unless `overwrite:true`; a failed overwrite **restores the previous working version**. | `onboarding.py`, `routes.py` |
| 9 | **Name validation** in `approve`/`reject` (via `get_pending`). | `onboarding.py` |
| 12 | **`/admin/*` exempt from the api-key middleware** — admin routes carry their own token, fixing the `Authorization`-header collision that made them unreachable in `api_key` mode. | `security.py` |
| 13 | **Request-size limits**: source ≤ 1 MiB (`413`), ≤ 50 requirements (`400`), Content-Length pre-check. | `routes.py`, `onboarding.py` |
| 14 | `urllib.parse.quote` (fragile `urllib.request.quote` removed) + **mocked PyPI-lookup tests**. | `dependency_risk.py` |
| 15 | **Disabled onboarding → `503`** (was a generic `400`). | `routes.py` |
| 16 | **Metrics**: `mcp_tool_onboards_total{result}` counter + `mcp_tools_pending` gauge. | `onboarding.py`, `routes.py` |
| 17 | **Audit trail**: append-only JSON-lines log per onboard/approve/reject (`MCP_TOOL_AUDIT_LOG`). | `onboarding.py`, `config.py` |
| 18 | **`.env.example`** documents all `MCP_TOOL_*` onboarding/risk/install/audit knobs. | `config/.env.example` |
| 19 | **`GET /admin/tools/pending/{name}`** detail endpoint (includes held source). | `routes.py`, `onboarding.py` |
| 20 | **Install hardening**: `MCP_TOOL_INSTALL_ONLY_BINARY` → `pip --only-binary :all:` (no `setup.py` execution). | `onboarding.py`, `config.py` |

### Files modified

- `src/plugins/onboarding.py` — `OnboardingConflict`, overwrite + restore-on-failure, signed-mode reject, `_hold`/metrics/audit, `pending_count`/`get_pending_detail`, `only_binary` threading, name validation.
- `src/plugins/routes.py` — onboard route (503/413/400/409, overwrite), pending-detail route, onboarding metric registration.
- `src/plugins/security.py` — exempt `/admin/*` from api-key middleware.
- `src/plugins/dependency_risk.py` — `urllib.parse.quote`.
- `src/plugins/config.py` — `onboard_only_binary`, `onboard_audit_log`.
- `src/config/.env.example` — new onboarding section.
- `docs/MCP_TOOL_ONBOARDING.md` — detail endpoint, conflicts/limits, signed-mode, metrics/audit, config table.
- Tests: 20 new across `test_plugins_onboarding.py`, `test_plugins_dependency_risk.py`, `test_main_server.py`.

### Verification against real conditions (live server runs)

| Check | Result |
|-------|--------|
| Conflict/overwrite (#8) | duplicate → `409`; `overwrite:true` → `201` |
| Size limit (#13) | 1 MiB+ source → `413` |
| Pending detail (#19) | `GET /admin/tools/pending/{name}` returned the held source |
| Metrics (#16) | `/metrics` showed `mcp_tool_onboards_total{onboarded,pending,rejected}` + `mcp_tools_pending` gauge |
| Audit (#17) | `logs/onboarding_audit.log` recorded each onboard/reject as JSON lines |
| Disabled (#15) | onboard → `503` |
| Signed mode (#7) | onboard → `400` with clear message |
| api_key admin (#12) | `/status` needs api key (401→200); `/admin/resync` reachable with admin token (`409`), wrong token `401` |
| only-binary (#20) | wheel install of `inflection` succeeded with `--only-binary :all:` |

- Full plugin suite: **90 tests passing** (23 new).

### Review status: all items #1–#20 complete.

---

## Phase 6 — Tool exposure policy & manifest (explicit opt-in)

Prompted by the question "if a file has 3 functions (1 tool + 2 helpers),
what gets onboarded?". The answer exposed a deeper design weakness: tool
resolution for onboarded files was implicit, unreviewable, and over-exposed
via the legacy filename-match fallback. Solved as a small architecture change.

**Commit:** `5e255bf` — *Tool exposure policy + manifest: explicit opt-in for onboarded tools*

### Changes

| Area | Change |
|------|--------|
| Explainable resolver | `ToolLoader._resolve_with_report()` returns a `ResolutionReport` (winning mechanism, functions seen, selected, per-exclusion reasons, warnings) alongside the resolved tools. Registration behavior unchanged; the report rides on `_LoadPlan.resolution`. |
| Tool manifest (preview) | Onboarding builds a `tool_manifest` from the plan — `{mechanism, tools:[{name,description,parameters}], not_exposed:[{function,reason}], warnings}` — and attaches it to every onboard/pending record and the pending-detail endpoint. Reviewers see exactly what a file exposes vs. keeps private. |
| Exposure policy | For onboarded files, `MCP_TOOL_ONBOARD_REQUIRE_EXPLICIT=true` (default) rejects the legacy filename-match fallback — tools must opt in with `@tool`/`TOOLS`/`register`. `MCP_TOOL_ONBOARD_MAX_TOOLS` bounds the surface. Policy is enforced at the onboarding boundary (pre-commit); the shared loader and the trusted local dir keep legacy support. |
| Actionable feedback | A file exposing no tool is held pending with a message listing the functions it found and how to declare one, instead of a generic "no valid tools". |

### Files modified

- `src/plugins/tool_loader.py` — `ResolutionReport`, `_resolve_with_report`, `_functions_defined_in`, `resolution` on `_LoadPlan`.
- `src/plugins/onboarding.py` — `_build_manifest`, `_exposure_violation`, policy-gated `_write_live`/`_load_locked` (commit only after policy passes), `require_explicit`/`max_tools`, manifest in records.
- `src/plugins/config.py`, `src/plugins/app.py` — two new knobs threaded through.
- `docs/MCP_TOOL_ONBOARDING.md`, `src/config/.env.example` — exposure policy + manifest docs.
- Tests: 9 new (manifest content incl. the 3-function scenario, legacy rejection, relaxed-policy legacy, no-tool actionable message, max-tools, TOOLS-shadowing warning, HTTP manifest surfacing). Existing legacy-source tests migrated to explicit `@tool`.

### Verification against real conditions (live server)

| Check | Result |
|-------|--------|
| 3-function file (1 `@tool` + 2 helpers) | onboarded; manifest exposed `current_weather` (with `city` param schema), `not_exposed` listed both helpers; catalog showed only the one tool |
| Legacy filename-match under strict default | held pending with the "opt in explicitly" reason |
| File exposing no tool | held pending listing `helper_a, helper_b, do_weather` + how to declare one |
| Pending detail | returns both source and `tool_manifest` for review |

- Full plugin suite: **98 tests passing** (9 new).

---

## Commit summary

| Commit | Summary |
|--------|---------|
| `feb13ba` | Rebuild `src/main.py` as a secure, plugin-based MCP tool server (no Azure). |
| `3177bcc` | Add risk-gated tool onboarding endpoint (Azure sync replacement). |
| `0d7d000` | Harden tool onboarding: normalization, truthful load, timeout, install cache (Batch 1). |
| `5502fc0` | Batch 2: transitive-closure risk, guessed-dep gating, isolated pending store. |
| `c3271f0` | Batch 3+4: signed-mode reject, conflicts/overwrite, limits, api-key admin fix, metrics, audit, only-binary. |
| `5e255bf` | Tool exposure policy + manifest: explicit opt-in for onboarded tools. |

Pushed to `origin/claude/mcp-plugin-components-refactor-za9z1p`.
