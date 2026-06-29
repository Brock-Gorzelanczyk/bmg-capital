"""SHIP 3 — m030 idempotency + backfill test.

Verifies:
1. m030 adds inception_capital_cents_snapshot column to bot_daily_pnl
2. m030 adds note column to bot_daily_pnl
3. m030 backfills from bot_allocations.inception_capital_cents
4. Second run returns skipped (gate blocks re-execution)
5. m030 does NOT touch bot_allocations capital fields
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Minimal SQLAlchemy shim (same pattern as test_ship2_capital_invariance.py)
# ---------------------------------------------------------------------------

class _FakeText:
    def __init__(self, sql): self.sql = sql

def text(sql): return _FakeText(sql)


class _FakeCursor:
    def __init__(self, cur): self._cur = cur
    def fetchone(self): return self._cur.fetchone()
    def fetchall(self): return self._cur.fetchall()
    @property
    def rowcount(self): return self._cur.rowcount


class _FakeConn:
    def __init__(self, sqlite_conn):
        self._conn = sqlite_conn
        self._conn.row_factory = sqlite3.Row

    def execute(self, stmt, params=None):
        sql = stmt.sql if isinstance(stmt, _FakeText) else stmt
        if params:
            import re
            keys = []
            def repl(m):
                keys.append(m.group(1))
                return "?"
            converted = re.sub(r":(\w+)", repl, sql)
            values = tuple(params[k] for k in keys)
            return _FakeCursor(self._conn.execute(converted, values))
        return _FakeCursor(self._conn.execute(sql))

    def commit(self):
        self._conn.commit()


# ---------------------------------------------------------------------------
# Schema for the test DB
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    starting_capital_cents INTEGER NOT NULL DEFAULT 0,
    inception_capital_cents INTEGER NOT NULL DEFAULT 0,
    current_capital_cents   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    realized_cents INTEGER NOT NULL DEFAULT 0,
    unrealized_cents INTEGER NOT NULL DEFAULT 0,
    fees_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER,
    symbol TEXT
);
"""

_ALLOCATIONS_CENTS = {
    "stock_swing":    11_000_000,
    "stock_lt":        9_000_000,
    "cash_floor":     10_000_000,
}


def _seed(raw: sqlite3.Connection) -> dict:
    """Seed the DB and return {bot_name: allocation_id}."""
    raw.executescript(_DDL)
    alloc_ids = {}
    for name, cents in _ALLOCATIONS_CENTS.items():
        cur = raw.execute("INSERT INTO bot_profiles (name) VALUES (?)", (name,))
        pid = cur.lastrowid
        cur2 = raw.execute(
            "INSERT INTO bot_allocations "
            "(profile_id, user_id, enabled, starting_capital_cents, "
            " inception_capital_cents, current_capital_cents) "
            "VALUES (?, 1, 1, ?, ?, ?)",
            (pid, cents, cents, cents),
        )
        alloc_ids[name] = cur2.lastrowid

    # Insert one daily_pnl row per allocation
    for name, alloc_id in alloc_ids.items():
        raw.execute(
            "INSERT INTO bot_daily_pnl (allocation_id, date, realized_cents) VALUES (?, '2026-06-28', 500)",
            (alloc_id,),
        )
    raw.commit()
    return alloc_ids


def _run_m030(raw: sqlite3.Connection):
    """Load and run m030 with SQLAlchemy shim."""
    import os
    gate_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations", "_gate.py"
    )
    m030_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m030_inception_snapshot_on_daily_pnl.py"
    )

    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text

    # Patch sqlalchemy BEFORE loading the gate so the gate picks up our fake text
    saved = {k: sys.modules.get(k) for k in [
        "sqlalchemy", "app.db.migrations._gate",
    ]}
    sys.modules["sqlalchemy"] = fake_sa

    gate_spec = importlib.util.spec_from_file_location("_gate_m030", gate_path)
    gate_mod = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate_mod)

    fake_gate = types.ModuleType("app.db.migrations._gate")
    fake_gate.already_ran = gate_mod.already_ran
    fake_gate.record = gate_mod.record
    sys.modules["app.db.migrations._gate"] = fake_gate

    try:
        spec = importlib.util.spec_from_file_location("m030_test", m030_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(_FakeConn(raw))
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("m030_test", None)
        sys.modules.pop("_gate_m030", None)


def _capital_snapshot(raw: sqlite3.Connection) -> dict:
    starting = raw.execute(
        "SELECT SUM(starting_capital_cents) FROM bot_allocations WHERE user_id=1 AND enabled=1"
    ).fetchone()[0] or 0
    inception = raw.execute(
        "SELECT SUM(inception_capital_cents) FROM bot_allocations WHERE user_id=1 AND enabled=1"
    ).fetchone()[0] or 0
    current = raw.execute(
        "SELECT SUM(current_capital_cents) FROM bot_allocations WHERE user_id=1 AND enabled=1"
    ).fetchone()[0] or 0
    return {"starting": starting, "inception": inception, "current": current}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_m030_adds_columns():
    raw = sqlite3.connect(":memory:")
    _seed(raw)

    result = _run_m030(raw)
    assert result["executed"] is True, f"Expected executed=True, got: {result}"
    assert result["column_added"] is True
    assert result["note_column_added"] is True

    # Confirm columns exist via PRAGMA
    cols = {r[1] for r in raw.execute("PRAGMA table_info(bot_daily_pnl)").fetchall()}
    assert "inception_capital_cents_snapshot" in cols
    assert "note" in cols
    raw.close()


def test_m030_backfills_snapshot_from_inception():
    raw = sqlite3.connect(":memory:")
    alloc_ids = _seed(raw)

    _run_m030(raw)

    # Every row should have snapshot set to the allocation's inception_capital_cents
    rows = raw.execute(
        "SELECT dp.allocation_id, dp.inception_capital_cents_snapshot, a.inception_capital_cents "
        "FROM bot_daily_pnl dp "
        "JOIN bot_allocations a ON a.id = dp.allocation_id"
    ).fetchall()

    assert rows, "Expected at least one bot_daily_pnl row"
    for row in rows:
        alloc_id, snapshot, inception = row
        assert snapshot == inception, (
            f"alloc_id={alloc_id}: snapshot={snapshot} != inception={inception}"
        )
        assert snapshot != 0, f"alloc_id={alloc_id}: snapshot should be non-zero"

    raw.close()


def test_m030_is_idempotent():
    raw = sqlite3.connect(":memory:")
    _seed(raw)

    r1 = _run_m030(raw)
    assert r1["executed"] is True

    r2 = _run_m030(raw)
    assert r2["executed"] is False
    assert r2["skipped_reason"] == "already_applied"

    raw.close()


def test_m030_does_not_mutate_capital():
    """m030 must not touch bot_allocations capital fields."""
    raw = sqlite3.connect(":memory:")
    _seed(raw)

    snap_before = _capital_snapshot(raw)
    assert snap_before["starting"] == sum(_ALLOCATIONS_CENTS.values())

    _run_m030(raw)

    snap_after = _capital_snapshot(raw)
    assert snap_before == snap_after, (
        f"m030 mutated capital: before={snap_before} after={snap_after}"
    )

    raw.close()


def test_m030_creates_archive_tables():
    raw = sqlite3.connect(":memory:")
    _seed(raw)

    result = _run_m030(raw)
    assert result["executed"] is True

    tables = {r[0] for r in raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "bot_trades_archive" in tables
    assert "bot_daily_pnl_archive" in tables

    raw.close()


# ---------------------------------------------------------------------------
# P0 hotfix regression test (2026-06-28)
# Reproduces production failure: bot_allocations.inception_capital_cents = NULL
# causes the backfill UPDATE to set snapshot to NULL, violating NOT NULL DEFAULT 0.
# With the COALESCE fix the snapshot must land on 0, not NULL, and not crash.
# ---------------------------------------------------------------------------

_NULL_INCEPTION_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    starting_capital_cents INTEGER NOT NULL DEFAULT 0,
    inception_capital_cents INTEGER,
    current_capital_cents   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    realized_cents INTEGER NOT NULL DEFAULT 0,
    unrealized_cents INTEGER NOT NULL DEFAULT 0,
    fees_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER,
    symbol TEXT
);
"""


def test_m030_backfill_handles_null_inception_capital_cents():
    """P0 hotfix: when inception_capital_cents is NULL in bot_allocations,
    the backfill must set snapshot to 0 (via COALESCE), never NULL or crash."""
    raw = sqlite3.connect(":memory:")
    raw.executescript(_NULL_INCEPTION_DDL)

    # Seed an allocation with inception_capital_cents explicitly NULL
    cur = raw.execute("INSERT INTO bot_profiles (name) VALUES (?)", ("null_inception_bot",))
    pid = cur.lastrowid
    cur2 = raw.execute(
        "INSERT INTO bot_allocations "
        "(profile_id, user_id, enabled, starting_capital_cents, "
        " inception_capital_cents, current_capital_cents) "
        "VALUES (?, 1, 1, 5000000, NULL, 5000000)",
        (pid,),
    )
    alloc_id = cur2.lastrowid

    # Seed a daily_pnl row pointing to that allocation
    raw.execute(
        "INSERT INTO bot_daily_pnl (allocation_id, date, realized_cents) "
        "VALUES (?, '2026-06-28', 250)",
        (alloc_id,),
    )
    raw.commit()

    # Run m030 — must not raise, must not set NULL
    result = _run_m030(raw)
    assert result["executed"] is True, f"Expected m030 to execute, got: {result}"

    # The snapshot for the NULL-inception row must be 0, not NULL
    row = raw.execute(
        "SELECT inception_capital_cents_snapshot FROM bot_daily_pnl "
        "WHERE allocation_id = ?",
        (alloc_id,),
    ).fetchone()
    assert row is not None, "bot_daily_pnl row missing after m030"
    snapshot = row[0]
    assert snapshot == 0, (
        f"Expected snapshot=0 for NULL inception row, got snapshot={snapshot!r}. "
        "COALESCE fix is not working."
    )

    raw.close()
