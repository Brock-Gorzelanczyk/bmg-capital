"""R2 — Tier-1 deterministic autofix (replaces Sonnet/Haiku LLM diff call).

Only applies safe linter/formatter fixes. No LLM required.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

TIER1_CATEGORIES = {
    "css_class_typo",
    "import_path_wrong",
    "syntax_error_simple",
    "missing_python_dependency",
    "unused_import",
    "unused_variable",
    "trailing_whitespace",
    "missing_newline_at_eof",
}

_FRONTEND_EXTS = {".ts", ".tsx", ".js", ".jsx"}
_BACKEND_EXTS = {".py"}

TIMEOUT = 30  # seconds per subprocess


def apply_tier1_fix(file_path: str, category: str) -> dict:
    """Return {success: bool, files_changed: [...], tool: str, stdout: str}.

    Frontend (.ts/.tsx/.js/.jsx): eslint --fix then prettier --write.
    Backend (.py): ruff check --fix then black.
    """
    suffix = Path(file_path).suffix.lower()

    if suffix in _FRONTEND_EXTS:
        return _fix_frontend(file_path)
    elif suffix in _BACKEND_EXTS:
        return _fix_backend(file_path)
    else:
        return {
            "success": False,
            "files_changed": [],
            "tool": "none",
            "stdout": f"Unsupported file extension: {suffix}",
        }


def _fix_frontend(file_path: str) -> dict:
    stdout_parts = []
    success = True

    # eslint --fix
    try:
        eslint = subprocess.run(
            ["npx", "eslint", "--fix", file_path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        stdout_parts.append(f"[eslint] rc={eslint.returncode}\n{eslint.stdout[:500]}")
        if eslint.returncode not in (0, 1):  # 1 = warnings only
            success = False
    except Exception as exc:
        stdout_parts.append(f"[eslint] error: {exc}")
        success = False

    # prettier --write
    try:
        prettier = subprocess.run(
            ["npx", "prettier", "--write", file_path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        stdout_parts.append(f"[prettier] rc={prettier.returncode}\n{prettier.stdout[:500]}")
        if prettier.returncode != 0:
            success = False
    except Exception as exc:
        stdout_parts.append(f"[prettier] error: {exc}")
        success = False

    return {
        "success": success,
        "files_changed": [file_path] if success else [],
        "tool": "chained",
        "stdout": "\n".join(stdout_parts),
    }


def _fix_backend(file_path: str) -> dict:
    stdout_parts = []
    success = True

    # ruff check --fix
    try:
        ruff = subprocess.run(
            ["ruff", "check", "--fix", file_path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        stdout_parts.append(f"[ruff] rc={ruff.returncode}\n{ruff.stdout[:500]}")
        if ruff.returncode not in (0, 1):
            success = False
    except Exception as exc:
        stdout_parts.append(f"[ruff] error: {exc}")
        success = False

    # black
    try:
        black = subprocess.run(
            ["black", file_path],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        stdout_parts.append(f"[black] rc={black.returncode}\n{black.stdout[:500]}")
        if black.returncode != 0:
            success = False
    except Exception as exc:
        stdout_parts.append(f"[black] error: {exc}")
        success = False

    return {
        "success": success,
        "files_changed": [file_path] if success else [],
        "tool": "chained",
        "stdout": "\n".join(stdout_parts),
    }
