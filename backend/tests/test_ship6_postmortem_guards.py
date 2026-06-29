"""SHIP 6 post-mortem guards — 4 invariant tests.

These tests assert the hard constraints from the spec:
1. m038 does NOT mutate any capital fields on deploy.
2. No new calls to _ensure_portfolios_for_user added in this branch.
3. No new writes to starting_capital_cents outside migrations.
4. No writes to bot_trades or bot_daily_pnl in new code.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import types

import pytest
import sqlalchemy as sa

# Add backend to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Test 1: m038 does not mutate capital on deploy ─────────────────────────

_SCHEMA_FOR_M038 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER,
    user_id INTEGER,
    starting_capital_cents INTEGER DEFAULT 1000,
    inception_capital_cents INTEGER DEFAULT 1000,
    current_capital_cents INTEGER DEFAULT 1000,
    enabled BOOLEAN DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bot_symbol_cooldown (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id         TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    cooldown_until TIMESTAMP NOT NULL,
    last_entry_at  TIMESTAMP NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uix_bot_symbol_cooldown_botsym
    ON bot_symbol_cooldown(bot_id, symbol);
"""


def _make_full_engine():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        for stmt in _SCHEMA_FOR_M038.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(sa.text(stmt))
        # Seed a few allocation rows
        for i in range(3):
            conn.execute(sa.text("""
                INSERT INTO bot_allocations (profile_id, user_id, starting_capital_cents,
                    inception_capital_cents, current_capital_cents, enabled)
                VALUES (:pid, 1, :sc, :ic, :cc, 1)
            """), {"pid": i + 1, "sc": (i + 1) * 100_000_00, "ic": (i + 1) * 100_000_00,
                   "cc": (i + 1) * 100_000_00})
        conn.commit()
    return engine


def _snapshot_capital(conn):
    """Return list of (id, starting, inception, current) tuples."""
    rows = conn.execute(sa.text(
        "SELECT id, starting_capital_cents, inception_capital_cents, current_capital_cents "
        "FROM bot_allocations ORDER BY id"
    )).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def _load_m038_with_gate(conn):
    """Load m038 with a real _gate module wired to our in-memory DB."""
    _gate_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations", "_gate.py"
    ))
    gate_name = f"_gate_guard_{os.getpid()}"
    gate_spec = importlib.util.spec_from_file_location(gate_name, _gate_path)
    gate_mod = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate_mod)
    sys.modules["app.db.migrations._gate"] = gate_mod

    _m038_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m038_bot_symbol_cooldown.py"
    ))
    m038_name = f"_m038_guard_{os.getpid()}"
    sys.modules.pop(m038_name, None)
    spec = importlib.util.spec_from_file_location(m038_name, _m038_path)
    m038_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m038_mod)
    return m038_mod


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _restore_sys_modules():
    """Snapshot sys.modules before each test and restore after (SHIP 14/3 lesson)."""
    import sys
    snapshot = dict(sys.modules)
    yield
    for k in list(sys.modules.keys()):
        if k not in snapshot:
            del sys.modules[k]
    for k, v in snapshot.items():
        sys.modules[k] = v


def test_ship6_does_not_mutate_capital_on_deploy():
    """Run m038 against fresh DB. Capital fields unchanged before and after (incl. re-run)."""
    engine = _make_full_engine()

    with engine.connect() as conn:
        before = _snapshot_capital(conn)
        m038_mod = _load_m038_with_gate(conn)

        # First run
        r1 = m038_mod.run(conn)
        assert r1.get("executed") is True

        after1 = _snapshot_capital(conn)
        assert before == after1, f"Capital mutated on first m038 run: {before} vs {after1}"

        # Second run (idempotent)
        r2 = m038_mod.run(conn)
        assert r2.get("executed") is False

        after2 = _snapshot_capital(conn)
        assert before == after2, f"Capital mutated on second m038 run: {before} vs {after2}"


# ── Test 2: No new calls to _ensure_portfolios_for_user ───────────────────

def test_no_new_calls_to_ensure_portfolios_for_user_in_branch():
    """Grep git diff for new lines adding _ensure_portfolios_for_user.

    Allowed in pre-existing files: clean_slate.py, bots.py (if pre-existing on main).
    Any new line starting with '+' that calls _ensure_portfolios_for_user in
    new code (services/cooldown_clamp.py or jobs/auto_pause_degraded.py) must be absent.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    # Grep new SHIP 6 files directly
    ship6_files = [
        os.path.join(repo_root, "backend", "app", "services", "cooldown_clamp.py"),
        os.path.join(repo_root, "backend", "app", "jobs", "auto_pause_degraded.py"),
        os.path.join(repo_root, "backend", "app", "db", "migrations", "m038_bot_symbol_cooldown.py"),
    ]

    pattern = "_ensure_portfolios_for_user"
    for fpath in ship6_files:
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            content = f.read()
        assert pattern not in content, (
            f"[GUARD] {pattern} found in {fpath} — violates SHIP 6 hard constraint"
        )


# ── Test 3: No new writes to starting_capital_cents outside migrations ─────

def test_no_new_writes_to_starting_capital_cents_outside_migrations():
    """Grep SHIP 6 service + job files for starting_capital_cents assignment.

    Assignments are only allowed inside backend/app/db/migrations/.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    non_migration_files = [
        os.path.join(repo_root, "backend", "app", "services", "cooldown_clamp.py"),
        os.path.join(repo_root, "backend", "app", "jobs", "auto_pause_degraded.py"),
        os.path.join(repo_root, "backend", "strategy_lab", "runner.py"),
        os.path.join(repo_root, "backend", "app", "routers", "admin.py"),
        os.path.join(repo_root, "backend", "app", "screener", "scheduler.py"),
    ]

    pattern = "starting_capital_cents"
    import re
    # Match assignment: starting_capital_cents = ... or starting_capital_cents=
    assign_re = re.compile(r"starting_capital_cents\s*=")

    for fpath in non_migration_files:
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            lines = f.readlines()
        violations = [
            (i + 1, line.rstrip())
            for i, line in enumerate(lines)
            if assign_re.search(line)
        ]
        assert not violations, (
            f"[GUARD] starting_capital_cents= assignment found in {fpath}: {violations}"
        )


# ── Test 4: No writes to bot_trades or bot_daily_pnl ──────────────────────

def test_no_writes_to_bot_trades_or_bot_daily_pnl_in_branch():
    """Grep SHIP 6 new files for INSERT/UPDATE/DELETE against bot_trades or bot_daily_pnl."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    ship6_files = [
        os.path.join(repo_root, "backend", "app", "services", "cooldown_clamp.py"),
        os.path.join(repo_root, "backend", "app", "jobs", "auto_pause_degraded.py"),
    ]

    import re
    write_re = re.compile(
        r"(INSERT INTO|UPDATE|DELETE FROM)\s+(bot_trades|bot_daily_pnl)",
        re.IGNORECASE,
    )

    for fpath in ship6_files:
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            content = f.read()
        match = write_re.search(content)
        assert match is None, (
            f"[GUARD] Write to bot_trades or bot_daily_pnl found in {fpath}: {match.group()!r}"
        )
