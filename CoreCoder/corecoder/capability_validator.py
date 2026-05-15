# -*- coding: utf-8 -*-
"""Lightweight post-write validation for agent-authored files."""

from __future__ import annotations

import ast
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationResult:
    ok: bool
    kind: str
    message: str


def validate_path(path: Path) -> ValidationResult:
    """Validate supported file types after writes/edits.

    The goal is fast feedback, not a full linter. Only standard-library checks
    are used so this stays dependency-free.
    """
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ValidationResult(True, "binary-or-non-utf8", "Skipped validation for non-UTF8 file.")

    try:
        if suffix == ".py":
            ast.parse(text)
            return ValidationResult(True, "python", "Python syntax OK.")
        if suffix == ".json":
            json.loads(text)
            return ValidationResult(True, "json", "JSON syntax OK.")
        if suffix == ".toml":
            tomllib.loads(text)
            return ValidationResult(True, "toml", "TOML syntax OK.")
        if suffix in {".yaml", ".yml"}:
            return _validate_yaml_shape(text)
    except Exception as exc:
        return ValidationResult(False, suffix.lstrip(".") or "text", str(exc))

    return ValidationResult(True, "unsupported", "No validation rule for this file type.")


def validate_python_source(code: str) -> ValidationResult:
    try:
        ast.parse(code)
        return ValidationResult(True, "python", "Python syntax OK.")
    except SyntaxError as exc:
        return ValidationResult(False, "python", f"Python syntax error: {exc}")


def _validate_yaml_shape(text: str) -> ValidationResult:
    """A small YAML sanity check without pulling PyYAML as a dependency."""
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_single = False
    in_double = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return ValidationResult(False, "yaml", "Unbalanced bracket-like character.")
    if in_single or in_double:
        return ValidationResult(False, "yaml", "Unclosed quoted string.")
    if stack:
        return ValidationResult(False, "yaml", "Unbalanced bracket-like character.")
    return ValidationResult(True, "yaml", "YAML shape check OK.")
