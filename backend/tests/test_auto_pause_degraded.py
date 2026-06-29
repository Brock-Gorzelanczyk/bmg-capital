"""Tests for SHIP 6 auto_pause_degraded.py job.

Uses SQLite in-memory DB. Tests mock the ORM layer so the job's
query() calls work without needing the full app stack.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

# Add backend to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── DB schema ──────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    asset_class TEXT
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER DEFAULT 1,
    paused_reason TEXT,
    starting_capital_cents INTEGER DEFAULT 0,
    inception_capital_cents INTEGER DEFAULT 0,
    current_capital_cents INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER,
    symbol TEXT,
    exit_reason TEXT,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT,
    side TEXT,
    qty REAL,
    fill_price_cents REAL,
    ts TEXT NOT NULL,
    position_id INTEGER
);
CREATE TABLE IF NOT EXISTS bot_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT,
    user_id INTEGER,
    date TEXT,
    realized_cents INTEGER DEFAULT 0,
    unrealized_cents INTEGER DEFAULT 0
);
"""


def _make_engine():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        for stmt in _SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(sa.text(stmt))
        conn.commit()
    return engine


def _load_apd():
    """Load auto_pause_degraded with discord stubbed."""
    _path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "app", "jobs", "auto_pause_degraded.py"
    ))
    mod_name = f"_apd_{os.getpid()}"
    sys.modules.pop(mod_name, None)
    fake_discord = types.ModuleType("app.services.discord")
    fake_discord.send_ops_alert = MagicMock(return_value=True)
    sys.modules["app.services.discord"] = fake_discord
    spec = importlib.util.spec_from_file_location(mod_name, _path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_bot(conn, name, user_ids=None, enabled=True, paused_reason=None):
    """Seed profile + allocations. Returns (profile_id, [alloc_ids])."""
    if user_ids is None:
        user_ids = [1]
    conn.execute(sa.text(
        "INSERT OR IGNORE INTO bot_profiles (name, asset_class) VALUES (:n, 'crypto')"
    ), {"n": name})
    conn.commit()
    pid = conn.execute(
        sa.text("SELECT id FROM bot_profiles WHERE name=:n"), {"n": name}
    ).fetchone()[0]
    alloc_ids = []
    for uid in user_ids:
        conn.execute(sa.text("""
            INSERT INTO bot_allocations
                (profile_id, user_id, enabled, paused_reason,
                 starting_capital_cents, inception_capital_cents, current_capital_cents)
            VALUES (:pid, :uid, :en, :pr, 7000000, 7000000, 7000000)
        """), {"pid": pid, "uid": uid, "en": 1 if enabled else 0, "pr": paused_reason})
    conn.commit()
    rows = conn.execute(
        sa.text("SELECT id FROM bot_allocations WHERE profile_id=:pid ORDER BY id"), {"pid": pid}
    ).fetchall()
    alloc_ids = [r[0] for r in rows]
    return pid, alloc_ids


def _seed_trades(conn, alloc_id, total, stops, days_ago=1):
    """Seed bot_positions (with exit_reason) + bot_trades (close-side) linked by position_id."""
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(days=days_ago)).isoformat()
    for i in range(total):
        er = "stop_loss" if i < stops else "take_profit"
        conn.execute(sa.text("""
            INSERT INTO bot_positions (allocation_id, symbol, exit_reason, closed_at)
            VALUES (:aid, 'ETH/USD', :er, :ca)
        """), {"aid": alloc_id, "er": er, "ca": ts})
    conn.commit()
    pos_ids = [
        r[0] for r in conn.execute(
            sa.text("SELECT id FROM bot_positions WHERE allocation_id=:aid"), {"aid": alloc_id}
        ).fetchall()
    ]
    for pid in pos_ids:
        conn.execute(sa.text("""
            INSERT INTO bot_trades (allocation_id, symbol, side, qty, fill_price_cents, ts, position_id)
            VALUES (:aid, 'ETH/USD', 'sell', 1.0, 100000, :ts, :pid)
        """), {"aid": alloc_id, "ts": ts, "pid": pid})
    conn.commit()


# ── Thin ORM mock that proxies to real SQLite ─────────────────────────────

class _MockSession:
    """Proxies execute() to real SQLite; provides query() returning _MockQuery."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, stmt, params=None):
        return self._conn.execute(stmt, params or {})

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        pass  # caller manages conn

    def query(self, model_cls):
        return _MockQuery(self._conn, model_cls)


class _MockAlloc:
    """Minimal BotAllocation-alike returned from queries.

    Attribute writes (e.g. ``alloc.enabled = False``) are proxied as
    immediate UPDATE statements against the bound SQLite connection so
    the production code's ORM-style mutation pattern actually persists
    through the test's raw connection read-back.
    """
    def __init__(self, row_dict, conn=None):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_id", row_dict.get("id"))
        self.__dict__.update(row_dict)

    def __setattr__(self, name, value):
        # Set in-memory first so subsequent reads off the object stay consistent.
        object.__setattr__(self, name, value)
        # Then push to SQLite if this is a real DB-backed column.
        if name.startswith("_") or self._conn is None or self._id is None:
            return
        try:
            import sqlalchemy as _sa
            self._conn.execute(
                _sa.text(f"UPDATE bot_allocations SET {name} = :v WHERE id = :id"),
                {"v": value, "id": self._id},
            )
        except Exception:
            pass  # best effort; rollback handled by Session


class _MockProfileObj:
    """Minimal BotProfile-alike (no DB writes needed)."""
    def __init__(self, row_dict):
        self.__dict__.update(row_dict)


class _MockProfile:
    """Minimal BotProfile-alike."""
    def __init__(self, row_dict):
        self.__dict__.update(row_dict)


class _MockQuery:
    """Query builder that converts ORM filter expressions to SQL WHERE clauses."""

    def __init__(self, conn, model_cls):
        self._conn = conn
        self._model_name = getattr(model_cls, "_mock_name", str(model_cls))
        self._conditions: list[tuple[str, object]] = []

    def filter(self, *args):
        for a in args:
            # Each arg is a BinaryExpression mock with .left.key and .right.value or .right
            try:
                col = a.left.key
                # .right may be a BindParameter or scalar
                right = getattr(a.right, "value", None)
                if right is None:
                    right = getattr(a.right, "effective_value", None)
                op_name = getattr(a.operator, "__name__", "") or str(a.operator)
                self._conditions.append((col, op_name, right))
            except AttributeError:
                pass  # skip unparseable
        return self

    def _where_clause(self, table: str) -> tuple[str, dict]:
        parts = []
        vals: dict = {}
        for i, (col, op, val) in enumerate(self._conditions):
            param = f"_p{i}"
            if op in ("eq", "__eq__", "is_") and val is True:
                parts.append(f"{table}.{col} = 1")
            elif op in ("eq", "__eq__", "is_") and val is False:
                parts.append(f"{table}.{col} = 0")
            elif val is None:
                parts.append(f"{table}.{col} IS NULL")
            else:
                parts.append(f"{table}.{col} = :{param}")
                vals[param] = val
        return (" AND ".join(parts) if parts else "1=1"), vals

    def count(self) -> int:
        table = self._table()
        where, vals = self._where_clause(table)
        r = self._conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {where}"), vals
        ).fetchone()
        return int(r[0]) if r else 0

    def first(self):
        table = self._table()
        where, vals = self._where_clause(table)
        cols = [c[1] for c in self._conn.execute(
            sa.text(f"PRAGMA table_info({table})")
        ).fetchall()]
        r = self._conn.execute(
            sa.text(f"SELECT * FROM {table} WHERE {where} LIMIT 1"), vals
        ).fetchone()
        if r is None:
            return None
        row_dict = dict(zip(cols, r))
        if table == "bot_profiles":
            return _MockProfile(row_dict)
        return _MockAlloc(row_dict, conn=self._conn)

    def all(self) -> list:
        table = self._table()
        where, vals = self._where_clause(table)
        cols = [c[1] for c in self._conn.execute(
            sa.text(f"PRAGMA table_info({table})")
        ).fetchall()]
        rows = self._conn.execute(
            sa.text(f"SELECT * FROM {table} WHERE {where}"), vals
        ).fetchall()
        if table == "bot_profiles":
            return [_MockProfile(dict(zip(cols, r))) for r in rows]
        return [_MockAlloc(dict(zip(cols, r)), conn=self._conn) for r in rows]

    def _table(self):
        if "BotProfile" in self._model_name or "bot_profiles" in self._model_name:
            return "bot_profiles"
        if "BotAllocation" in self._model_name or "bot_allocations" in self._model_name:
            return "bot_allocations"
        raise ValueError(f"Unknown model: {self._model_name}")


def _make_model_stubs():
    """Return (BotProfile_stub, BotAllocation_stub) that work with _MockQuery."""

    class _BP:
        _mock_name = "BotProfile_bot_profiles"
        name = MagicMock()
        name.key = "name"
        id = MagicMock()
        id.key = "id"

        def __eq__(self, other):
            # e.g. BotProfile.name == bot_id  -> BinaryExpression mock
            return _BinExpr("name", "eq", other)

    class _BA:
        _mock_name = "BotAllocation_bot_allocations"
        profile_id = MagicMock()
        profile_id.key = "profile_id"
        enabled = MagicMock()
        enabled.key = "enabled"
        id = MagicMock()
        id.key = "id"

    # Attribute access for comparison
    _BP.name = _AttrProxy("name")
    _BA.profile_id = _AttrProxy("profile_id")
    _BA.enabled = _AttrProxy("enabled")

    return _BP, _BA


class _BinExpr:
    """Minimal binary expression for filter()."""
    def __init__(self, col, op, val):
        self.left = type("L", (), {"key": col})()
        self.operator = type("Op", (), {"__name__": op})()
        self.right = type("R", (), {"value": val, "effective_value": val})()


class _AttrProxy:
    """Descriptor that produces _BinExpr on __eq__."""
    def __init__(self, col):
        self.key = col

    def __eq__(self, other):
        return _BinExpr(self.key, "eq", other)

    def is_(self, val):
        return _BinExpr(self.key, "is_", val)

    # Make hashable for use as dict key
    def __hash__(self):
        return hash(self.key)


def _inject_model_stubs(apd_mod):
    """Inject model stubs so apd_mod.auto_pause_if_degraded can import them."""
    _BP, _BA = _make_model_stubs()
    bp_stub = types.ModuleType("app.db.models.bots")
    bp_stub.BotProfile = _BP
    bp_stub.BotAllocation = _BA
    sys.modules["app.db.models.bots"] = bp_stub
    return _BP, _BA


# ── Tests ──────────────────────────────────────────────────────────────────

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _restore_sys_modules():
    """Snapshot sys.modules before each test and restore after.

    Prevents the SHIP 14 / SHIP 3 sys.modules pollution regression:
    tests in this file overwrite app.services.discord, app.services.asset_class_registry,
    app.db.models.bots, etc. Without restoration, subsequent tests
    (test_factor_attribution, test_position_monitor_guards, test_risk_overlay_apply)
    fail because their imports resolve to the stub modules.
    """
    import sys
    snapshot = dict(sys.modules)
    yield
    # Remove keys added during the test, restore keys overwritten.
    for k in list(sys.modules.keys()):
        if k not in snapshot:
            del sys.modules[k]
    for k, v in snapshot.items():
        sys.modules[k] = v


class TestAutoPauseDegraded:

    def test_auto_pause_triggers_at_70pct_stop_rate(self):
        """71 stops / 100 closes → action=paused, paused_reason=degraded_auto_pause:71.0%_over_7d."""
        engine = _make_engine()
        apd = _load_apd()

        with engine.connect() as conn:
            pid, [aid] = _seed_bot(conn, "crypto_quant_scalper")
            _seed_trades(conn, aid, total=100, stops=71)
            _inject_model_stubs(apd)
            db = _MockSession(conn)
            result = apd.auto_pause_if_degraded(db, "crypto_quant_scalper")

        assert result["action"] == "paused", f"Expected 'paused', got: {result}"
        assert "degraded_auto_pause" in result["paused_reason"]
        assert result["stop_pct"] > 70.0

        # Verify DB state
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT enabled, paused_reason FROM bot_allocations WHERE profile_id=:pid"),
                {"pid": pid},
            ).fetchone()
        assert row[0] == 0
        assert "degraded_auto_pause" in str(row[1])

    def test_auto_pause_does_not_trigger_at_exactly_70_pct(self):
        """70 stops / 100 closes → action=below_threshold."""
        engine = _make_engine()
        apd = _load_apd()

        with engine.connect() as conn:
            pid, [aid] = _seed_bot(conn, "crypto_quant_scalper")
            _seed_trades(conn, aid, total=100, stops=70)
            _inject_model_stubs(apd)
            db = _MockSession(conn)
            result = apd.auto_pause_if_degraded(db, "crypto_quant_scalper")

        assert result["action"] == "below_threshold", f"Got: {result}"

    def test_auto_pause_insufficient_data(self):
        """10 closes (below MIN_CLOSES_FOR_EVAL=20) → action=insufficient_data."""
        engine = _make_engine()
        apd = _load_apd()

        with engine.connect() as conn:
            pid, [aid] = _seed_bot(conn, "crypto_quant_scalper")
            _seed_trades(conn, aid, total=10, stops=9)
            _inject_model_stubs(apd)
            db = _MockSession(conn)
            result = apd.auto_pause_if_degraded(db, "crypto_quant_scalper")

        assert result["action"] == "insufficient_data", f"Got: {result}"

    def test_auto_pause_skips_already_paused_bot(self):
        """Bot already enabled=False → action=already_paused, no Discord alert."""
        engine = _make_engine()
        apd = _load_apd()
        discord_calls = []

        fake_discord = types.ModuleType("app.services.discord")
        fake_discord.send_ops_alert = lambda **kw: discord_calls.append(kw)
        sys.modules["app.services.discord"] = fake_discord

        with engine.connect() as conn:
            pid, [aid] = _seed_bot(conn, "crypto_quant_scalper", enabled=False)
            _seed_trades(conn, aid, total=100, stops=80)
            _inject_model_stubs(apd)
            db = _MockSession(conn)
            result = apd.auto_pause_if_degraded(db, "crypto_quant_scalper")

        assert result["action"] == "already_paused", f"Got: {result}"
        assert len(discord_calls) == 0

    def test_auto_pause_recovers_on_manual_enable(self):
        """Simulate enable_bot: paused_reason=None + enabled=True after auto-pause."""
        engine = _make_engine()

        with engine.connect() as conn:
            pid, [aid] = _seed_bot(conn, "crypto_quant_scalper")
            # Simulate auto-pause state
            conn.execute(sa.text("""
                UPDATE bot_allocations SET enabled=0,
                    paused_reason='degraded_auto_pause:84.2%_over_7d'
                WHERE id=:aid
            """), {"aid": aid})
            conn.commit()

            row_before = conn.execute(
                sa.text("SELECT enabled, paused_reason FROM bot_allocations WHERE id=:aid"),
                {"aid": aid},
            ).fetchone()
            assert row_before[0] == 0
            assert "degraded_auto_pause" in str(row_before[1])

            # Simulate enable_bot (sets enabled=True, paused_reason=NULL)
            conn.execute(sa.text("""
                UPDATE bot_allocations SET enabled=1, paused_reason=NULL
                WHERE profile_id=(SELECT id FROM bot_profiles WHERE name='crypto_quant_scalper')
            """))
            conn.commit()

            row_after = conn.execute(
                sa.text("SELECT enabled, paused_reason FROM bot_allocations WHERE id=:aid"),
                {"aid": aid},
            ).fetchone()
            assert row_after[0] == 1
            assert row_after[1] is None

    def test_auto_pause_pauses_all_allocations_for_bot(self):
        """2 allocations (user 1 + 3) for same bot → both get paused."""
        engine = _make_engine()
        apd = _load_apd()

        with engine.connect() as conn:
            pid, alloc_ids = _seed_bot(conn, "crypto_quant_scalper", user_ids=[1, 3])
            for aid in alloc_ids:
                _seed_trades(conn, aid, total=100, stops=80)
            _inject_model_stubs(apd)
            db = _MockSession(conn)
            result = apd.auto_pause_if_degraded(db, "crypto_quant_scalper")

        assert result["action"] == "paused", f"Got: {result}"
        assert len(result["paused_allocation_ids"]) == 2

        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT enabled, paused_reason FROM bot_allocations WHERE profile_id=:pid"),
                {"pid": pid},
            ).fetchall()
        assert all(r[0] == 0 for r in rows)
        assert all("degraded_auto_pause" in str(r[1]) for r in rows)

    def test_auto_pause_reads_from_bot_trades_but_never_writes(self):
        """bot_trades and bot_daily_pnl row counts unchanged after job run."""
        engine = _make_engine()
        apd = _load_apd()

        with engine.connect() as conn:
            pid, [aid] = _seed_bot(conn, "crypto_quant_scalper")
            _seed_trades(conn, aid, total=30, stops=25)

            bt_before = conn.execute(sa.text("SELECT COUNT(*) FROM bot_trades")).fetchone()[0]
            bdp_before = conn.execute(sa.text("SELECT COUNT(*) FROM bot_daily_pnl")).fetchone()[0]

            _inject_model_stubs(apd)
            db = _MockSession(conn)
            apd.auto_pause_if_degraded(db, "crypto_quant_scalper")

            bt_after = conn.execute(sa.text("SELECT COUNT(*) FROM bot_trades")).fetchone()[0]
            bdp_after = conn.execute(sa.text("SELECT COUNT(*) FROM bot_daily_pnl")).fetchone()[0]

        assert bt_before == bt_after, f"bot_trades mutated: {bt_before} → {bt_after}"
        assert bdp_before == bdp_after, f"bot_daily_pnl mutated: {bdp_before} → {bdp_after}"

    def test_auto_pause_iterates_canonical_registry(self):
        """Mock ASSET_CLASS_REGISTRY with 2 bots → bots_checked == 2."""
        apd = _load_apd()

        fake_registry = {"foo": {}, "bar": {}}
        results = []

        def _fake_apd(db, bot_id):
            r = {"bot_id": bot_id, "action": "insufficient_data", "total_closes": 0,
                 "stops": 0, "stop_pct": 0.0, "paused_allocation_ids": [], "paused_reason": None,
                 "ts": datetime.now(timezone.utc).isoformat()}
            results.append(r)
            return r

        fake_acr = types.ModuleType("app.services.asset_class_registry")
        fake_acr.ASSET_CLASS_REGISTRY = fake_registry
        sys.modules["app.services.asset_class_registry"] = fake_acr

        fake_db_session_mod = types.ModuleType("app.db.session")
        fake_db_session_mod.SessionLocal = MagicMock(return_value=MagicMock())
        sys.modules["app.db.session"] = fake_db_session_mod

        with patch.object(apd, "auto_pause_if_degraded", side_effect=_fake_apd):
            result = apd.run_auto_pause_degraded_job()

        assert result["bots_checked"] == 2
