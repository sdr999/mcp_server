"""Regression tests for the grade3 baseline review fixes."""
from __future__ import annotations

from plugins.prompts.repository import PromptRepository, _version_key
from plugins.prompts.ab_testing import ABTestManager
from plugins.intelligence.log_search import LogSearchIndex


# -- #4: semver "latest" ordering, not lexicographic -----------------------

def test_get_prompt_latest_is_semver_ordered():
    repo = PromptRepository()
    repo.register_prompt("p", "old", version="v1.9.0")
    repo.register_prompt("p", "new", version="v1.10.0")
    # lexicographic sort would wrongly pick v1.9.0
    assert repo.get_prompt("p")["version"] == "v1.10.0"
    assert repo.get_prompt("p")["template"] == "new"


def test_version_key_numeric():
    assert _version_key("v1.10.0") > _version_key("v1.9.0")
    assert _version_key("v2.0.0") > _version_key("v1.99.99")


# -- #7: A/B allocation is unbiased across variants ------------------------

def test_ab_selection_is_deterministic_and_uses_all_variants():
    ab = ABTestManager()
    variants = {"a": "A", "b": "B", "c": "C"}   # 3 doesn't divide 100 evenly
    # deterministic per (tenant, prompt)
    k1, _ = ab.select_variant("tenantX", "greet", variants)
    k2, _ = ab.select_variant("tenantX", "greet", variants)
    assert k1 == k2
    # every variant is reachable across many tenants (old %100 skewed away from 'c')
    seen = {ab.select_variant(f"t{i}", "greet", variants)[0] for i in range(300)}
    assert seen == {"a", "b", "c"}


# -- #3: dict payload secrets are redacted before indexing -----------------

def test_log_search_redacts_secret_valued_keys():
    idx = LogSearchIndex()
    idx.add_execution_log(
        tool_name="login", status="ok", duration_sec=0.1,
        input_payload={"user": "alice", "password": "hunter2", "api_key": "sk-SECRETVALUE123"})
    hit = idx.search("login")[0]
    blob = hit["input"] + hit["output"] + hit["error"]
    assert "hunter2" not in blob
    assert "sk-SECRETVALUE123" not in blob
    assert "[REDACTED]" in blob
