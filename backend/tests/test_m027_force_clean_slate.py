"""Tests for m027_force_clean_slate migration.

Verifies:
  - Hard reset to $1M, all 3 capital columns set to spec value
  - Inflated extras (non-SPEC names) get DELETED, not just disabled
  - bot_trades and bot_daily_pnl wiped for user 1
  - capital_audit_log populated with m027_pre_reset and m027_post_reset rows
  - Open positions closed with exit_reason='m027_force_clean_slate'
  - user_id != 1 untouched
  - Idempotent: second run skips
"""
import os
import sys
import sqlite3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


ALLOCATIONS_CENTS = {
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
BOT_NAMES = list(ALLOCATIONS_CENTS.keys())

EXTRAS = ("stock_momentum", "crypto_arbitrage", "options_iron_condor")


# ─── adapter (same pattern as m024/m025/m026 tests) ──────────────────────────

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
    inception_capital_cents INTEGER NOT NULL DEFAULT 0,
    current_capital_cents   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT, qty INTEGER, fill_price_cents INTEGER
);
CREATE TABLE IF NOT EXISTS bot_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    realized_cents INTEGER NOT NULL DEFAULT 0,
    trade_date TEXT
);
CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT, qty INTEGER,
    closed_at TEXT, quarantined_at TEXT, exit_reason TEXT
);
"""


def _seed(conn):
    cur = conn.cursor()
    # user_id=1 — inflated state: spec bots + EXTRAS, all at varied capital
    alloc_ids_by_name = {}
    for name in list(BOT_NAMES) + list(EXTRAS):
        cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 1))
        pid = cur.lastrowid
        # Pre-m027 broken state: 3x inflated like the audit-described prod state.
        inflated = ALLOCATIONS_CENTS.get(name, 8_000_000) * 3
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 1, 1, ?, ?, ?, '2024-01-01T00:00:00')""",
            (pid, inflated, inflated, inflated),
        )
        alloc_ids_by_name[name] = cur.lastrowid

    # Some trade + daily_pnl history to be wiped
    for name in ("stock_swing", "crypto_quant_mean_reversion"):
        aid = alloc_ids_by_name[name]
        cur.execute("INSERT INTO bot_trades (allocation_id, symbol, qty, fill_price_cents) VALUES (?, 'AAPL', 10, 15000)", (aid,))
        cur.execute("INSERT INTO bot_daily_pnl (allocation_id, realized_cents, trade_date) VALUES (?, 500000, '2024-06-01')", (aid,))

    # One open position to be closed
    aid = alloc_ids_by_name["stock_swing"]
    cur.execute(
        "INSERT INTO bot_positions (allocation_id, symbol, qty, closed_at, quarantined_at, exit_reason) VALUES (?, 'AAPL', 5, NULL, NULL, NULL)",
        (aid,),
    )

    # user_id=3 control (different bots)
    for name in ("stock_swing", "crypto_day"):
        cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 3))
        pid = cur.lastrowid
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 3, 1, 5000000, 5000000, 5000000, '2024-01-01T00:00:00')""",
            (pid,),
        )
    conn.commit()
    return alloc_ids_by_name


@pytest.fixture()
def db_conn():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    raw.executescript(_DDL)
    raw.commit()
    alloc_ids = _seed(raw)
    yield raw, _FakeConn(raw), alloc_ids
    raw.close()


def _run_m027(fake_conn):
    import importlib.util, types
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m027_force_clean_slate.py",
    )
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text
    old_sa = sys.modules.get("sqlalchemy")
    old_mod = sys.modules.pop("m027_force_clean_slate", None)
    sys.modules["sqlalchemy"] = fake_sa
    try:
        spec = importlib.util.spec_from_file_location("m027_force_clean_slate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(fake_conn)
    finally:
        if old_sa is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = old_sa
        sys.modules.pop("m027_force_clean_slate", None)
        if old_mod is not None:
            sys.modules["m027_force_clean_slate"] = old_mod


# ─── tests ───────────────────────────────────────────────────────────────────

def test_executed_returns_true(db_conn):
    _, fake, _ = db_conn
    result = _run_m027(fake)
    assert result["executed"] is True
    assert result["rows_updated"] == 13
    assert result["sum_starting_cents"] == 100_000_000

def test_sum_is_exactly_1m_after_run(db_conn):
    raw, fake, _ = db_conn
    _run_m027(fake)
    total = raw.execute(
        "SELECT SUM(starting_capital_cents) FROM bot_allocations WHERE user_id=1 AND enabled=1"
    ).fetchone()[0]
    assert total == 100_000_000

def test_all_three_capital_columns_set_to_spec(db_conn):
    raw, fake, _ = db_conn
    _run_m027(fake)
    rows = raw.execute("""
        SELECT p.name, a.starting_capital_cents, a.inception_capital_cents, a.current_capital_cents
          FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = 1 AND a.enabled = 1
    """).fetchall()
    by_name = {r[0]: (r[1], r[2], r[3]) for r in rows}
    for name, expected in ALLOCATIONS_CENTS.items():
        s, i, c = by_name[name]
        assert s == expected, f"{name} starting={s} != {expected}"
        assert i == expected, f"{name} inception={i} != {expected}"
        assert c == expected, f"{name} current={c} != {expected}"

def test_extras_deleted_outright(db_conn):
    raw, fake, _ = db_conn
    result = _run_m027(fake)
    assert result["extras_deleted"] == len(EXTRAS)
    # Verify no extras left for user 1
    rows = raw.execute("""
        SELECT p.name FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = 1
    """).fetchall()
    names = {r[0] for r in rows}
    assert names == set(BOT_NAMES)
    for extra in EXTRAS:
        assert extra not in names

def test_trades_wiped_for_user_1(db_conn):
    raw, fake, _ = db_conn
    _run_m027(fake)
    remaining = raw.execute("""
        SELECT COUNT(*) FROM bot_trades
         WHERE allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = 1)
    """).fetchone()[0]
    assert remaining == 0

def test_daily_pnl_wiped_for_user_1(db_conn):
    raw, fake, _ = db_conn
    _run_m027(fake)
    remaining = raw.execute("""
        SELECT COUNT(*) FROM bot_daily_pnl
         WHERE allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = 1)
    """).fetchone()[0]
    assert remaining == 0

def test_open_positions_closed_with_m027_reason(db_conn):
    raw, fake, _ = db_conn
    result = _run_m027(fake)
    assert result["positions_closed"] >= 1
    open_after = raw.execute("""
        SELECT COUNT(*) FROM bot_positions
         WHERE closed_at IS NULL AND quarantined_at IS NULL
           AND allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = 1)
    """).fetchone()[0]
    assert open_after == 0
    # Reason recorded
    reason = raw.execute(
        "SELECT exit_reason FROM bot_positions WHERE allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = 1) LIMIT 1"
    ).fetchone()[0]
    assert reason == "m027_force_clean_slate"

def test_audit_log_has_pre_and_post_rows(db_conn):
    raw, fake, _ = db_conn
    _run_m027(fake)
    pre = raw.execute("SELECT COUNT(*) FROM capital_audit_log WHERE note = 'm027_pre_reset'").fetchone()[0]
    post = raw.execute("SELECT COUNT(*) FROM capital_audit_log WHERE note = 'm027_post_reset'").fetchone()[0]
    # 3 fields per bot per phase
    assert pre > 0
    assert post == 3 * len(BOT_NAMES)

def test_user_3_untouched(db_conn):
    raw, fake, _ = db_conn
    _run_m027(fake)
    user3_total = raw.execute(
        "SELECT SUM(starting_capital_cents) FROM bot_allocations WHERE user_id=3 AND enabled=1"
    ).fetchone()[0]
    assert user3_total == 2 * 5_000_000  # 2 user-3 bots seeded at $50K

def test_other_users_touched_is_zero(db_conn):
    _, fake, _ = db_conn
    result = _run_m027(fake)
    assert result["other_users_touched"] == 0

def test_idempotent_second_run_skips(db_conn):
    _, fake, _ = db_conn
    first = _run_m027(fake)
    assert first["executed"] is True
    second = _run_m027(fake)
    assert second["executed"] is False
    assert second["skipped_reason"] == "already_applied"
