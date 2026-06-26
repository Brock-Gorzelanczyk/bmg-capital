"""Tests for m024_corrective_capital_reset migration.

Uses an in-memory SQLite database seeded with the broken prod state
(m021/m022/m023 bugs) to verify the migration corrects all 13 enabled
bot_allocations for user_id=1 while leaving user_id=3 untouched.

Schema is a minimal subset of the real schema — only the columns m024
reads or writes. This keeps the fixture self-contained.
"""
import sys
import os
import sqlite3
import pytest

# Add backend/ to path so `app` is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── CONSTANTS ────────────────────────────────────────────────────────────────

ALLOCATIONS_CENTS = {
    "stock_swing":                 11_000_000,
    "stock_lt":                     9_000_000,
    "stock_day":                    7_000_000,
    "crypto_onchain":               9_000_000,
    "crypto_day":                   7_000_000,
    "crypto_swing":                 6_000_000,
    "crypto_lt":                    5_000_000,
    "options_directional":          5_000_000,
    "options_income":               5_000_000,
    "crypto_quant_mean_reversion": 11_000_000,
    "crypto_quant_aggressive":      8_000_000,
    "crypto_quant_scalper":         7_000_000,
    "cash_floor":                  10_000_000,
}

BOT_NAMES = list(ALLOCATIONS_CENTS.keys())

# The 4 "stuck" bots that m021/m023 left at $200K current_capital
STUCK_AT_200K = {
    "crypto_onchain",
    "crypto_quant_aggressive",
    "crypto_quant_mean_reversion",
    "crypto_quant_scalper",
}

# Realized P&L seeded for a subset of user_id=1 allocations (in cents)
SEEDED_REALIZED = {
    "stock_swing":                  500_000,   # +$5K
    "crypto_onchain":              -200_000,   # -$2K (one of the stuck bots)
    "crypto_quant_mean_reversion":  300_000,   # +$3K (another stuck bot)
}


# ─── SQLALCHEMY-LIKE CONNECTION ADAPTER ───────────────────────────────────────
# m024 expects a SQLAlchemy Connection (conn.execute(text(...), params)).
# We provide a thin adapter around sqlite3 so no SQLAlchemy dependency is
# needed in the test environment.

class _FakeText:
    """Wraps a raw SQL string like sqlalchemy.text()."""
    def __init__(self, sql: str):
        self.sql = sql

def text(sql: str) -> _FakeText:
    return _FakeText(sql)


class _FakeCursor:
    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _FakeConn:
    """Adapter that wraps sqlite3.Connection to look like a SQLAlchemy Connection.

    Maps conn.execute(text(sql), params_dict) → sqlite3 execute with
    :name-style parameters converted to ?-style for sqlite3.
    """
    def __init__(self, sqlite_conn: sqlite3.Connection):
        self._conn = sqlite_conn
        self._conn.row_factory = sqlite3.Row

    def execute(self, stmt, params=None):
        sql = stmt.sql if isinstance(stmt, _FakeText) else stmt
        # Convert :name params to ? style for sqlite3
        if params:
            import re
            keys_in_order = []
            def replace_param(m):
                keys_in_order.append(m.group(1))
                return "?"
            converted = re.sub(r":(\w+)", replace_param, sql)
            values = tuple(params[k] for k in keys_in_order)
            cur = self._conn.execute(converted, values)
        else:
            cur = self._conn.execute(sql)
        return _FakeCursor(cur)

    def commit(self):
        self._conn.commit()

    # For _table_exists / _column_exists which use PRAGMA directly
    # sqlite3 handles PRAGMA fine through the adapter above.


# ─── SCHEMA SETUP ─────────────────────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS bot_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    realized_cents INTEGER NOT NULL DEFAULT 0,
    trade_date TEXT
);
"""


def _create_schema(conn: sqlite3.Connection):
    conn.executescript(_DDL)
    conn.commit()


def _seed_db(conn: sqlite3.Connection):
    """Seed the DB with broken prod state for user_id=1 and clean state for user_id=3.

    user_id=1 (broken):
      - 13 bot_profiles + enabled allocations
      - starting_capital_cents = 10_000_000 for all (flat $100K — broken)
      - inception_capital_cents = 20_000_000 for all (contaminated $200K — broken)
      - current_capital_cents = 20_000_000 for the 4 stuck bots, else 10_000_000
      - some bot_daily_pnl rows for SEEDED_REALIZED bots

    user_id=3 (clean — should not be touched):
      - Same 13 bot profile names but different allocations
      - starting=5_000_000, inception=5_000_000, current=5_000_000 for all
    """
    cur = conn.cursor()

    # ── user_id=1 bot profiles ────────────────────────────────────────────────
    profile_ids_u1 = {}
    for name in BOT_NAMES:
        cur.execute(
            "INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)",
            (name, 1),
        )
        profile_ids_u1[name] = cur.lastrowid

    # ── user_id=1 bot allocations (broken state) ──────────────────────────────
    alloc_ids_u1 = {}
    for name, prof_id in profile_ids_u1.items():
        broken_starting  = 10_000_000          # all flat $100K — wrong
        broken_inception = 20_000_000          # contaminated $200K — wrong
        broken_current   = 20_000_000 if name in STUCK_AT_200K else 10_000_000
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 1, 1, ?, ?, ?, '2024-01-01T00:00:00')""",
            (prof_id, broken_starting, broken_inception, broken_current),
        )
        alloc_ids_u1[name] = cur.lastrowid

    # ── bot_daily_pnl for user_id=1 (some realized P&L history) ──────────────
    for name, realized in SEEDED_REALIZED.items():
        alloc_id = alloc_ids_u1[name]
        # Split into 2 rows to test SUM aggregation
        half = realized // 2
        remainder = realized - half
        cur.execute(
            "INSERT INTO bot_daily_pnl (allocation_id, realized_cents, trade_date) VALUES (?, ?, '2024-06-01')",
            (alloc_id, half),
        )
        cur.execute(
            "INSERT INTO bot_daily_pnl (allocation_id, realized_cents, trade_date) VALUES (?, ?, '2024-06-02')",
            (alloc_id, remainder),
        )

    # ── user_id=3 bot profiles + allocations (should never be touched) ────────
    profile_ids_u3 = {}
    for name in BOT_NAMES:
        cur.execute(
            "INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)",
            (name, 3),
        )
        profile_ids_u3[name] = cur.lastrowid

    alloc_ids_u3 = {}
    for name, prof_id in profile_ids_u3.items():
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 3, 1, 5000000, 5000000, 5000000, '2024-01-01T00:00:00')""",
            (prof_id,),
        )
        alloc_ids_u3[name] = cur.lastrowid

    conn.commit()
    return alloc_ids_u1, alloc_ids_u3


# ─── FIXTURES ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_conn():
    """Return a pair (sqlite3.Connection, _FakeConn) with schema + broken seed."""
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    _create_schema(raw)
    alloc_ids_u1, alloc_ids_u3 = _seed_db(raw)
    fake = _FakeConn(raw)
    yield raw, fake, alloc_ids_u1, alloc_ids_u3
    raw.close()


def _run_migration(fake_conn: _FakeConn):
    """Import and run the migration using our adapter.

    Uses importlib.util.spec_from_file_location to load the migration directly
    from its file path, bypassing the mock app.db module hierarchy installed
    by conftest.py (which prevents import via the normal package path).
    """
    import importlib.util
    import types

    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "app",
        "db",
        "migrations",
        "m024_corrective_capital_reset.py",
    )

    # Build a minimal fake sqlalchemy module that exposes our text() stub.
    # The migration does `from sqlalchemy import text` at module level so we
    # must inject the stub BEFORE the module is loaded.
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text

    old_sa = sys.modules.get("sqlalchemy")
    # Also temporarily remove any cached version of the migration module so
    # each test gets a fresh load (avoids stale state from previous runs).
    _mod_key = "m024_corrective_capital_reset"
    old_mod = sys.modules.pop(_mod_key, None)

    sys.modules["sqlalchemy"] = fake_sa

    try:
        spec = importlib.util.spec_from_file_location(_mod_key, migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(fake_conn)
    finally:
        # Restore original sqlalchemy module (or remove our stub)
        if old_sa is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = old_sa
        # Clean up the migration module from sys.modules
        sys.modules.pop(_mod_key, None)
        if old_mod is not None:
            sys.modules[_mod_key] = old_mod


# ─── TESTS ────────────────────────────────────────────────────────────────────

class TestM024HappyPath:
    """Verify the migration executes correctly against the seeded broken state."""

    def test_returns_executed_true(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert result["executed"] is True

    def test_rows_updated_is_13(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert result["rows_updated"] == 13

    def test_sum_starting_cents_equals_1m(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        row = raw.execute(
            "SELECT SUM(starting_capital_cents) FROM bot_allocations WHERE user_id=1 AND enabled=1"
        ).fetchone()
        assert row[0] == 100_000_000, f"Expected 100_000_000 got {row[0]}"

    def test_sum_inception_cents_equals_1m(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        row = raw.execute(
            "SELECT SUM(inception_capital_cents) FROM bot_allocations WHERE user_id=1 AND enabled=1"
        ).fetchone()
        assert row[0] == 100_000_000, f"Expected 100_000_000 got {row[0]}"

    def test_per_bot_starting_capital_matches_spec(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.starting_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1"""
        ).fetchall()
        assert len(rows) == 13, f"Expected 13 rows, got {len(rows)}"
        for row in rows:
            name = row[0]
            starting = row[1]
            expected = ALLOCATIONS_CENTS[name]
            assert starting == expected, (
                f"{name}: starting_capital_cents={starting}, expected {expected}"
            )

    def test_per_bot_inception_capital_matches_spec(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.inception_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1"""
        ).fetchall()
        for row in rows:
            name = row[0]
            inception = row[1]
            expected = ALLOCATIONS_CENTS[name]
            assert inception == expected, (
                f"{name}: inception_capital_cents={inception}, expected {expected}"
            )

    def test_inception_equals_starting_per_bot(self, db_conn):
        """inception_capital_cents must equal starting_capital_cents for every bot."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.starting_capital_cents, a.inception_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1"""
        ).fetchall()
        for row in rows:
            name, starting, inception = row[0], row[1], row[2]
            assert starting == inception, (
                f"{name}: starting={starting} != inception={inception}"
            )

    def test_current_capital_equals_starting_plus_realized(self, db_conn):
        """current_capital_cents = spec_cents + SUM(realized_cents) from bot_daily_pnl."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.id AS alloc_id,
                      a.starting_capital_cents, a.current_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1"""
        ).fetchall()
        for row in rows:
            name, alloc_id, starting, current = row[0], row[1], row[2], row[3]
            pnl_row = raw.execute(
                "SELECT COALESCE(SUM(realized_cents), 0) FROM bot_daily_pnl WHERE allocation_id=?",
                (alloc_id,),
            ).fetchone()
            realized = pnl_row[0]
            expected_current = starting + realized
            assert current == expected_current, (
                f"{name}: current={current}, expected {expected_current} "
                f"(starting={starting} + realized={realized})"
            )


class TestM024MultiUserIsolation:
    """Verify user_id=3 rows are byte-identical before and after migration."""

    def test_user3_starting_capital_unchanged(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        # Snapshot user_id=3 before
        before = raw.execute(
            "SELECT id, starting_capital_cents FROM bot_allocations WHERE user_id=3 ORDER BY id"
        ).fetchall()
        _run_migration(fake)
        after = raw.execute(
            "SELECT id, starting_capital_cents FROM bot_allocations WHERE user_id=3 ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after], \
            "user_id=3 starting_capital_cents changed — multi-user safety violation"

    def test_user3_inception_capital_unchanged(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        before = raw.execute(
            "SELECT id, inception_capital_cents FROM bot_allocations WHERE user_id=3 ORDER BY id"
        ).fetchall()
        _run_migration(fake)
        after = raw.execute(
            "SELECT id, inception_capital_cents FROM bot_allocations WHERE user_id=3 ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after], \
            "user_id=3 inception_capital_cents changed — multi-user safety violation"

    def test_user3_current_capital_unchanged(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        before = raw.execute(
            "SELECT id, current_capital_cents FROM bot_allocations WHERE user_id=3 ORDER BY id"
        ).fetchall()
        _run_migration(fake)
        after = raw.execute(
            "SELECT id, current_capital_cents FROM bot_allocations WHERE user_id=3 ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after], \
            "user_id=3 current_capital_cents changed — multi-user safety violation"

    def test_user3_full_row_byte_identical(self, db_conn):
        """All columns for user_id=3 rows must be identical before and after."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        before = raw.execute(
            """SELECT id, profile_id, user_id, enabled,
                      starting_capital_cents, inception_capital_cents, current_capital_cents
                 FROM bot_allocations WHERE user_id=3 ORDER BY id"""
        ).fetchall()
        _run_migration(fake)
        after = raw.execute(
            """SELECT id, profile_id, user_id, enabled,
                      starting_capital_cents, inception_capital_cents, current_capital_cents
                 FROM bot_allocations WHERE user_id=3 ORDER BY id"""
        ).fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after], \
            "user_id=3 rows were mutated by m024 — multi-user safety violation"

    def test_migration_result_other_users_touched_is_zero(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert result["other_users_touched"] == 0


class TestM024Idempotency:
    """Running the migration twice must produce the same final state."""

    def test_second_run_short_circuits(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)  # first run
        result2 = _run_migration(fake)  # second run
        assert result2["executed"] is False
        assert result2.get("skipped_reason") == "already_applied"

    def test_second_run_state_is_identical(self, db_conn):
        """State after 2nd run matches state after 1st run."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        snapshot_after_first = raw.execute(
            """SELECT id, starting_capital_cents, inception_capital_cents, current_capital_cents
                 FROM bot_allocations WHERE user_id=1 ORDER BY id"""
        ).fetchall()
        _run_migration(fake)
        snapshot_after_second = raw.execute(
            """SELECT id, starting_capital_cents, inception_capital_cents, current_capital_cents
                 FROM bot_allocations WHERE user_id=1 ORDER BY id"""
        ).fetchall()
        assert [tuple(r) for r in snapshot_after_first] == [tuple(r) for r in snapshot_after_second]


class TestM024Guards:
    """Edge-case guard paths per spec."""

    def test_skips_when_inception_column_missing(self):
        """Migration must return skipped (not raise) when inception_capital_cents missing."""
        raw = sqlite3.connect(":memory:")
        raw.executescript("""
            CREATE TABLE schema_migrations (id INTEGER PRIMARY KEY, migration_name TEXT UNIQUE);
            CREATE TABLE bot_profiles (id INTEGER PRIMARY KEY, name TEXT, user_id INTEGER);
            CREATE TABLE bot_allocations (
                id INTEGER PRIMARY KEY,
                profile_id INTEGER,
                user_id INTEGER,
                enabled INTEGER,
                starting_capital_cents INTEGER,
                current_capital_cents INTEGER,
                updated_at TEXT
            );
            CREATE TABLE bot_daily_pnl (id INTEGER PRIMARY KEY, allocation_id INTEGER, realized_cents INTEGER);
        """)
        raw.commit()
        fake = _FakeConn(raw)
        result = _run_migration(fake)
        assert result["executed"] is False
        assert "inception_capital_cents" in result["skipped_reason"]
        raw.close()

    def test_skips_when_current_column_missing(self):
        """Migration must return skipped (not raise) when current_capital_cents missing."""
        raw = sqlite3.connect(":memory:")
        raw.executescript("""
            CREATE TABLE schema_migrations (id INTEGER PRIMARY KEY, migration_name TEXT UNIQUE);
            CREATE TABLE bot_profiles (id INTEGER PRIMARY KEY, name TEXT, user_id INTEGER);
            CREATE TABLE bot_allocations (
                id INTEGER PRIMARY KEY,
                profile_id INTEGER,
                user_id INTEGER,
                enabled INTEGER,
                starting_capital_cents INTEGER,
                inception_capital_cents INTEGER,
                updated_at TEXT
            );
            CREATE TABLE bot_daily_pnl (id INTEGER PRIMARY KEY, allocation_id INTEGER, realized_cents INTEGER);
        """)
        raw.commit()
        fake = _FakeConn(raw)
        result = _run_migration(fake)
        assert result["executed"] is False
        assert "current_capital_cents" in result["skipped_reason"]
        raw.close()

    def test_skips_when_bot_allocations_table_missing(self):
        raw = sqlite3.connect(":memory:")
        raw.executescript("""
            CREATE TABLE schema_migrations (id INTEGER PRIMARY KEY, migration_name TEXT UNIQUE);
            CREATE TABLE bot_profiles (id INTEGER PRIMARY KEY, name TEXT, user_id INTEGER);
            CREATE TABLE bot_daily_pnl (id INTEGER PRIMARY KEY, allocation_id INTEGER, realized_cents INTEGER);
        """)
        raw.commit()
        fake = _FakeConn(raw)
        result = _run_migration(fake)
        assert result["executed"] is False
        assert "bot_allocations" in result["skipped_reason"]
        raw.close()

    def test_hard_errors_when_bot_missing_from_profiles(self, db_conn):
        """If a required bot is absent from enabled allocations, must RuntimeError."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        # Disable one of the 13 bots to simulate a missing enabled allocation
        raw.execute(
            "UPDATE bot_allocations SET enabled=0 WHERE id=?",
            (alloc_ids_u1["cash_floor"],),
        )
        raw.commit()
        with pytest.raises(RuntimeError, match=r"\[m024\] missing enabled allocation for user 1 bot: cash_floor"):
            _run_migration(fake)

    def test_hard_errors_when_zero_enabled_rows_for_user1(self, db_conn):
        """If user_id=1 has NO enabled allocations, must RuntimeError."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        raw.execute("UPDATE bot_allocations SET enabled=0 WHERE user_id=1")
        raw.commit()
        with pytest.raises(RuntimeError, match=r"\[m024\] user_id=1 has 0 enabled bot_allocations"):
            _run_migration(fake)

    def test_no_pnl_rows_means_current_equals_starting(self, db_conn):
        """Bots with zero daily_pnl rows must have current = starting (COALESCE)."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        # Remove ALL bot_daily_pnl rows
        raw.execute("DELETE FROM bot_daily_pnl")
        raw.commit()
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.starting_capital_cents, a.current_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1"""
        ).fetchall()
        for row in rows:
            name, starting, current = row[0], row[1], row[2]
            assert current == starting, (
                f"{name}: expected current=starting={starting}, got current={current}"
            )

    def test_duplicate_alloc_ids_reported_picks_min(self, db_conn):
        """When a bot has 2 enabled alloc rows, migration must:
          - UPDATE only MIN(id) (the canonical row) for that bot
          - Scope Step 6 acceptance gate to canonical alloc_ids only (no false RuntimeError)
          - Report the duplicate id(s) in result['duplicate_alloc_ids']
          - Execute successfully (return executed=True)

        Verifies spec edge case 3: pick MIN(id), report dupes in
        duplicate_alloc_ids, execute successfully.
        """
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        # Insert a second enabled row for stock_swing under user_id=1
        prof_id_row = raw.execute(
            "SELECT id FROM bot_profiles WHERE name='stock_swing' AND user_id=1"
        ).fetchone()
        prof_id = prof_id_row[0]
        raw.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 1, 1, 99999, 99999, 99999, '2024-01-01T00:00:00')""",
            (prof_id,),
        )
        raw.commit()
        # Step 6 now scopes by canonical alloc_id set — no false RuntimeError on duplicate.
        result = _run_migration(fake)
        assert result["executed"] is True, "Migration must succeed even with duplicate enabled rows"
        assert "duplicate_alloc_ids" in result, "duplicate_alloc_ids must be reported in result"
        assert "stock_swing" in result["duplicate_alloc_ids"], (
            "stock_swing must appear in duplicate_alloc_ids"
        )
        # The canonical (MIN id) row must carry the correct spec value
        canonical_alloc_id = alloc_ids_u1["stock_swing"]
        row = raw.execute(
            "SELECT starting_capital_cents, inception_capital_cents FROM bot_allocations WHERE id=?",
            (canonical_alloc_id,),
        ).fetchone()
        expected = ALLOCATIONS_CENTS["stock_swing"]
        assert row[0] == expected, f"canonical stock_swing starting={row[0]}, expected {expected}"
        assert row[1] == expected, f"canonical stock_swing inception={row[1]}, expected {expected}"


class TestM024LeaderboardMath:
    """Verify that with inception=starting and small realized PNL, all-time % is within ±5%."""

    def test_all_time_pct_within_5pct_of_zero(self, db_conn):
        """After reset, (realized / inception) must be within [-0.05, 0.05] for every bot."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.inception_capital_cents, a.id AS alloc_id
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1"""
        ).fetchall()
        for row in rows:
            name, inception, alloc_id = row[0], row[1], row[2]
            pnl_row = raw.execute(
                "SELECT COALESCE(SUM(realized_cents), 0) FROM bot_daily_pnl WHERE allocation_id=?",
                (alloc_id,),
            ).fetchone()
            cumulative_pnl = pnl_row[0]
            if inception == 0:
                continue  # avoid ZeroDivisionError; inception should never be 0 post-migration
            all_time_pct = (cumulative_pnl / inception) * 100.0
            assert -5.0 <= all_time_pct <= 5.0, (
                f"{name}: all_time_pct={all_time_pct:.2f}% is outside ±5% "
                f"(realized={cumulative_pnl}, inception={inception})"
            )

    def test_inception_never_zero_after_migration(self, db_conn):
        """inception_capital_cents must be > 0 for every user_id=1 enabled bot."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        rows = raw.execute(
            "SELECT inception_capital_cents FROM bot_allocations WHERE user_id=1 AND enabled=1"
        ).fetchall()
        for row in rows:
            assert row[0] > 0, f"inception_capital_cents is zero — leaderboard division-by-zero risk"


class TestM024SpecTotals:
    """Boundary and totals checks."""

    def test_allocations_cents_sums_to_1m(self):
        """Module-level assertion: ALLOCATIONS_CENTS must sum to exactly $1M."""
        assert sum(ALLOCATIONS_CENTS.values()) == 100_000_000

    def test_exactly_13_bots_enabled_after_migration(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        _run_migration(fake)
        row = raw.execute(
            "SELECT COUNT(*) FROM bot_allocations WHERE user_id=1 AND enabled=1"
        ).fetchone()
        assert row[0] == 13

    def test_result_per_bot_has_13_entries(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert len(result["per_bot"]) == 13

    def test_result_sum_starting_cents_field(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert result["sum_starting_cents"] == 100_000_000

    def test_result_sum_inception_cents_field(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert result["sum_inception_cents"] == 100_000_000

    def test_result_user_id_field(self, db_conn):
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        result = _run_migration(fake)
        assert result["user_id"] == 1

    def test_disabled_rows_not_touched(self, db_conn):
        """enabled=0 rows must not be modified by the migration."""
        raw, fake, alloc_ids_u1, alloc_ids_u3 = db_conn
        # Add an extra disabled row for stock_swing under user_id=1
        prof_id_row = raw.execute(
            "SELECT id FROM bot_profiles WHERE name='stock_swing' AND user_id=1"
        ).fetchone()
        raw.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 1, 0, 77777, 77777, 77777, '2024-01-01T00:00:00')""",
            (prof_id_row[0],),
        )
        raw.commit()
        disabled_id = raw.execute(
            "SELECT id FROM bot_allocations WHERE user_id=1 AND enabled=0 AND starting_capital_cents=77777"
        ).fetchone()[0]

        _run_migration(fake)

        # The disabled row must be untouched
        row = raw.execute(
            "SELECT starting_capital_cents, inception_capital_cents FROM bot_allocations WHERE id=?",
            (disabled_id,),
        ).fetchone()
        assert row[0] == 77777, "Disabled row starting_capital_cents was mutated"
        assert row[1] == 77777, "Disabled row inception_capital_cents was mutated"
