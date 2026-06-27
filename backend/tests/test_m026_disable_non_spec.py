"""Tests for m026_disable_non_spec_allocations.

Verifies:
  - Extra (non-SPEC) enabled allocations for user 1 get disabled
  - SPEC allocations are LEFT enabled
  - user_id != 1 untouched
  - Hard-errors if no SPEC bots are present (refuses to proceed)
  - Idempotent re-run is safe
"""
import os
import sys
import sqlite3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SPEC = {
    "stock_swing", "stock_lt", "stock_day",
    "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
    "options_income", "options_directional",
    "crypto_quant_aggressive", "crypto_quant_mean_reversion", "crypto_quant_scalper",
    "cash_floor",
}

EXTRAS = {
    # Inflation that appeared on prod:
    "stock_momentum", "stock_value", "stock_growth", "stock_smallcap",  # +4 Stocks
    "crypto_macro", "crypto_arbitrage", "crypto_yield", "crypto_l2", "crypto_defi",  # +5 Crypto
    "options_iron_condor", "options_strangle",  # +2 Options
}


# ─── adapter (same shape as test_m024/m025) ────────────────────────────────

class _FakeText:
    def __init__(self, sql: str): self.sql = sql
def text(sql: str) -> _FakeText: return _FakeText(sql)

class _FakeCursor:
    def __init__(self, cur): self._cur = cur
    def fetchone(self): return self._cur.fetchone()
    def fetchall(self): return self._cur.fetchall()

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
    def commit(self): self._conn.commit()


_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    user_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    starting_capital_cents INTEGER NOT NULL DEFAULT 0,
    paused_reason TEXT,
    updated_at TEXT
);
"""


def _seed(conn):
    cur = conn.cursor()
    # user_id=1: all SPEC bots enabled + extras enabled
    for name in list(SPEC) + list(EXTRAS):
        cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 1))
        pid = cur.lastrowid
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                paused_reason, updated_at)
               VALUES (?, 1, 1, 7000000, NULL, '2024-01-01T00:00:00')""",
            (pid,),
        )
    # user_id=3: separate (control)
    for name in ("stock_swing", "crypto_day"):
        cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 3))
        pid = cur.lastrowid
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                paused_reason, updated_at)
               VALUES (?, 3, 1, 5000000, NULL, '2024-01-01T00:00:00')""",
            (pid,),
        )
    conn.commit()


@pytest.fixture()
def db_conn():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    raw.executescript(_DDL)
    raw.commit()
    _seed(raw)
    yield raw, _FakeConn(raw)
    raw.close()


def _run_m026(fake_conn):
    import importlib.util, types
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m026_disable_non_spec_allocations.py",
    )
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text
    old_sa = sys.modules.get("sqlalchemy")
    old_mod = sys.modules.pop("m026_disable_non_spec_allocations", None)
    sys.modules["sqlalchemy"] = fake_sa
    try:
        spec = importlib.util.spec_from_file_location("m026_disable_non_spec_allocations", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(fake_conn)
    finally:
        if old_sa is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = old_sa
        sys.modules.pop("m026_disable_non_spec_allocations", None)
        if old_mod is not None:
            sys.modules["m026_disable_non_spec_allocations"] = old_mod


# ─── tests ────────────────────────────────────────────────────────────────

def test_disables_only_extras(db_conn):
    raw, fake = db_conn
    result = _run_m026(fake)
    assert result["executed"] is True
    assert result["extras_disabled"] == len(EXTRAS)
    assert result["spec_present_count"] == len(SPEC)
    # spec_missing is empty when all SPEC bots are present
    assert result["spec_missing"] == []

def test_spec_bots_stay_enabled(db_conn):
    raw, fake = db_conn
    _run_m026(fake)
    rows = raw.execute(
        """SELECT p.name FROM bot_allocations a JOIN bot_profiles p ON p.id=a.profile_id
            WHERE a.user_id=1 AND a.enabled=1"""
    ).fetchall()
    names = {r[0] for r in rows}
    assert names == SPEC

def test_extras_paused_reason_set(db_conn):
    raw, fake = db_conn
    _run_m026(fake)
    rows = raw.execute(
        """SELECT p.name, a.paused_reason FROM bot_allocations a
              JOIN bot_profiles p ON p.id=a.profile_id
            WHERE a.user_id=1 AND a.enabled=0"""
    ).fetchall()
    for name, reason in rows:
        assert name in EXTRAS
        assert reason == "m026_non_spec"

def test_user_3_untouched(db_conn):
    raw, fake = db_conn
    _run_m026(fake)
    count = raw.execute(
        "SELECT COUNT(*) FROM bot_allocations WHERE user_id=3 AND enabled=1"
    ).fetchone()[0]
    assert count == 2  # both seeded user-3 allocations still enabled

def test_idempotent_rerun_is_noop(db_conn):
    raw, fake = db_conn
    first = _run_m026(fake)
    second = _run_m026(fake)
    # First run disables EXTRAS; second has nothing left to disable.
    assert first["extras_disabled"] == len(EXTRAS)
    assert second["extras_disabled"] == 0

def test_hard_errors_if_no_spec_bots(db_conn):
    """If user_id=1 has no enabled SPEC allocations, refuse to proceed
    (suggests upstream m025 is broken)."""
    raw, fake = db_conn
    # Disable ALL SPEC bots first to simulate broken upstream state.
    raw.execute("""
        UPDATE bot_allocations SET enabled = 0
         WHERE user_id = 1 AND profile_id IN (
             SELECT id FROM bot_profiles
              WHERE name IN ('stock_swing','stock_lt','stock_day',
                             'crypto_day','crypto_swing','crypto_lt','crypto_onchain',
                             'options_income','options_directional',
                             'crypto_quant_aggressive','crypto_quant_mean_reversion','crypto_quant_scalper',
                             'cash_floor')
         )
    """)
    raw.commit()
    with pytest.raises(RuntimeError, match="no SPEC bot names found"):
        _run_m026(fake)
