"""
G2 — No new calls to _ensure_portfolios_for_user added in this branch.

git diff main...HEAD -- '*.py' for added lines matching _ensure_portfolios_for_user(
must be empty.
"""
import subprocess
import os
import pytest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../")
)


def _get_added_lines_with_ensure_portfolios():
    result = subprocess.run(
        ["git", "diff", "main...HEAD", "--", "*.py"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    hits = []
    for line in result.stdout.splitlines():
        # Only look at added lines (start with '+' but not '+++')
        if line.startswith("+") and not line.startswith("+++"):
            if "_ensure_portfolios_for_user(" in line:
                hits.append(line)
    return hits


def test_g2_no_new_ensure_portfolios_calls():
    hits = _get_added_lines_with_ensure_portfolios()
    assert hits == [], (
        f"Found {len(hits)} new call(s) to _ensure_portfolios_for_user in this branch "
        f"(SHIP 4 must add ZERO):\n"
        + "\n".join(hits)
    )
