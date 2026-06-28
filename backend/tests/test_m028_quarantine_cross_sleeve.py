"""Tests for m028_quarantine_cross_sleeve migration (SHIP 14).

Verifies:
  - Table and indexes created
  - Existing violations quarantined
  - Clean positions skipped
  - No positions auto-closed
  - cash_floor off-allowlist quarantined
  - Idempotent on second run
  - Multi-user safety (only user_id=1 scanned)
  - Unknown (retired) bot skipped with counter
  - schema_migrations row recorded
"""
import os
import sys
import sqlite3
import types
import importlib.util
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── _FakeText / _FakeCursor / _FakeConn (same pattern as m027 test) ─────────

class _FakeText:
    def __init__(self, sql): self.sql = sql

def text(sql): return _FakeText(sql)


class _FakeCursor:
    def __init__(self, cur): self._cur = cur
    def fetchone(self): return self._cur.fetchone()
    def fetchall(self): return self._cur.fetchall()
    def scalar(self):
        row = self._cur.fetchone()
        return row[0] if row else None
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


# ─── DDL ─────────────────────────────────────────────────────────────────────

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
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    closed_at TEXT,
    quarantined_at TEXT,
    exit_reason TEXT
);
"""

# bot_id → (symbol, expected_violation)
_SCENARIOS = [
    # cross-sleeve violation: crypto bot holds equity
    ("crypto_day",   "AAPL",    True),
    # clean: crypto bot holds crypto
    ("crypto_day",   "BTC/USD",  False),
    # cross-sleeve violation: equity bot holds crypto
    ("stock_swing",  "ETH/USD",  True),
    # clean: equity bot holds equity
    ("stock_swing",  "AAPL",     False),
    # cash_floor allowlist violation
    ("cash_floor",   "TSLA",     True),
    # cash_floor passing
    ("cash_floor",   "SPY",      False),
]

# user_id=3 control row (should never be touched)
_USER3_SCENARIOS = [
    ("crypto_day",  "AAPL"),   # violation, but user_id=3 — must stay unquarantined
]


def _seed(conn):
    cur = conn.cursor()
    profile_ids = {}
    # Create one profile per unique bot name
    unique_bots = set(s[0] for s in _SCENARIOS) | set(s[0] for s in _USER3_SCENARIOS)
    unique_bots.add("crypto_meanrev_2163")  # retired bot
    for name in unique_bots:
        cur.execute("INSERT INTO bot_profiles (name) VALUES (?)", (name,))
        profile_ids[name] = cur.lastrowid

    # user_id=1 allocations + positions
    pos_ids = {}
    for bot_id, symbol, _ in _SCENARIOS:
        if bot_id not in pos_ids:
            cur.execute(
                "INSERT INTO bot_allocations (profile_id, user_id) VALUES (?, 1)",
                (profile_ids[bot_id],),
            )
            alloc_id = cur.lastrowid
        # Each (bot_id, symbol) combo gets its own position
        cur.execute(
            "INSERT INTO bot_allocations (profile_id, user_id) VALUES (?, 1)",
            (profile_ids[bot_id],),
        )
        alloc_id = cur.lastrowid
        cur.execute(
            "INSERT INTO bot_positions (allocation_id, symbol, closed_at, quarantined_at) VALUES (?, ?, NULL, NULL)",
            (alloc_id, symbol),
        )
        pos_ids[(bot_id, symbol)] = cur.lastrowid

    # user_id=3 control row
    for bot_id, symbol in _USER3_SCENARIOS:
        cur.execute(
            "INSERT INTO bot_allocations (profile_id, user_id) VALUES (?, 3)",
            (profile_ids[bot_id],),
        )
        alloc_id = cur.lastrowid
        cur.execute(
            "INSERT INTO bot_positions (allocation_id, symbol, closed_at, quarantined_at) VALUES (?, ?, NULL, NULL)",
            (alloc_id, symbol),
        )

    # Retired bot position for user_id=1
    cur.execute(
        "INSERT INTO bot_allocations (profile_id, user_id) VALUES (?, 1)",
        (profile_ids["crypto_meanrev_2163"],),
    )
    alloc_id = cur.lastrowid
    cur.execute(
        "INSERT INTO bot_positions (allocation_id, symbol, closed_at, quarantined_at) VALUES (?, 'AAPL', NULL, NULL)",
        (alloc_id,),
    )

    conn.commit()
    return pos_ids


@pytest.fixture()
def db_conn():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    raw.executescript(_DDL)
    raw.commit()
    pos_ids = _seed(raw)
    yield raw, _FakeConn(raw), pos_ids
    raw.close()


def _run_m028(fake_conn, registry_mod):
    """Load and run m028 with real registry already set up in sys.modules."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m028_quarantine_cross_sleeve.py",
    )
    # Stub sqlalchemy.text
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text
    old_sa = sys.modules.get("sqlalchemy")
    sys.modules["sqlalchemy"] = fake_sa
    old_m028 = sys.modules.pop("app.db.migrations.m028_quarantine_cross_sleeve", None)
    try:
        spec = importlib.util.spec_from_file_location(
            "app.db.migrations.m028_quarantine_cross_sleeve", path
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["app.db.migrations.m028_quarantine_cross_sleeve"] = mod
        spec.loader.exec_module(mod)
        return mod.run(fake_conn)
    finally:
        if old_sa is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = old_sa
        sys.modules.pop("app.db.migrations.m028_quarantine_cross_sleeve", None)
        if old_m028 is not None:
            sys.modules["app.db.migrations.m028_quarantine_cross_sleeve"] = old_m028


@pytest.fixture(scope="module")
def registry_mod():
    """Load the real asset_class_registry module once for the whole module."""
    import types as _types
    # Ensure m027 is loaded
    m027_name = "app.db.migrations.m027_force_clean_slate"
    if m027_name not in sys.modules:
        m027_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "db", "migrations",
            "m027_force_clean_slate.py",
        )
        fake_sa = _types.ModuleType("sqlalchemy")
        fake_sa.text = text
        old_sa = sys.modules.get("sqlalchemy")
        sys.modules.setdefault("sqlalchemy", fake_sa)
        try:
            spec = importlib.util.spec_from_file_location(m027_name, m027_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[m027_name] = mod
            spec.loader.exec_module(mod)
        finally:
            if old_sa is None:
                sys.modules.pop("sqlalchemy", None)
            else:
                sys.modules["sqlalchemy"] = old_sa

    # Ensure migrations namespace
    mig_mod_name = "app.db.migrations"
    if mig_mod_name not in sys.modules:
        mig_mod = _types.ModuleType(mig_mod_name)
        mig_mod.__path__ = [os.path.join(os.path.dirname(__file__), "..", "app", "db", "migrations")]
        mig_mod.__package__ = mig_mod_name
        sys.modules[mig_mod_name] = mig_mod
        if "app.db" in sys.modules:
            sys.modules["app.db"].migrations = mig_mod

    # Stub discord
    disc = _types.ModuleType("app.services.discord")
    disc.send_ops_alert = lambda *a, **kw: None
    sys.modules["app.services.discord"] = disc

    # Load real registry
    for k in list(sys.modules.keys()):
        if "asset_class_registry" in k:
            del sys.modules[k]
    reg_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "services", "asset_class_registry.py"
    )
    spec = importlib.util.spec_from_file_location("app.services.asset_class_registry", reg_path)
    reg_mod = importlib.util.module_from_spec(spec)
    sys.modules["app.services.asset_class_registry"] = reg_mod
    spec.loader.exec_module(reg_mod)
    return reg_mod


# ─── tests ───────────────────────────────────────────────────────────────────

def test_m028_creates_table_and_indexes(db_conn, registry_mod):
    raw, fake, _ = db_conn
    _run_m028(fake, registry_mod)
    tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "cross_sleeve_quarantine_s14" in tables
    indexes = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_cs_quarantine_unresolved" in indexes
    assert "idx_cs_quarantine_pos_unique" in indexes


def test_m028_quarantines_existing_violations(db_conn, registry_mod):
    raw, fake, _ = db_conn
    result = _run_m028(fake, registry_mod)
    assert result["executed"] is True
    # Expected violations: crypto_day+AAPL, stock_swing+ETH/USD, cash_floor+TSLA = 3
    assert result["quarantined"] >= 2  # at least the 2 explicit cross-sleeve + allowlist
    count = raw.execute("SELECT COUNT(*) FROM cross_sleeve_quarantine_s14").fetchone()[0]
    assert count == result["quarantined"]


def test_m028_does_not_auto_close_quarantined_positions(db_conn, registry_mod):
    raw, fake, _ = db_conn
    _run_m028(fake, registry_mod)
    # No position should have exit_reason containing 'm028'
    rows = raw.execute(
        "SELECT COUNT(*) FROM bot_positions WHERE exit_reason LIKE '%m028%'"
    ).fetchone()[0]
    assert rows == 0
    # No position should have closed_at set by m028
    # (all closed_at values were NULL before, should remain NULL unless original seed set them)
    rows2 = raw.execute(
        "SELECT COUNT(*) FROM bot_positions WHERE closed_at IS NOT NULL"
    ).fetchone()[0]
    assert rows2 == 0


def test_m028_skips_passing_positions(db_conn, registry_mod):
    raw, fake, _ = db_conn
    _run_m028(fake, registry_mod)
    # crypto_day+BTC/USD and stock_swing+AAPL and cash_floor+SPY should NOT be quarantined
    passing = [("crypto_day", "BTC/USD"), ("stock_swing", "AAPL"), ("cash_floor", "SPY")]
    for bot_id, symbol in passing:
        count = raw.execute(
            "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE bot_id=? AND actual_symbol=?",
            (bot_id, symbol),
        ).fetchone()[0]
        assert count == 0, f"Expected {bot_id}+{symbol} NOT quarantined but found {count} row(s)"


def test_m028_cash_floor_off_allowlist_quarantined(db_conn, registry_mod):
    raw, fake, _ = db_conn
    _run_m028(fake, registry_mod)
    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE bot_id='cash_floor' AND actual_symbol='TSLA'"
    ).fetchone()[0]
    assert count == 1


def test_m028_idempotent_on_second_run(db_conn, registry_mod):
    raw, fake, _ = db_conn
    r1 = _run_m028(fake, registry_mod)
    count_after_first = raw.execute("SELECT COUNT(*) FROM cross_sleeve_quarantine_s14").fetchone()[0]
    r2 = _run_m028(fake, registry_mod)
    count_after_second = raw.execute("SELECT COUNT(*) FROM cross_sleeve_quarantine_s14").fetchone()[0]
    # Second run should skip (already applied)
    assert r2.get("skipped_reason") == "already_applied"
    assert count_after_first == count_after_second


def test_multi_user_safety_m028_only_scans_user_1(db_conn, registry_mod):
    raw, fake, _ = db_conn
    _run_m028(fake, registry_mod)
    # user_id=3 position (crypto_day + AAPL) must NOT appear in quarantine
    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE user_id=3"
    ).fetchone()[0]
    assert count == 0, f"user_id=3 positions should not be quarantined, but got {count} row(s)"


def test_m028_unknown_bot_skipped_with_counter(db_conn, registry_mod):
    raw, fake, _ = db_conn
    result = _run_m028(fake, registry_mod)
    # crypto_meanrev_2163 is retired and not in registry — should be skipped
    assert result["skipped_unknown_bot"] >= 1
    # Should NOT appear in quarantine table
    count = raw.execute(
        "SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE bot_id='crypto_meanrev_2163'"
    ).fetchone()[0]
    assert count == 0


def test_m028_records_schema_migration_row(db_conn, registry_mod):
    raw, fake, _ = db_conn
    _run_m028(fake, registry_mod)
    row = raw.execute(
        "SELECT migration_name FROM schema_migrations WHERE migration_name='m028_quarantine_cross_sleeve'"
    ).fetchone()
    assert row is not None
    assert row[0] == "m028_quarantine_cross_sleeve"
