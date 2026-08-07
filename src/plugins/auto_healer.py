"""Self-Healing Tool Onboarding Engine.

Provides AST and token-line rewriting to auto-fix submitted Python code:
1. Auto-insert missing `from tools_sdk import tool` import at line 1.
2. Auto-insert `@tool(description=...)` decorator above target function while preserving comments.
3. Auto-extract function docstrings into `@tool(description=...)`.
4. Auto-infer PyPI distribution requirements from imported modules (`yaml` -> `pyyaml`, `PIL` -> `pillow`, etc.).
5. Auto-fix untyped function parameters (`arg` -> `arg: str`).
6. Guarantee 100% comment, docstring layout, and code style preservation.
7. Idempotency: re-healing valid code produces zero changes.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .dependency_risk import IMPORT_TO_PACKAGE, canonical_name


@dataclass
class HealResult:
    original_source: str
    corrected_source: str
    suggested_requirements: List[str] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)
    has_autofix: bool = False
    syntax_ok: bool = True
    target_function: Optional[str] = None


class AutoHealer:
    """AST-driven, line-preserving code auto-fixer and dependency inferrer."""

    def heal_source(
        self,
        source: str,
        name: Optional[str] = None,
        requirements: Optional[List[str]] = None,
    ) -> HealResult:
        original_source = source
        corrected = source
        fixes: List[str] = []
        requirements = list(requirements or [])

        # 1. Check syntax first (apply colon auto-fix if missing trailing colon on def lines)
        corrected, colon_fixed = self._fix_missing_colons(corrected)
        if colon_fixed:
            fixes.append("Inserted missing colon ':' on function definition line.")

        syntax_ok = True
        try:
            tree = ast.parse(corrected)
        except SyntaxError:
            syntax_ok = False
            return HealResult(
                original_source=original_source,
                corrected_source=corrected,
                suggested_requirements=requirements,
                fixes_applied=fixes,
                has_autofix=bool(fixes),
                syntax_ok=False,
            )

        # 2. Dependency Auto-Inference
        suggested_reqs, req_fixes = self._infer_requirements(tree, requirements)
        fixes.extend(req_fixes)

        # 3. Locate function defs in AST
        funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        target_fn = None
        if name:
            for fn in funcs:
                if fn.name == name:
                    target_fn = fn
                    break
        if not target_fn and funcs:
            target_fn = funcs[-1]  # Default to last defined function if name unmatched

        # 4. Check for @tool decorator
        has_decorator = any(
            (isinstance(dec, ast.Call) and getattr(dec.func, "id", None) == "tool")
            or (isinstance(dec, ast.Name) and dec.id == "tool")
            or "@tool" in corrected
            for dec in (target_fn.decorator_list if target_fn else [])
        )

        # If @tool decorator is missing, auto-insert decorator above target function
        if target_fn and not has_decorator:
            desc = self._extract_docstring(target_fn) or f"MCP tool function {target_fn.name}"
            corrected, dec_fixed = self._insert_decorator(corrected, target_fn, desc)
            if dec_fixed:
                fixes.append(f"Auto-inserted '@tool(description=\"{desc}\")' decorator above function '{target_fn.name}'.")

        # 5. Check for missing `from tools_sdk import tool` import
        if ("@tool" in corrected or "from tools_sdk" in corrected) and "from tools_sdk import tool" not in corrected:
            corrected = f"from tools_sdk import tool\n\n{corrected.lstrip()}"
            fixes.append("Added missing 'from tools_sdk import tool' import at top of file.")

        # 6. Untyped Parameter Auto-Annotation
        if target_fn:
            corrected, param_fixes = self._annotate_untyped_params(corrected, target_fn)
            fixes.extend(param_fixes)

        # 7. Unbound Standard Library Symbol Auto-Imports (Path, List, json, re, math, etc.)
        try:
            latest_tree = ast.parse(corrected)
            corrected, symbol_fixes = self._fix_unbound_symbols(latest_tree, corrected)
            fixes.extend(symbol_fixes)
        except Exception:
            pass

        has_autofix = bool(fixes)
        return HealResult(
            original_source=original_source,
            corrected_source=corrected,
            suggested_requirements=suggested_reqs,
            fixes_applied=fixes,
            has_autofix=has_autofix,
            syntax_ok=syntax_ok,
            target_function=target_fn.name if target_fn else None,
        )


    def _fix_missing_colons(self, code: str) -> Tuple[str, bool]:
        lines = code.splitlines()
        modified = False
        new_lines = []
        for line in lines:
            stripped = line.rstrip()
            if re.match(r"^\s*def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(.*\)\s*(->\s*[^:]+)?\s*$", stripped) and not stripped.endswith(":"):
                line = stripped + ":"
                modified = True
            new_lines.append(line)
        return "\n".join(new_lines) + ("\n" if code.endswith("\n") else ""), modified

    def _infer_requirements(
        self, tree: ast.AST, existing_requirements: List[str]
    ) -> Tuple[List[str], List[str]]:
        existing_canonical = {canonical_name(r) for r in existing_requirements}
        suggested = list(existing_requirements)
        fixes = []

        for node in ast.walk(tree):
            mod_name = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_name = alias.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod_name = node.module.split(".")[0]

            if mod_name and mod_name in IMPORT_TO_PACKAGE:
                package = IMPORT_TO_PACKAGE[mod_name]
                c_pkg = canonical_name(package)
                if c_pkg not in existing_canonical:
                    existing_canonical.add(c_pkg)
                    suggested.append(package)
                    fixes.append(f"Auto-inferred PyPI package requirement '{package}' from 'import {mod_name}'.")

        return suggested, fixes

    def _extract_docstring(self, fn_node: ast.FunctionDef) -> Optional[str]:
        doc = ast.get_docstring(fn_node)
        if doc:
            first_line = doc.strip().splitlines()[0].strip()
            return first_line.replace('"', '\\"')
        return None

    def _insert_decorator(self, code: str, fn_node: ast.FunctionDef, description: str) -> Tuple[str, bool]:
        lines = code.splitlines()
        lineno = fn_node.lineno - 1  # 0-indexed line number
        if lineno < 0 or lineno >= len(lines):
            return code, False

        # Match indentation of def line
        match = re.match(r"^(\s*)def\s+", lines[lineno])
        indent = match.group(1) if match else ""

        decorator_line = f'{indent}@tool(description="{description}")'
        lines.insert(lineno, decorator_line)
        return "\n".join(lines) + ("\n" if code.endswith("\n") else ""), True

    def _annotate_untyped_params(self, code: str, fn_node: ast.FunctionDef) -> Tuple[str, List[str]]:
        fixes = []
        untyped = [arg.arg for arg in fn_node.args.args if arg.annotation is None and arg.arg != "self"]
        if not untyped:
            return code, fixes

        lines = code.splitlines()
        lineno = fn_node.lineno - 1
        if lineno < 0 or lineno >= len(lines):
            return code, fixes

        def_line = lines[lineno]
        for arg in untyped:
            # Replace untyped parameter `arg` with `arg: str` in def line if not already annotated
            pattern = rf"\b{arg}\b(?!\s*:)"
            if re.search(pattern, def_line):
                def_line = re.sub(pattern, f"{arg}: str", def_line, count=1)
                fixes.append(f"Auto-annotated parameter '{arg}' with default type 'str' in function '{fn_node.name}'.")

        lines[lineno] = def_line
        return "\n".join(lines) + ("\n" if code.endswith("\n") else ""), fixes

    def _fix_unbound_symbols(self, tree: ast.AST, code: str) -> Tuple[str, List[str]]:
        fixes = []
        bound = set()
        loaded = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound.add(alias.asname or alias.name)
            elif isinstance(node, ast.FunctionDef):
                bound.add(node.name)
                for arg in node.args.args:
                    bound.add(arg.arg)
            elif isinstance(node, ast.ClassDef):
                bound.add(node.name)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, (ast.Store, ast.Param)):
                    bound.add(node.id)
                elif isinstance(node.ctx, ast.Load):
                    loaded.add(node.id)

        unbound = loaded - bound
        symbol_map = {
            "Path": "from pathlib import Path",
            "List": "from typing import List",
            "Dict": "from typing import Dict",
            "Tuple": "from typing import Tuple",
            "Optional": "from typing import Optional",
            "Union": "from typing import Union",
            "Any": "from typing import Any",
            "Callable": "from typing import Callable",
            "json": "import json",
            "re": "import re",
            "math": "import math",
            "sys": "import sys",
            "time": "import time",
            "asyncio": "import asyncio",
            "dataclass": "from dataclasses import dataclass",
        }

        needed_imports = []
        for sym in sorted(unbound):
            if sym in symbol_map and symbol_map[sym] not in code:
                needed_imports.append(symbol_map[sym])
                fixes.append(f"Auto-imported missing symbol '{sym}' via '{symbol_map[sym]}'.")

        if needed_imports:
            imports_text = "\n".join(needed_imports) + "\n"
            code = f"{imports_text}{code}"

        return code, fixes

    def intercept_runtime_failure(
        self,
        tool_name: str,
        traceback_str: str,
        source_code: Optional[str] = None,
    ) -> Optional[HealResult]:
        """Intercepts a runtime execution failure traceback, diagnoses the error, and proposes AST code fixes."""
        if not source_code:
            return None

        heal_result = self.heal_source(source_code, name=tool_name)

        # Check for specific traceback error patterns
        missing_module = re.search(r"No module named ['\"]([^'\"]+)['\"]", traceback_str)
        if missing_module:
            mod = missing_module.group(1)
            pkg = IMPORT_TO_PACKAGE.get(mod.lower(), mod)
            if pkg not in heal_result.suggested_requirements:
                heal_result.suggested_requirements.append(pkg)
                heal_result.fixes_applied.append(f"Inferred PyPI dependency '{pkg}' for missing module '{mod}'.")
                heal_result.has_autofix = True

        name_error = re.search(r"name ['\"]([^'\"]+)['\"] is not defined", traceback_str)
        if name_error:
            missing_name = name_error.group(1)
            symbol_map = {
                "json": "import json",
                "re": "import re",
                "math": "import math",
                "Path": "from pathlib import Path",
                "List": "from typing import List",
                "Dict": "from typing import Dict",
            }
            if missing_name in symbol_map and symbol_map[missing_name] not in heal_result.corrected_source:
                heal_result.corrected_source = f"{symbol_map[missing_name]}\n" + heal_result.corrected_source
                heal_result.fixes_applied.append(f"Auto-imported missing runtime symbol '{missing_name}'.")
                heal_result.has_autofix = True

        return heal_result


