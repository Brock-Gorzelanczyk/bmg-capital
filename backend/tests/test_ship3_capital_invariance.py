"""SHIP 3 post-mortem guard: m030 deploy must NOT mutate capital state.

test_ship3_does_not_mutate_capital_on_deploy:
  - Seeds bot_allocations at $1M (per m027 spec)
  - Seeds bot_daily_pnl rows
  - Snapshots SUM(starting_capital_cents), SUM(inception_capital_cents),
    SUM(current_capital_cents)
  - Runs m030 once (first boot)
  - Snapshots again
  - Runs m030 a second time (second boot — simulating subsequent deploy)
  - Snapshots a third time
  - All three capital snapshots must be byte-identical and equal 100_000_000
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


# Canonical m027 allocation amounts
_ALLOCATIONS_CENTS = {
    "stock_swing":                  11_000_000,
    "stock_lt":                      9_000_000,
    "stock_day":                     7_000_000,
    "crypto_day":                    9_000_000,
    "crypto_swing":                  7_000_000,
    "crypto_lt":                     6_000_000,
    "crypto_onchain":                5_000_000,
    "options_income":                5_000_000,
    "options_directional":           5_000_000,
    "crypto_quant_aggressive":      11_000_000,
    "crypto_quant_mean_reversion":   8_000_000,
    "crypto_quant_scalper":          7_000_000,
    "cash_floor":                   10_000_000,
}

_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_name TEXT UNIQUE NOT NULL
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
    allocation_id INTEGER
);
"""


def _seed(raw: sqlite3.Connection) -> None:
    raw.executescript(_DDL)
    for name, cents in _ALLOCATIONS_CENTS.items():
        cur = raw.execute("INSERT INTO bot_profiles (name) VALUES (?)", (name,))
        pid = cur.lastrowid
        alloc_cur = raw.execute(
            "INSERT INTO bot_allocations "
            "(profile_id, user_id, enabled, starting_capital_cents, "
            " inception_capital_cents, current_capital_cents) "
            "VALUES (?, 1, 1, ?, ?, ?)",
            (pid, cents, cents, cents),
        )
        alloc_id = alloc_cur.lastrowid
        # seed one daily_pnl row per bot
        raw.execute(
            "INSERT INTO bot_daily_pnl (allocation_id, date, realized_cents) VALUES (?, '2026-06-28', 1000)",
            (alloc_id,),
        )
    raw.commit()


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


def _run_m030(raw: sqlite3.Connection):
    """Run m030 with full dependency shims."""
    m030_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m030_inception_snapshot_on_daily_pnl.py"
    )
    gate_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations", "_gate.py"
    )

    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text

    # Patch sqlalchemy BEFORE loading gate so gate picks up our fake text
    saved = {k: sys.modules.get(k) for k in [
        "sqlalchemy", "app.db.migrations._gate",
    ]}
    sys.modules["sqlalchemy"] = fake_sa

    gate_spec = importlib.util.spec_from_file_location("_gate_ship3_inv", gate_path)
    gate_mod = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate_mod)

    fake_gate = types.ModuleType("app.db.migrations._gate")
    fake_gate.already_ran = gate_mod.already_ran
    fake_gate.record = gate_mod.record
    sys.modules["app.db.migrations._gate"] = fake_gate

    try:
        spec = importlib.util.spec_from_file_location("m030_ship3_inv", m030_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(_FakeConn(raw))
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("m030_ship3_inv", None)
        sys.modules.pop("_gate_ship3_inv", None)


def test_ship3_does_not_mutate_capital_on_deploy():
    raw = sqlite3.connect(":memory:")
    _seed(raw)

    # Snapshot before any m030 run
    snap_before = _capital_snapshot(raw)

    # Verify baseline is $1M
    assert snap_before["starting"] == 100_000_000, (
        f"baseline starting_capital_cents={snap_before['starting']} != 100_000_000"
    )
    assert snap_before["inception"] == 100_000_000
    assert snap_before["current"] == 100_000_000

    # First boot: m030 runs (adds columns + backfills, no capital writes)
    result1 = _run_m030(raw)
    assert result1["executed"] is True, f"First run should execute: {result1}"

    snap_after_boot1 = _capital_snapshot(raw)

    # Second boot: m030 is idempotent (gate short-circuits)
    result2 = _run_m030(raw)
    assert result2["executed"] is False
    assert result2["skipped_reason"] == "already_applied"

    snap_after_boot2 = _capital_snapshot(raw)

    # All three snapshots must be byte-identical
    assert snap_before == snap_after_boot1, (
        f"Capital mutated on first m030 boot: {snap_before} -> {snap_after_boot1}"
    )
    assert snap_before == snap_after_boot2, (
        f"Capital mutated on second m030 boot: {snap_before} -> {snap_after_boot2}"
    )

    # All capital fields must equal exactly $1M
    for snap, label in [
        (snap_after_boot1, "after_boot1"),
        (snap_after_boot2, "after_boot2"),
    ]:
        assert snap["starting"] == 100_000_000, (
            f"[{label}] starting_capital_cents={snap['starting']} != 100_000_000"
        )
        assert snap["inception"] == 100_000_000, (
            f"[{label}] inception_capital_cents={snap['inception']} != 100_000_000"
        )
        assert snap["current"] == 100_000_000, (
            f"[{label}] current_capital_cents={snap['current']} != 100_000_000"
        )

    raw.close()
