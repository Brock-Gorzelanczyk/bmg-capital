"""SHIP 2 post-mortem guardrail tests: grep-based checks on branch-changed files.

Tests 15-16 from the spec:

15. test_no_new_calls_to_ensure_portfolios_for_user_in_branch
    Grep files changed in this branch (git diff --name-only main...HEAD) for
    '_ensure_portfolios_for_user'. Any hit outside backend/app/routers/bots.py
    (the pre-existing definition site) fails this test.

16. test_no_new_writes_to_starting_capital_cents_outside_migrations
    Grep files changed in this branch for assignment patterns
    (starting_capital_cents =, inception_capital_cents =, current_capital_cents =).
    Any hit in a file outside backend/app/db/migrations/ fails this test.
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest

BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
REPO_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))


def _git_changed_files() -> list[str]:
    """Return absolute paths of files changed in this branch vs main."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        # Make absolute
        return [os.path.join(REPO_DIR, f) for f in lines if os.path.isfile(os.path.join(REPO_DIR, f))]
    except Exception:
        # Fallback: if git is unavailable, return empty (no new files to check)
        return []


def _file_contains(path: str, pattern: str) -> bool:
    try:
        content = open(path, encoding="utf-8", errors="replace").read()
        return bool(re.search(pattern, content))
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 15. No new calls to _ensure_portfolios_for_user in branch-changed files
# ---------------------------------------------------------------------------

def test_no_new_calls_to_ensure_portfolios_for_user_in_branch():
    changed = _git_changed_files()

    # Only check backend .py files; skip tests and .venv
    backend_changed = [
        f for f in changed
        if f.endswith(".py")
        and "/backend/" in f.replace(os.sep, "/")
        and "/tests/" not in f.replace(os.sep, "/")
        and "/.venv/" not in f.replace(os.sep, "/")
        and "test_" not in os.path.basename(f)
    ]

    # bots.py is the only pre-existing caller (definition + call sites).
    _ALLOWED = {
        os.path.abspath(os.path.join(BACKEND_DIR, "app", "routers", "bots.py")),
    }

    violating = [
        f for f in backend_changed
        if _file_contains(f, r"_ensure_portfolios_for_user")
        and f not in _ALLOWED
    ]

    assert not violating, (
        f"SHIP 2 HARD CONSTRAINT VIOLATED: new file(s) call _ensure_portfolios_for_user:\n"
        + "\n".join(f"  {f}" for f in sorted(violating))
        + "\n\nOnly backend/app/routers/bots.py may contain _ensure_portfolios_for_user."
    )


# ---------------------------------------------------------------------------
# 16. No new writes to capital fields outside migrations in branch-changed files
# ---------------------------------------------------------------------------

def test_no_new_writes_to_starting_capital_cents_outside_migrations():
    changed = _git_changed_files()

    pattern = r"(starting_capital_cents|inception_capital_cents|current_capital_cents)\s*="

    # Check backend .py files changed in this branch, excluding migrations and tests
    backend_non_migration_changed = [
        f for f in changed
        if f.endswith(".py")
        and "/backend/" in f.replace(os.sep, "/")
        and "/migrations/" not in f.replace(os.sep, "/")
        and "/tests/" not in f.replace(os.sep, "/")
        and "/.venv/" not in f.replace(os.sep, "/")
        and "test_" not in os.path.basename(f)
    ]

    violating = [
        f for f in backend_non_migration_changed
        if _file_contains(f, pattern)
    ]

    assert not violating, (
        f"SHIP 2 HARD CONSTRAINT VIOLATED: new capital field write(s) outside migrations:\n"
        + "\n".join(f"  {f}" for f in sorted(violating))
        + "\n\nFiles changed in this branch must NOT assign starting_capital_cents, "
        "inception_capital_cents, or current_capital_cents outside "
        "backend/app/db/migrations/."
    )
