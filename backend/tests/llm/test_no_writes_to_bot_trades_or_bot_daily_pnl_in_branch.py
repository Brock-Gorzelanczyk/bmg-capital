"""
G4 — No writes to bot_trades or bot_daily_pnl added in this branch.

git diff main...HEAD -- '*.py' for added lines matching DML on those tables.
Must be empty.
"""
import subprocess
import re
import os
import pytest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../")
)

_WRITE_PATTERNS = [
    re.compile(r"DELETE FROM bot_trades", re.IGNORECASE),
    re.compile(r"UPDATE bot_trades", re.IGNORECASE),
    re.compile(r"DELETE FROM bot_daily_pnl", re.IGNORECASE),
    re.compile(r"UPDATE bot_daily_pnl", re.IGNORECASE),
    re.compile(r"db\.delete\(.*BotTrade", re.IGNORECASE),
    re.compile(r"db\.delete\(.*BotDailyPnL", re.IGNORECASE),
]


def _get_bot_table_write_hits():
    result = subprocess.run(
        ["git", "diff", "main...HEAD", "--", "*.py"],
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


def test_g4_no_writes_to_bot_trades_or_bot_daily_pnl():
    hits = _get_bot_table_write_hits()
    assert hits == [], (
        f"Found {len(hits)} new write(s) to bot_trades/bot_daily_pnl in branch:\n"
        + "\n".join(hits)
    )
