"""
G3 — No new writes to starting_capital_cents / inception_capital_cents /
current_capital_cents outside migrations in this branch.

git diff main...HEAD -- '*.py' ':(exclude)backend/app/db/migrations/*'
for added lines matching assignment or UPDATE patterns must be empty.
"""
import subprocess
import re
import os
import pytest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../")
)

# Patterns for writes: assignment or SQL UPDATE
_WRITE_PATTERNS = [
    re.compile(r"(starting_capital_cents|inception_capital_cents|current_capital_cents)\s*="),
    re.compile(r"UPDATE\b.*capital_cents", re.IGNORECASE),
]


def _get_capital_write_hits():
    result = subprocess.run(
        [
            "git", "diff", "main...HEAD",
            "--",
            "*.py",
            ":(exclude)backend/app/db/migrations/*",
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    hits = []
    for line in result.stdout.splitlines():
        if not (line.startswith("+") and not line.startswith("+++")):
            continue
        for pat in _WRITE_PATTERNS:
            if pat.search(line):
                hits.append(line)
                break
    return hits


def test_g3_no_new_capital_writes_outside_migrations():
    hits = _get_capital_write_hits()
    assert hits == [], (
        f"Found {len(hits)} new write(s) to capital fields outside migrations:\n"
        + "\n".join(hits)
    )
