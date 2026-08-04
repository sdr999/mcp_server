# 06 — Dependency Risk (`plugins/dependency_risk.py`)

**Job:** decide how risky a pip dependency is, using stdlib-only heuristics
plus a best-effort PyPI lookup. **No hard dependency** — `ast`, `difflib`,
`importlib`, `urllib`. When offline, it's *less precise*, never broken.

Used by onboarding (doc 07) to gate installs. Everything here is a pure
function of its inputs (except the optional network call), so it's fully
unit-testable offline.

## The scoring model

A requirement spec (`requests==2.31.0`) is scored 0–100 by independent
heuristics that add/subtract points; two lists short-circuit.

| Signal | Effect |
|--------|--------|
| Name on the allowlist | score **0**, done |
| Name on the denylist | score **100**, done |
| Spec fails the strict grammar | score **100** — never passed to pip |
| Already importable locally | **−20** |
| Not pinned (`==`) | **+25** |
| Name ≈ a popular package but not exact | **+60** (typosquat) |
| *(net)* not on PyPI | **+70** |
| *(net)* published <30 days ago | **+30** |
| *(net)* <3 releases | **+15** |
| *(net)* lookup failed | **+20** (conservative, never fail-open) |

`score ≥ 50` → **high**, `≥ 20` → **medium**, else **low**.

## The strict spec grammar (injection defense)

The single most important line: a spec that reaches `pip install` must match a
grammar that **cannot** contain shell metacharacters, flags, URLs, or VCS/`-e`
refs. Anything else scores 100 and is rejected before pip ever sees it.

```python
_SPEC_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9._-]{0,213})"
    r"(?P<extras>\[[A-Za-z0-9,_-]{1,100}\])?"
    r"(==(?P<version>[A-Za-z0-9][A-Za-z0-9._+*!-]{0,49}))?$"
)
```

## PEP 503 name canonicalization (bypass defense)

`evil-pkg`, `evil_pkg`, and `Evil.Pkg` are the *same* PyPI distribution. Naive
lowercasing lets a denylisted `evil-pkg` slip through as `evil_pkg`. So all
allow/deny/typosquat comparisons canonicalize first.

```python
def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()
```

```python
allow = {canonical_name(n) for n in raw_allow}
deny  = {canonical_name(n) for n in raw_deny}
key = canonical_name(name)
if key in allow: return RiskReport(..., score=0, level="low", ...)
if key in deny:  return RiskReport(..., score=100, level="high", ...)
```

## Best-effort PyPI lookup (fails conservative)

The network call returns `None` on *any* failure (down, 404, timeout, bad
JSON). Callers treat `None` as "couldn't verify → add risk", never "assume
fine". Note `urllib.parse.quote` (not the fragile `urllib.request.quote`).

```python
def _pypi_lookup(name: str, timeout: float) -> Optional[dict]:
    url = f"https://pypi.org/pypi/{urllib.parse.quote(name, safe='')}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
```

```python
if network_check:
    meta = _pypi_lookup(name, network_timeout)
    if meta is None:
        score += 20
        reasons.append("could not verify package via PyPI ...; treated conservatively")
    else:
        releases = meta.get("releases", {}) or {}
        if not releases:
            score += 70; reasons.append("package not found on PyPI (no releases)")
        ...
```

## Import → distribution mapping & origin classification

Onboarding also *infers* dependencies from `import` statements in the source.
`detect_missing_imports` finds top-level imports that aren't stdlib/installed;
`classify_import` decides whether the mapping is reliable.

```python
def classify_import(module_name: str) -> Tuple[str, str]:
    # "inferred" — reliable mapping (dotenv → python-dotenv)
    # "guessed"  — import name used verbatim (may not be the real PyPI name)
    if module_name in IMPORT_TO_PACKAGE:
        return IMPORT_TO_PACKAGE[module_name], "inferred"
    return module_name, "guessed"
```

That `origin` rides on the `RiskReport` and drives policy: a **guessed**,
non-allowlisted dependency is held for admin confirmation (doc 07), because the
import name and the PyPI distribution name frequently differ.

```python
@dataclass
class RiskReport:
    spec: str; name: str; version_pin: Optional[str]
    score: int; level: str
    reasons: List[str] = field(default_factory=list)
    valid: bool = True
    already_installed: bool = False
    origin: str = "declared"        # declared | inferred | guessed | transitive
```

## Gotchas / design notes

- The heuristics catch *names* (typosquats, brand-new/unknown, denylisted), not
  a compromised release of a legitimate package — this is not a malware scanner.
- Allow/deny lists are extended from JSON files via `load_name_set` (also
  canonicalized) — see `MCP_TOOL_DEPENDENCY_ALLOWLIST/DENYLIST`.
- Offline mode (`network_check=False`) simply skips the network signals; the
  allowlist/denylist/pin/typosquat checks still work.
