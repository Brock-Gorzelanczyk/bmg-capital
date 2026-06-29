"""R1 — Deterministic browser error classifier (replaces Haiku LLM call).

No LLM dependency. Keyword/regex map, first-hit wins.
"""
from __future__ import annotations

import re


_RULES: list[tuple[re.Pattern, str, str]] = [
    # TypeScript / React property access errors
    (re.compile(r"cannot read propert(y|ies)|undefined is not", re.I),
     "typescript_missing_property", "frontend"),
    # CSS class name typos (className mismatch, Tailwind unknown class, etc.)
    (re.compile(r"className mismatch|Unknown utility class|class .* does not exist.*tailwind", re.I),
     "css_class_typo", "frontend"),
    # Missing DB column
    (re.compile(r"OperationalError.*no such column|no such column", re.I),
     "missing_db_column", "backend"),
    # Module / import resolution errors — covers both Node and Python
    (re.compile(r"Module not found|Cannot find module|Cannot resolve module", re.I),
     "import_path_wrong", "frontend"),
    (re.compile(r"ModuleNotFoundError|ImportError", re.I),
     "import_path_wrong", "backend"),
    # Null / None attribute access
    (re.compile(r"AttributeError.*NoneType|NoneType.*has no attribute", re.I),
     "null_attribute_access", "backend"),
    # Key errors
    (re.compile(r"\bKeyError\b", re.I),
     "key_error", "backend"),
    # ReferenceError (JS)
    (re.compile(r"\bReferenceError\b", re.I),
     "reference_error", "frontend"),
    # Connection errors
    (re.compile(r"\bConnectionError\b|ECONNREFUSED|ENOTFOUND|fetch failed", re.I),
     "connection_error", None),
    # Syntax errors — determine side from stack
    (re.compile(r"SyntaxError|Unexpected token", re.I),
     "syntax_error", None),
    # Broken image / asset URLs
    (re.compile(r"404.*\.(png|jpg|svg|webp)", re.I),
     "broken_image_url", "frontend"),
    # npm / node_modules
    (re.compile(r"npm ERR|ModuleNotFoundError.*node_modules", re.I),
     "missing_npm_dependency", "frontend"),
]

_FS_TOKEN_RE = re.compile(r"(/[\w./-]+\.\w+)")


def _suggested_file(stack: str) -> str:
    """Extract last filesystem-looking token from stack, strip line/col."""
    matches = _FS_TOKEN_RE.findall(stack)
    if not matches:
        return ""
    path = matches[-1]
    # Strip trailing :line:col if present
    path = re.sub(r":\d+(:\d+)?$", "", path)
    return path


def _infer_side(stack: str) -> str:
    if any(ext in stack for ext in [".ts", ".tsx", ".js", ".jsx"]):
        return "frontend"
    if ".py" in stack:
        return "backend"
    return "unknown"


def classify_error(text: str, stack: str) -> dict:
    """Returns {category, frontend_or_backend, suggested_file}. No LLM."""
    combined = text + "\n" + stack
    for pattern, category, side in _RULES:
        if pattern.search(combined):
            if side is None:
                side = _infer_side(stack)
            return {
                "category": category,
                "frontend_or_backend": side,
                "suggested_file": _suggested_file(stack),
            }
    return {
        "category": "other",
        "frontend_or_backend": "unknown",
        "suggested_file": _suggested_file(stack),
    }
