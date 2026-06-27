"""Tests for m025_clean_slate_one_million migration.

Verifies:
  - Hard reset to $1M across the 13 enabled bots for user_id=1
  - Intra-sleeve rebalance matches the m025 spec (different from m024)
  - Duplicate enabled rows inventoried into cross_alloc_quarantine_m025
  - user_id != 1 rows are NOT touched
  - Idempotency via schema_migrations
"""
import sys
import os
import sqlite3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# m025 canonical allocations (per Brock's SHIP RECAP, mapped to real bot_ids).
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


# ─── adapter (same shape as test_m024) ────────────────────────────────────────

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


def _seed(conn: sqlite3.Connection):
    """Seed broken pre-m025 state for user_id=1 + clean state for user_id=3.

    user_id=1 starting values mirror what production looked like at audit time
    (~$3M total, m024 amounts but inflated): values do not matter for the
    correctness of the reset — m025 writes absolute targets.

    Includes one duplicate enabled row for crypto_quant_mean_reversion to exercise
    the quarantine path.
    """
    cur = conn.cursor()
    prof_ids = {}
    for name in BOT_NAMES:
        cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 1))
        prof_ids[name] = cur.lastrowid

    alloc_ids = {}
    for name, pid in prof_ids.items():
        # Pre-m025 broken state: roughly 3x inflated vs m024 spec.
        broken = ALLOCATIONS_CENTS[name] * 3
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 1, 1, ?, ?, ?, '2024-01-01T00:00:00')""",
            (pid, broken, broken, broken),
        )
        alloc_ids[name] = cur.lastrowid

    # Dup enabled row for crypto_quant_mean_reversion — exercises quarantine path.
    cur.execute(
        """INSERT INTO bot_allocations
           (profile_id, user_id, enabled, starting_capital_cents,
            inception_capital_cents, current_capital_cents, updated_at)
           VALUES (?, 1, 1, 99999, 99999, 99999, '2024-01-01T00:00:00')""",
        (prof_ids["crypto_quant_mean_reversion"],),
    )
    dup_alloc_id = cur.lastrowid

    # user_id=3 untouched control
    prof_ids_u3 = {}
    for name in BOT_NAMES:
        cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 3))
        prof_ids_u3[name] = cur.lastrowid
    for name, pid in prof_ids_u3.items():
        cur.execute(
            """INSERT INTO bot_allocations
               (profile_id, user_id, enabled, starting_capital_cents,
                inception_capital_cents, current_capital_cents, updated_at)
               VALUES (?, 3, 1, 5000000, 5000000, 5000000, '2024-01-01T00:00:00')""",
            (pid,),
        )
    conn.commit()
    return alloc_ids, dup_alloc_id


# ─── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_conn():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    raw.executescript(_DDL)
    raw.commit()
    alloc_ids, dup_id = _seed(raw)
    fake = _FakeConn(raw)
    yield raw, fake, alloc_ids, dup_id
    raw.close()


def _run_migration(fake_conn):
    import importlib.util, types
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "db", "migrations",
        "m025_clean_slate_one_million.py",
    )
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = text
    old_sa = sys.modules.get("sqlalchemy")
    old_mod = sys.modules.pop("m025_clean_slate_one_million", None)
    sys.modules["sqlalchemy"] = fake_sa
    try:
        spec = importlib.util.spec_from_file_location("m025_clean_slate_one_million", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run(fake_conn)
    finally:
        if old_sa is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = old_sa
        sys.modules.pop("m025_clean_slate_one_million", None)
        if old_mod is not None:
            sys.modules["m025_clean_slate_one_million"] = old_mod


# ─── tests ────────────────────────────────────────────────────────────────────

class TestM025HappyPath:
    def test_executed_true(self, db_conn):
        _, fake, _, _ = db_conn
        result = _run_migration(fake)
        assert result["executed"] is True
        assert result["rows_updated"] == 13
        assert result["sum_starting_cents"] == 100_000_000
        assert result["sum_inception_cents"] == 100_000_000

    def test_per_bot_matches_spec(self, db_conn):
        raw, fake, _, _ = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.starting_capital_cents, a.inception_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.starting_capital_cents = ?""",
            (0,),
        ).fetchall()
        # Use the canonical alloc set instead — fetch all, filter to spec names.
        all_rows = raw.execute(
            """SELECT p.name, MIN(a.id), a.starting_capital_cents, a.inception_capital_cents
                 FROM bot_allocations a
                 JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1
                GROUP BY p.name"""
        ).fetchall()
        by_name = {r[0]: (r[2], r[3]) for r in all_rows}
        for name, expected in ALLOCATIONS_CENTS.items():
            assert by_name[name][0] == expected, f"{name} starting={by_name[name][0]}, expected {expected}"
            assert by_name[name][1] == expected, f"{name} inception={by_name[name][1]}, expected {expected}"

    def test_intra_sleeve_rebalance_vs_m024(self, db_conn):
        """The whole point of m025 vs m024 — confirm the reallocation deltas."""
        raw, fake, _, _ = db_conn
        _run_migration(fake)
        rows = raw.execute(
            """SELECT p.name, a.starting_capital_cents
                 FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id
                WHERE a.user_id = 1 AND a.enabled = 1
                GROUP BY p.name"""
        ).fetchall()
        by_name = {r[0]: r[1] for r in rows}
        # crypto_onchain demoted $90K -> $50K
        assert by_name["crypto_onchain"] == 5_000_000
        # crypto_quant_aggressive promoted $80K -> $110K
        assert by_name["crypto_quant_aggressive"] == 11_000_000
        # crypto_quant_mean_reversion demoted $110K -> $80K
        assert by_name["crypto_quant_mean_reversion"] == 8_000_000


class TestM025MultiUserSafety:
    def test_user3_untouched(self, db_conn):
        raw, fake, _, _ = db_conn
        _run_migration(fake)
        row = raw.execute(
            "SELECT SUM(starting_capital_cents) FROM bot_allocations WHERE user_id = 3"
        ).fetchone()
        # 13 bots at 5_000_000 each = 65_000_000
        assert row[0] == 13 * 5_000_000

    def test_other_users_touched_is_zero(self, db_conn):
        _, fake, _, _ = db_conn
        result = _run_migration(fake)
        assert result["other_users_touched"] == 0


class TestM025Idempotency:
    def test_second_run_skips(self, db_conn):
        _, fake, _, _ = db_conn
        first = _run_migration(fake)
        assert first["executed"] is True
        second = _run_migration(fake)
        assert second["executed"] is False
        assert second["skipped_reason"] == "already_applied"

    def test_schema_migrations_recorded(self, db_conn):
        raw, fake, _, _ = db_conn
        _run_migration(fake)
        row = raw.execute(
            "SELECT migration_name FROM schema_migrations WHERE migration_name = 'm025_clean_slate_one_million'"
        ).fetchone()
        assert row is not None


class TestM025Quarantine:
    def test_duplicate_alloc_quarantined(self, db_conn):
        raw, fake, _, dup_id = db_conn
        result = _run_migration(fake)
        # The seeded dup row for crypto_quant_mean_reversion should be inventoried.
        assert result["quarantined"] >= 1
        assert "crypto_quant_mean_reversion" in result.get("duplicate_alloc_ids", {})

        row = raw.execute(
            """SELECT bot_name, canonical_alloc_id, duplicate_alloc_id, user_id, action
                 FROM cross_alloc_quarantine_m025
                WHERE duplicate_alloc_id = ?""",
            (dup_id,),
        ).fetchone()
        assert row is not None, "expected duplicate to be quarantined"
        assert row[0] == "crypto_quant_mean_reversion"
        assert row[3] == 1
        assert row[4] == "review"

    def test_canonical_picked_min_id_for_dup(self, db_conn):
        raw, fake, alloc_ids, dup_id = db_conn
        _run_migration(fake)
        # MIN(id) for crypto_quant_mean_reversion should be the original row,
        # not the dup.
        canonical_id = alloc_ids["crypto_quant_mean_reversion"]
        assert canonical_id < dup_id
        # Canonical row carries the spec value; dup carries pre-existing 99999.
        canonical_starting = raw.execute(
            "SELECT starting_capital_cents FROM bot_allocations WHERE id = ?", (canonical_id,),
        ).fetchone()[0]
        dup_starting = raw.execute(
            "SELECT starting_capital_cents FROM bot_allocations WHERE id = ?", (dup_id,),
        ).fetchone()[0]
        assert canonical_starting == ALLOCATIONS_CENTS["crypto_quant_mean_reversion"]
        assert dup_starting == 99999  # unchanged


class TestM025Guards:
    def test_missing_bot_hard_errors(self):
        """If a spec bot has no enabled allocation row for user 1, raise."""
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        raw.executescript(_DDL)
        raw.commit()
        # Seed only 12 of the 13 — omit cash_floor
        cur = raw.cursor()
        for name in BOT_NAMES:
            if name == "cash_floor":
                continue
            cur.execute("INSERT INTO bot_profiles (name, user_id) VALUES (?, ?)", (name, 1))
            pid = cur.lastrowid
            cur.execute(
                """INSERT INTO bot_allocations
                   (profile_id, user_id, enabled, starting_capital_cents,
                    inception_capital_cents, current_capital_cents, updated_at)
                   VALUES (?, 1, 1, 0, 0, 0, '2024-01-01T00:00:00')""",
                (pid,),
            )
        raw.commit()
        fake = _FakeConn(raw)
        with pytest.raises(RuntimeError, match="missing enabled allocation"):
            _run_migration(fake)
        raw.close()
