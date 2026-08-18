"""Tests for Whitelisted OpenAPI Schema Coercion (Phase 6, Component 5)."""
from __future__ import annotations

import pytest

from src.plugins.openapi_plugin import OpenAPIToolManager


class TestOpenAPISchemaCoercion:
    def test_coerce_string_to_int(self):
        mgr = OpenAPIToolManager(None, None)
        operation = {
            "parameters": [
                {"name": "limit", "in": "query", "schema": {"type": "integer"}}
            ]
        }
        args = {"limit": "50"}
        coerced, fixes = mgr._coerce_arguments(operation, args)
        assert coerced["limit"] == 50
        assert len(fixes) == 1
        assert "to int" in fixes[0]

    def test_coerce_string_to_float(self):
        mgr = OpenAPIToolManager(None, None)
        operation = {
            "parameters": [
                {"name": "price", "in": "query", "schema": {"type": "number"}}
            ]
        }
        args = {"price": "19.99"}
        coerced, fixes = mgr._coerce_arguments(operation, args)
        assert coerced["price"] == 19.99
        assert len(fixes) == 1

    def test_coerce_string_to_bool(self):
        mgr = OpenAPIToolManager(None, None)
        operation = {
            "parameters": [
                {"name": "active", "in": "query", "schema": {"type": "boolean"}}
            ]
        }
        args = {"active": "true"}
        coerced, fixes = mgr._coerce_arguments(operation, args)
        assert coerced["active"] is True
        assert len(fixes) == 1

    def test_coerce_scalar_to_array(self):
        mgr = OpenAPIToolManager(None, None)
        operation = {
            "parameters": [
                {"name": "tags", "in": "query", "schema": {"type": "array"}}
            ]
        }
        args = {"tags": "python"}
        coerced, fixes = mgr._coerce_arguments(operation, args)
        assert coerced["tags"] == ["python"]
        assert len(fixes) == 1
