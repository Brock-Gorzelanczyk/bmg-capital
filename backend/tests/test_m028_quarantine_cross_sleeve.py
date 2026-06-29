"""Tests for m028_quarantine_cross_sleeve migration — SHIP 2.

Tests 10-13 from the spec.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import importlib.util
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Minimal SQLAlchemy shim + FakeConn (same pattern as m027 tests)
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
    def scalar(self):
        row = self._cur.fetchone()
        return row[0] if row else None


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


_BASE_DDL = """
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
CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT,
    closed_at TEXT,
    quarantined_at TEXT
);
"""


def _setup_db(raw: sqlite3.Connection):
    raw.executescript(_BASE_DDL)
    raw.commit()


def _insert_profile(raw, name: str) -> int:
    cur = raw.execute("INSERT INTO bot_profiles (name) VALUES (?)", (name,))
    return cur.lastrowid


def _insert_alloc(raw, profile_id: int, user_id: int) -> int:
    cur = raw.execute(
        "INSERT INTO bot_allocations (profile_id, user_id, enabled, starting_capital_cents, "
        "inception_capital_cents, current_capital_cents) VALUES (?, ?, 1, 5000000, 5000000, 5000000)",
        (profile_id, user_id),
    )
    return cur.lastrowid


def _insert_position(raw, alloc_id: int, symbol: str,
                     closed_at=None, quarantined_at=None) -> int:
    cur = raw.execute(
        "INSERT INTO bot_positions (allocation_id, symbol, closed_at, quarantined_at) "
        "VALUES (?, ?, ?, ?)",
        (alloc_id, symbol, closed_at, quarantined_at),
    )
    return cur.lastrowid


def _load_m028(fake_conn, registry_mod=None):
    """Load m028 with fake sqlalchemy and optional custom registry module."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m028_quarantine_cross_sleeve.py",
    )

    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text

    # Load gate module
    gate_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations", "_gate.py"
    )
    fake_gate = types.ModuleType("app.db.migrations._gate")
    gate_spec = importlib.util.spec_from_file_location("_gate_real", gate_path)
    gate_real = importlib.util.module_from_spec(gate_spec)
    # We need a fake sqlalchemy for the gate too
    old_sa = sys.modules.get("sqlalchemy")
    sys.modules["sqlalchemy"] = fake_sa
    gate_spec.loader.exec_module(gate_real)
    if old_sa is None:
        sys.modules.pop("sqlalchemy", None)
    else:
        sys.modules["sqlalchemy"] = old_sa
    fake_gate.already_ran = gate_real.already_ran
    fake_gate.record = gate_real.record

    # Use real registry unless a custom one is provided
    if registry_mod is None:
        reg_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "asset_class_registry.py",
        )
        reg_spec = importlib.util.spec_from_file_location("asset_class_registry_real", reg_path)
        registry_mod = importlib.util.module_from_spec(reg_spec)
        old_sa2 = sys.modules.get("sqlalchemy")
        sys.modules["sqlalchemy"] = fake_sa
        # Suppress discord import
        fake_discord = types.ModuleType("app.services.discord")
        fake_discord.send_ops_alert = lambda **kw: True
        old_discord = sys.modules.get("app.services.discord")
        sys.modules["app.services.discord"] = fake_discord
        reg_spec.loader.exec_module(registry_mod)
        if old_sa2 is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = old_sa2
        if old_discord is None:
            sys.modules.pop("app.services.discord", None)
        else:
            sys.modules["app.services.discord"] = old_discord

    fake_registry = types.ModuleType("app.services.asset_class_registry")
    fake_registry.get_required_asset_class = registry_mod.get_required_asset_class
    fake_registry.classify_instrument = registry_mod.classify_instrument

    # Build stub module hierarchy
    fake_app = types.ModuleType("app")
    fake_app_db = types.ModuleType("app.db")
    fake_app_db_migrations = types.ModuleType("app.db.migrations")
    fake_app_services = types.ModuleType("app.services")

    old_mods = {k: sys.modules.get(k) for k in [
        "sqlalchemy",
        "app", "app.db", "app.db.migrations", "app.db.migrations._gate",
        "app.services", "app.services.asset_class_registry",
    ]}
    sys.modules["sqlalchemy"] = fake_sa
    sys.modules["app"] = fake_app
    sys.modules["app.db"] = fake_app_db
    sys.modules["app.db.migrations"] = fake_app_db_migrations
    sys.modules["app.db.migrations._gate"] = fake_gate
    sys.modules["app.services"] = fake_app_services
    sys.modules["app.services.asset_class_registry"] = fake_registry

    try:
        spec = importlib.util.spec_from_file_location("m028_quarantine_cross_sleeve", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(fake_conn)
    finally:
        for k, v in old_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("m028_quarantine_cross_sleeve", None)


# ---------------------------------------------------------------------------
# 10. m028 quarantines existing violations
# ---------------------------------------------------------------------------

def test_m028_quarantines_existing_violations():
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    # crypto_quant_scalper (declared=crypto) with AAPL (actual=equity) -> violation
    pid = _insert_profile(raw, "crypto_quant_scalper")
    aid = _insert_alloc(raw, pid, 1)
    _insert_position(raw, aid, "AAPL")  # equity symbol for crypto bot -> violation

    # stock_swing (declared=equity) with AAPL (actual=equity) -> clean
    pid2 = _insert_profile(raw, "stock_swing")
    aid2 = _insert_alloc(raw, pid2, 1)
    _insert_position(raw, aid2, "MSFT")  # clean

    raw.commit()

    result = _load_m028(_FakeConn(raw))
    assert result["executed"] is True
    assert result["quarantined"] == 1, f"expected 1 quarantined, got {result['quarantined']}"

    rows = raw.execute(
        "SELECT bot_id, actual_symbol, action FROM cross_sleeve_quarantine_s14"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "crypto_quant_scalper"
    assert rows[0][1] == "AAPL"
    assert rows[0][2] == "review"

    raw.close()


# ---------------------------------------------------------------------------
# 11. m028 does NOT auto-close quarantined positions
# ---------------------------------------------------------------------------

def test_m028_does_not_auto_close_quarantined_positions():
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    pid = _insert_profile(raw, "crypto_quant_scalper")
    aid = _insert_alloc(raw, pid, 1)
    pos_id = _insert_position(raw, aid, "AAPL")  # violation
    raw.commit()

    _load_m028(_FakeConn(raw))

    row = raw.execute(
        "SELECT closed_at, quarantined_at FROM bot_positions WHERE id = ?", (pos_id,)
    ).fetchone()
    assert row["closed_at"] is None, "m028 must NOT close the position"
    assert row["quarantined_at"] is None, "m028 must NOT set quarantined_at on the position"

    raw.close()


# ---------------------------------------------------------------------------
# 12. Multi-user safety: m028 only scans user_id = 1
# ---------------------------------------------------------------------------

def test_multi_user_safety_m028_only_scans_user_1():
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    # User 2 violation — must NOT be quarantined
    pid = _insert_profile(raw, "crypto_quant_scalper")
    aid_u2 = _insert_alloc(raw, pid, 2)
    _insert_position(raw, aid_u2, "AAPL")  # violation for user 2

    # User 1 clean position
    pid2 = _insert_profile(raw, "stock_swing")
    aid_u1 = _insert_alloc(raw, pid2, 1)
    _insert_position(raw, aid_u1, "MSFT")  # clean for user 1

    raw.commit()

    _load_m028(_FakeConn(raw))

    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE user_id != 1"
    ).fetchone()[0]
    assert count == 0, f"Expected 0 non-user-1 rows, got {count}"

    raw.close()


# ---------------------------------------------------------------------------
# 13. m028 is idempotent via gate
# ---------------------------------------------------------------------------

def test_m028_is_idempotent_via_gate():
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    pid = _insert_profile(raw, "crypto_quant_scalper")
    aid = _insert_alloc(raw, pid, 1)
    _insert_position(raw, aid, "AAPL")  # violation
    raw.commit()

    first = _load_m028(_FakeConn(raw))
    assert first["executed"] is True

    second = _load_m028(_FakeConn(raw))
    assert second["executed"] is False
    assert second["skipped_reason"] == "already_applied"

    # Row count unchanged on second run
    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14"
    ).fetchone()[0]
    assert count == 1, f"Expected 1 row after idempotent second run, got {count}"

    raw.close()


# ---------------------------------------------------------------------------
# Edge case: m028 second boot returns "already_applied" immediately (no scan)
# Verifies _gate.already_ran short-circuits before touching bot_positions.
# ---------------------------------------------------------------------------

def test_m028_second_boot_returns_already_applied_dict():
    """Explicit shape check: second run must return exactly the skipped shape."""
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    pid = _insert_profile(raw, "stock_swing")
    aid = _insert_alloc(raw, pid, 1)
    _insert_position(raw, aid, "AAPL")
    raw.commit()

    _load_m028(_FakeConn(raw))  # first run

    result = _load_m028(_FakeConn(raw))  # second run
    assert result == {"skipped_reason": "already_applied", "executed": False}, (
        f"Second run returned unexpected shape: {result}"
    )
    raw.close()


# ---------------------------------------------------------------------------
# Edge case: unclassifiable symbol is skipped (logged), not quarantined
# ---------------------------------------------------------------------------

def test_m028_skips_unclassifiable_symbol_without_quarantine():
    """A position with an unclassifiable symbol (e.g., '') is skipped, not quarantined."""
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    # Insert a position with a weird/unclassifiable symbol
    pid = _insert_profile(raw, "crypto_quant_scalper")
    aid = _insert_alloc(raw, pid, 1)
    _insert_position(raw, aid, "NOT_A_REAL_SYMBOL!!!")  # unclassifiable
    raw.commit()

    result = _load_m028(_FakeConn(raw))
    assert result["executed"] is True
    assert result["skipped_unclassifiable"] == 1, (
        f"Expected 1 skipped_unclassifiable, got {result['skipped_unclassifiable']}"
    )

    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14"
    ).fetchone()[0]
    assert count == 0, f"Unclassifiable symbol should not be quarantined, got {count} rows"

    raw.close()


# ---------------------------------------------------------------------------
# Edge case: UNIQUE INDEX prevents duplicate quarantine rows on forced re-run
# (INSERT OR IGNORE semantics — simulates concurrent/race re-entry)
# ---------------------------------------------------------------------------

def test_m028_unique_index_prevents_duplicate_rows():
    """Even if gate is bypassed and run() is called raw twice, UNIQUE INDEX
    prevents duplicate position_id rows in quarantine table."""
    raw = sqlite3.connect(":memory:")
    _setup_db(raw)

    pid = _insert_profile(raw, "crypto_quant_scalper")
    aid = _insert_alloc(raw, pid, 1)
    pos_id = _insert_position(raw, aid, "AAPL")
    raw.commit()

    # Run first time to create table and insert quarantine row
    _load_m028(_FakeConn(raw))

    # Manually delete the schema_migrations record so m028 can "re-run"
    raw.execute("DELETE FROM schema_migrations")
    raw.commit()

    # Second raw run — should INSERT OR IGNORE, not raise UNIQUE constraint error
    result = _load_m028(_FakeConn(raw))
    assert result["executed"] is True

    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE position_id = ?",
        (pos_id,),
    ).fetchone()[0]
    assert count == 1, f"UNIQUE INDEX must prevent duplicates; got {count} rows"

    raw.close()
