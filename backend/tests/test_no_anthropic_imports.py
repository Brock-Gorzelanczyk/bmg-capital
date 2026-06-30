"""WALL — CI guard: bans `import anthropic` / `from anthropic` outside llm_client.py.

AST-walks every .py under backend/ (excluding .venv/, node_modules/, and the whitelist).
Fails loudly with file path + line number on any violation.

NO env gating, NO pytest.mark.skipif. This guard always runs.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Whitelist — only these files may import anthropic
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).parent.parent.resolve()

WHITELIST: set[Path] = {
    (_BACKEND_ROOT / "app" / "services" / "llm_client.py").resolve(),
}

# Directories to skip entirely
_SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", ".git"}


def _walk_backend_py_files() -> Iterator[Path]:
    """Yield all .py files under backend/, excluding skip dirs and the whitelist."""
    for path in _BACKEND_ROOT.rglob("*.py"):
        # Skip excluded directories anywhere in the path
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        resolved = path.resolve()
        if resolved in WHITELIST:
            continue
        yield resolved


def _file_imports_anthropic(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, statement), ...] for every anthropic import in path.

    Edge cases:
    - Aliased import (`import anthropic as foo`) is detected.
    - Conditional imports (`if False: import anthropic`) are detected (AST sees all nodes).
    - Comments (`# anthropic`) are NOT flagged (AST ignores comments).
    - Syntax errors propagate — treat as authoring error.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "anthropic" or alias.name.startswith("anthropic."):
                    stmt = f"import {alias.name}"
                    if alias.asname:
                        stmt += f" as {alias.asname}"
                    hits.append((node.lineno, stmt))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "anthropic" or module.startswith("anthropic."):
                names = ", ".join(
                    a.name + (f" as {a.asname}" if a.asname else "") for a in node.names
                )
                hits.append((node.lineno, f"from {module} import {names}"))
    return hits


def test_no_anthropic_imports_outside_llm_client() -> None:
    """AST-walks backend/, fails if any non-whitelisted file imports anthropic."""
    violations: list[str] = []

    for py_file in _walk_backend_py_files():
        try:
            hits = _file_imports_anthropic(py_file)
        except SyntaxError as exc:
            violations.append(
                f"SYNTAX ERROR in {py_file}: {exc} — fix the file to pass the Wall"
            )
            continue

        for lineno, stmt in hits:
            # Show path relative to backend root for readability
            try:
                rel = py_file.relative_to(_BACKEND_ROOT)
            except ValueError:
                rel = py_file
            violations.append(f"{rel}:{lineno}: {stmt}")

    if violations:
        msg = (
            "\n\nWALL VIOLATION — `import anthropic` found outside whitelist:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n\nOnly backend/app/services/llm_client.py may import anthropic."
            + "\nAll other LLM calls must go through call_llm()."
        )
        raise AssertionError(msg)
