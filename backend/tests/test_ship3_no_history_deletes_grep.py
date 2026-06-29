"""SHIP 3 branch-aware guard: no new DELETE FROM bot_trades / bot_daily_pnl
introduced anywhere in this branch outside migrations/ (where they are
covered by the historical-waiver contract in test_migration_history_contract.py).

Reconstruction code may INSERT but never DELETE.
"""
from __future__ import annotations

import os
import re
import sys

# Reuse helpers from SHIP 2 guardrail greps
sys.path.insert(0, os.path.dirname(__file__))
from test_ship2_guardrail_greps import _git_changed_files, _file_contains


def test_no_new_writes_to_bot_trades_or_bot_daily_pnl_outside_explicit_exceptions():
    """SHIP 3 HARD CONSTRAINT: no new DELETE FROM bot_trades or bot_daily_pnl
    in branch-changed backend files outside migrations/ and tests/."""
    changed = _git_changed_files()
    delete_pattern = r"DELETE\s+FROM\s+(bot_trades|bot_daily_pnl)"

    backend_changed = [
        f for f in changed
        if f.endswith(".py")
        and "/backend/" in f.replace(os.sep, "/")
        and "/migrations/" not in f.replace(os.sep, "/")
        and "/tests/" not in f.replace(os.sep, "/")
        and "/.venv/" not in f.replace(os.sep, "/")
    ]

    violating = [f for f in backend_changed if _file_contains(f, delete_pattern)]

    assert not violating, (
        f"SHIP 3 HARD CONSTRAINT: new DELETE FROM bot_trades/bot_daily_pnl outside migrations:\n"
        + "\n".join(f"  {f}" for f in sorted(violating))
        + "\n\nReconstruction may INSERT but never DELETE. "
        "Standing decision (2026-06-28): capital resets must NOT delete trade history."
    )
