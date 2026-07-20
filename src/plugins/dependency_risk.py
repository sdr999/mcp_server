"""Dependency risk assessment for tool onboarding.

No hard dependency: everything here is stdlib-only (``ast``, ``difflib``,
``importlib``, ``urllib``). The optional PyPI metadata lookup is best-effort
over the network with a short timeout; any failure degrades to a
conservative (higher) risk score rather than raising, so this module never
requires network access to function -- it is simply less precise without it.

A requirement is scored on a 0..100 axis from a handful of independent
heuristics (each adds/subtracts points; never a single hard "yes/no" test
except the explicit allow/deny lists and a malformed spec):

* allowlisted name                      -> score 0, short-circuits everything else
* denylisted name                       -> score 100, short-circuits everything else
* malformed / unsafe spec string        -> score 100 (never installed)
* already importable locally            -> -20 (no install action even needed)
* not pinned to an exact version        -> +25
* name closely resembles a popular      -> +60 (classic typosquat pattern)
  package but isn't an exact match
* (network) not found on PyPI           -> +70
* (network) published <30 days ago      -> +30
* (network) fewer than 3 releases ever  -> +15
* (network) lookup failed/unavailable   -> +20 (fail conservative, not fail open)

Score >= HIGH_THRESHOLD -> "high"; >= MEDIUM_THRESHOLD -> "medium"; else "low".
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import List, Optional, Set

log = logging.getLogger("MCP_logger")

HIGH_THRESHOLD = 50
MEDIUM_THRESHOLD = 20

# A conservative default allowlist of common, well-known packages. Deployments
# extend/replace this via config/tool_dependency_allowlist.json (one package
# name per array entry, case-insensitive).
DEFAULT_ALLOWLIST = {
    "requests", "httpx", "pydantic", "pyyaml", "python-dateutil", "numpy",
    "pandas", "beautifulsoup4", "aiohttp", "boto3", "jinja2", "click",
}

# A small built-in denylist of names known to have been used for typosquatting
# / malicious uploads targeting popular packages. Not exhaustive -- deployments
# should extend this via config/tool_dependency_denylist.json.
DEFAULT_DENYLIST = {
    "reqeusts", "requessts", "python3-dateutil", "crypt", "colourama",
}

# Reference set of popular package names for typosquat similarity checks.
POPULAR_PACKAGES = DEFAULT_ALLOWLIST | {
    "flask", "django", "scipy", "matplotlib", "scikit-learn", "torch",
    "tensorflow", "pillow", "cryptography", "sqlalchemy", "urllib3",
    "certifi", "idna", "setuptools", "wheel", "pip", "six", "attrs",
}

# name[extras]==version -- deliberately strict so a spec can never smuggle
# shell metacharacters, flags, URLs, or VCS refs into a pip invocation.
_SPEC_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9._-]{0,213})"
    r"(?P<extras>\[[A-Za-z0-9,_-]{1,100}\])?"
    r"(==(?P<version>[A-Za-z0-9][A-Za-z0-9._+*!-]{0,49}))?$"
)


#: Import name -> PyPI distribution name, for the common cases where they
#: differ. Not exhaustive; unknown imports are assessed under their own name.
IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml", "bs4": "beautifulsoup4", "PIL": "pillow",
    "cv2": "opencv-python", "sklearn": "scikit-learn", "dotenv": "python-dotenv",
    "jwt": "pyjwt",
}


def resolve_import_name(module_name: str) -> str:
    return IMPORT_TO_PACKAGE.get(module_name, module_name)


@dataclass
class RiskReport:
    spec: str
    name: str
    version_pin: Optional[str]
    score: int
    level: str  # "low" | "medium" | "high"
    reasons: List[str] = field(default_factory=list)
    valid: bool = True
    already_installed: bool = False


def spec_name(spec: str) -> str:
    """Best-effort package-name extraction from a requirement spec, for
    dedup/lookup purposes. Returns the lowercased raw spec if it doesn't
    match the strict spec grammar (callers should treat that as untrusted)."""
    m = _SPEC_RE.match((spec or "").strip())
    return m.group("name").lower() if m else spec.strip().lower()


def _level_for(score: int) -> str:
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def load_name_set(path: Optional[Path], default: Set[str]) -> Set[str]:
    if not path or not path.exists():
        return {n.lower() for n in default}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(n).strip().lower() for n in data if str(n).strip()}
    except Exception as exc:
        log.error("Could not read %s; falling back to built-in defaults: %s", path, exc)
        return {n.lower() for n in default}


def _pypi_lookup(name: str, timeout: float) -> Optional[dict]:
    """Best-effort metadata fetch. Returns None on ANY failure (network down,
    404, malformed JSON, timeout, ...) -- callers treat None conservatively."""
    url = f"https://pypi.org/pypi/{urllib.request.quote(name)}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310 - fixed https host
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def assess_requirement(
    spec: str,
    *,
    allowlist: Optional[Set[str]] = None,
    denylist: Optional[Set[str]] = None,
    network_check: bool = True,
    network_timeout: float = 3.0,
) -> RiskReport:
    """Score a single pip requirement spec (e.g. ``"requests==2.31.0"``)."""
    spec = (spec or "").strip()
    allowlist = allowlist if allowlist is not None else {n.lower() for n in DEFAULT_ALLOWLIST}
    denylist = denylist if denylist is not None else {n.lower() for n in DEFAULT_DENYLIST}

    m = _SPEC_RE.match(spec)
    if not m:
        return RiskReport(spec=spec, name=spec, version_pin=None, score=100, level="high",
                           reasons=["malformed or unsafe requirement spec"], valid=False)

    name = m.group("name")
    version = m.group("version")
    key = name.lower()
    reasons: List[str] = []
    score = 0

    if key in allowlist:
        return RiskReport(spec=spec, name=name, version_pin=version, score=0, level="low",
                           reasons=["package is on the trusted allowlist"])

    if key in denylist:
        return RiskReport(spec=spec, name=name, version_pin=version, score=100, level="high",
                           reasons=["package name is on the denylist"])

    already_installed = False
    try:
        already_installed = find_spec(name.replace("-", "_")) is not None or find_spec(name) is not None
    except (ImportError, ValueError):
        already_installed = False
    if already_installed:
        score -= 20
        reasons.append("already installed locally; no new install action required")

    if not version:
        score += 25
        reasons.append("dependency is unpinned (no exact ==version)")

    close = difflib.get_close_matches(key, POPULAR_PACKAGES, n=1, cutoff=0.82)
    if close and close[0] != key:
        score += 60
        reasons.append(f"name closely resembles popular package {close[0]!r} (possible typosquat)")

    if network_check:
        meta = _pypi_lookup(name, network_timeout)
        if meta is None:
            score += 20
            reasons.append("could not verify package via PyPI (network unavailable or lookup failed); treated conservatively")
        else:
            releases = meta.get("releases", {}) or {}
            if not releases:
                score += 70
                reasons.append("package not found on PyPI (no releases)")
            else:
                if len(releases) < 3:
                    score += 15
                    reasons.append("package has very few releases on PyPI")
                earliest = None
                for files in releases.values():
                    for f in files:
                        ts = f.get("upload_time_iso_8601")
                        if ts and (earliest is None or ts < earliest):
                            earliest = ts
                if earliest:
                    import datetime
                    try:
                        published = datetime.datetime.fromisoformat(earliest.replace("Z", "+00:00"))
                        age_days = (datetime.datetime.now(datetime.timezone.utc) - published).days
                        if age_days < 30:
                            score += 30
                            reasons.append(f"package was first published only {age_days} day(s) ago")
                    except ValueError:
                        pass

    score = max(0, score)
    return RiskReport(spec=spec, name=name, version_pin=version, score=score, level=_level_for(score),
                       reasons=reasons, already_installed=already_installed)


def stdlib_and_installed(module_name: str) -> bool:
    root = module_name.split(".")[0]
    if root in sys.stdlib_module_names or root in sys.builtin_module_names:
        return True
    try:
        return find_spec(root) is not None
    except (ImportError, ValueError):
        return False


def detect_missing_imports(source: str) -> List[str]:
    """Parse ``source`` and return top-level module names imported but not
    already resolvable (stdlib or already installed). Best-effort: a source
    file that fails to parse yields an empty list (the loader's own syntax
    check will surface the error separately)."""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])

    return sorted(name for name in found if not stdlib_and_installed(name))
