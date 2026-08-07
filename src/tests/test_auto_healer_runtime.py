"""Unit tests for AutoHealer runtime failure interception."""
from __future__ import annotations

from src.plugins.auto_healer import AutoHealer


def test_intercept_runtime_name_error():
    healer = AutoHealer()
    code = """def process_data(data):
    return json.dumps(data)
"""
    tb = "NameError: name 'json' is not defined"
    res = healer.intercept_runtime_failure(tool_name="process_data", traceback_str=tb, source_code=code)

    assert res is not None
    assert res.has_autofix is True
    assert "import json" in res.corrected_source
    assert len(res.fixes_applied) > 0


def test_intercept_runtime_module_not_found():
    healer = AutoHealer()
    code = """import yaml

def parse_yaml(data):
    return yaml.safe_load(data)
"""
    tb = "ModuleNotFoundError: No module named 'yaml'"
    res = healer.intercept_runtime_failure(tool_name="parse_yaml", traceback_str=tb, source_code=code)

    assert res is not None
    assert "pyyaml" in res.suggested_requirements
    assert len(res.suggested_requirements) > 0
