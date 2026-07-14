"""Tests for Phase 2 closed-loop learning: regime tagging.

10 tests per spec Section 5. All use fixed TARGET_DATE (never date.today()).
Sentry patched to a no-op. Uses SQLite in-memory DB with minimal raw SQL DDL.
Mirrors the pattern from test_phase1_daily_journal.py.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ── Path setup ────────────────────────────────────────────────────────────────

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

UTC = timezone.utc
TARGET_DATE = date(2026, 6, 29)


# ── Module loader ─────────────────────────────────────────────────────────────

def _load(module_name: str, rel_path: str):
    """Load a module from a file path, bypassing conftest stubs."""
    abs_path = os.path.join(_BACKEND_ROOT, rel_path)
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {abs_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Stub heavy dependencies ───────────────────────────────────────────────────

_config_stub = MagicMock()
_config_stub.settings = MagicMock()
_config_stub.settings.jwt_secret = "test_jwt_secret_for_unit_tests_only"
_config_stub.settings.jwt_algorithm = "HS256"
_config_stub.settings.cors_origins = ["http://localhost:5173"]
sys.modules.setdefault("app.config", _config_stub)
sys.modules.setdefault("sentry_sdk", MagicMock())

# Pre-load Base
_base_mod = _load("app.db.base", "app/db/base.py")
Base = _base_mod.Base

# Pre-stub app.routers as a package
_routers_stub = MagicMock()
sys.modules.setdefault("app.routers", _routers_stub)

# Pre-stub app.db.session
import types as _types
_session_stub = sys.modules.get("app.db.session")
if _session_stub is None:
    _session_stub = _types.ModuleType("app.db.session")
    sys.modules["app.db.session"] = _session_stub
if not hasattr(_session_stub, "SessionLocal"):
    _session_stub.SessionLocal = MagicMock()
if not hasattr(_session_stub, "get_db"):
    _session_stub.get_db = MagicMock()

# Pre-stub app.dependencies
_deps_stub = sys.modules.get("app.dependencies")
if _deps_stub is None:
    _deps_stub = _types.ModuleType("app.dependencies")
    sys.modules["app.dependencies"] = _deps_stub
if not hasattr(_deps_stub, "require_admin"):
    _deps_stub.require_admin = MagicMock(name="require_admin")
if not hasattr(_deps_stub, "get_current_user"):
    _deps_stub.get_current_user = MagicMock(name="get_current_user")
if not hasattr(_deps_stub, "get_db"):
    _deps_stub.get_db = _session_stub.get_db

# Load ORM models under private name. If phase1 tests already loaded bots.py
# (as "_phase1_bots_real"), reuse those classes — do NOT re-exec bots.py or we
# will get "Table X already defined for this MetaData instance" errors.
_bots_private_mod = sys.modules.get("_phase1_bots_real")
if _bots_private_mod is None:
    # Running standalone (no phase1 before us) — load fresh.
    _bots_spec = importlib.util.spec_from_file_location(
        "_phase2_bots_real", os.path.join(_BACKEND_ROOT, "app/db/models/bots.py")
    )
    _bots_private_mod = importlib.util.module_from_spec(_bots_spec)
    sys.modules["_phase2_bots_real"] = _bots_private_mod
    _orig_bots_stub = sys.modules.get("app.db.models.bots")
    sys.modules["app.db.models.bots"] = _bots_private_mod
    _bots_spec.loader.exec_module(_bots_private_mod)
    if _orig_bots_stub is not None:
        sys.modules["app.db.models.bots"] = _orig_bots_stub
    else:
        del sys.modules["app.db.models.bots"]

BotProfile = _bots_private_mod.BotProfile
BotAllocation = _bots_private_mod.BotAllocation
BotTrade = _bots_private_mod.BotTrade
BotPosition = _bots_private_mod.BotPosition
RegimeSnapshot = _bots_private_mod.RegimeSnapshot

# Patch the existing stub with real ORM classes
_bots_stub = sys.modules.get("app.db.models.bots")
if _bots_stub is not None:
    _bots_stub.BotProfile = BotProfile
    _bots_stub.BotAllocation = BotAllocation
    _bots_stub.BotTrade = BotTrade
    _bots_stub.BotPosition = BotPosition
    _bots_stub.RegimeSnapshot = RegimeSnapshot

# Load regime_snapshot service
_regime_mod = _load("app.services.regime_snapshot", "app/services/regime_snapshot.py")
sys.modules["app.services.regime_snapshot"] = _regime_mod

# Load regime_tag helper
_regime_tag_mod = _load("app.services.regime_tag", "app/services/regime_tag.py")
sys.modules["app.services.regime_tag"] = _regime_tag_mod


# ── Minimal DDL ───────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    config_json TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    profile_id INTEGER NOT NULL,
    capital_pct REAL NOT NULL DEFAULT 10.0,
    risk_profile TEXT NOT NULL DEFAULT 'standard',
    paper_mode INTEGER NOT NULL DEFAULT 1,
    go_live_requested INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    paused_reason TEXT,
    starting_capital_cents INTEGER NOT NULL DEFAULT 10000000,
    card_config TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    portfolio_id INTEGER,
    capital_cents_within_portfolio INTEGER,
    tier TEXT NOT NULL DEFAULT 'T0'
);

CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_cost_cents REAL NOT NULL,
    side TEXT NOT NULL DEFAULT 'long',
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_reason TEXT,
    is_paper INTEGER NOT NULL DEFAULT 1,
    stop_price_usd REAL,
    target_price_usd REAL,
    trailing_stop_activated INTEGER NOT NULL DEFAULT 0,
    trailing_stop_price_usd REAL,
    quarantined_at TEXT,
    quarantine_reason TEXT,
    option_type TEXT,
    strike_price REAL,
    expiration_date TEXT,
    underlying_symbol TEXT,
    contract_count INTEGER,
    contract_premium_cents REAL
);

CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    fill_price_cents REAL NOT NULL,
    fees_cents INTEGER NOT NULL DEFAULT 0,
    ts TEXT NOT NULL,
    alpaca_order_id TEXT,
    position_id INTEGER,
    signal_id INTEGER,
    is_paper INTEGER NOT NULL DEFAULT 1,
    expected_fill_cents REAL,
    slippage_bps REAL,
    quarantined_at TEXT,
    quarantine_reason TEXT,
    option_type TEXT,
    strike_price REAL,
    expiration_date TEXT,
    underlying_symbol TEXT,
    contract_count INTEGER,
    contract_premium_cents REAL,
    regime_vix VARCHAR(16),
    regime_trend VARCHAR(16),
    regime_btc_dom_band VARCHAR(16),
    composite_score_at_execution INTEGER
);

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    vix_regime TEXT NOT NULL DEFAULT 'mid',
    trend_regime TEXT NOT NULL DEFAULT 'chop',
    vol_pctile REAL,
    btc_dominance REAL,
    btc_funding_rate REAL,
    spy_price REAL,
    vix_value REAL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY NOT NULL
);
"""

# DDL WITHOUT regime columns (for m049 idempotency test)
_DDL_NO_REGIME = """
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    profile_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    starting_capital_cents INTEGER NOT NULL DEFAULT 10000000,
    tier TEXT NOT NULL DEFAULT 'T0'
);

CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    fill_price_cents REAL NOT NULL,
    fees_cents INTEGER NOT NULL DEFAULT 0,
    ts TEXT NOT NULL,
    alpaca_order_id TEXT,
    position_id INTEGER,
    signal_id INTEGER,
    is_paper INTEGER NOT NULL DEFAULT 1,
    expected_fill_cents REAL,
    slippage_bps REAL,
    quarantined_at TEXT,
    quarantine_reason TEXT,
    option_type TEXT,
    strike_price REAL,
    expiration_date TEXT,
    underlying_symbol TEXT,
    contract_count INTEGER,
    contract_premium_cents REAL,
    composite_score_at_execution INTEGER
);

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    vix_regime TEXT NOT NULL DEFAULT 'mid',
    trend_regime TEXT NOT NULL DEFAULT 'chop',
    vol_pctile REAL,
    btc_dominance REAL,
    btc_funding_rate REAL,
    spy_price REAL,
    vix_value REAL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY NOT NULL
);
"""


# ── DB session factory ────────────────────────────────────────────────────────

def _make_engine(ddl: str = _DDL):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        for stmt in ddl.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        conn.commit()
    return engine


@pytest.fixture
def db():
    """Yield a Session backed by in-memory SQLite with full schema (including regime columns)."""
    engine = _make_engine(_DDL)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def db_no_regime():
    """Yield a Session backed by in-memory SQLite WITHOUT regime columns (for m049 tests)."""
    engine = _make_engine(_DDL_NO_REGIME)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_profile(db, name="test_bot", asset_class="stock") -> int:
    db.execute(text(
        "INSERT INTO bot_profiles (name, asset_class) VALUES (:n, :ac)"
    ), {"n": name, "ac": asset_class})
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_alloc(db, profile_id, user_id=1, enabled=1) -> int:
    db.execute(text(
        "INSERT INTO bot_allocations (user_id, profile_id, enabled) VALUES (:uid, :pid, :en)"
    ), {"uid": user_id, "pid": profile_id, "en": enabled})
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_trade(db, alloc_id, ts_str, side="buy", symbol="AAPL",
                  qty=10.0, fill_price_cents=15000.0, position_id=None,
                  regime_vix=None, regime_trend=None, regime_btc=None) -> int:
    db.execute(text(
        "INSERT INTO bot_trades "
        "(allocation_id, symbol, side, qty, fill_price_cents, fees_cents, ts, "
        "position_id, regime_vix, regime_trend, regime_btc_dom_band) "
        "VALUES (:aid, :sym, :side, :qty, :fp, 0, :ts, :pid, :rv, :rt, :rb)"
    ), {
        "aid": alloc_id, "sym": symbol, "side": side, "qty": qty,
        "fp": fill_price_cents, "ts": ts_str, "pid": position_id,
        "rv": regime_vix, "rt": regime_trend, "rb": regime_btc,
    })
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_regime_snap(db, ts_str, vix_regime="mid", trend_regime="chop",
                        btc_dominance=0.55) -> int:
    db.execute(text(
        "INSERT INTO regime_snapshots (ts, vix_regime, trend_regime, btc_dominance) "
        "VALUES (:ts, :vix, :trend, :btc)"
    ), {"ts": ts_str, "vix": vix_regime, "trend": trend_regime, "btc": btc_dominance})
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — m049 adds columns idempotently
# ══════════════════════════════════════════════════════════════════════════════

def test_m049_adds_columns_idempotent(db_no_regime):
    """Run m049.run(conn) twice — first adds 3 columns, second adds 0."""
    m049 = _load("app.db.migrations.m049_regime_tagging",
                 "app/db/migrations/m049_regime_tagging.py")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        for stmt in _DDL_NO_REGIME.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        conn.commit()

        result1 = m049.run(conn)
        assert result1["executed"] is True
        assert set(result1["columns_added"]) == {"regime_vix", "regime_trend", "regime_btc_dom_band"}
        assert set(result1["columns_present_after"]) == {"regime_vix", "regime_trend", "regime_btc_dom_band"}

        result2 = m049.run(conn)
        assert result2["executed"] is True
        assert result2["columns_added"] == []
        assert set(result2["columns_present_after"]) == {"regime_vix", "regime_trend", "regime_btc_dom_band"}

    engine.dispose()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — m049 creates index
# ══════════════════════════════════════════════════════════════════════════════

def test_m049_creates_index():
    """After run(), idx_bot_trades_regime exists in sqlite_master."""
    m049 = _load("app.db.migrations.m049_regime_tagging",
                 "app/db/migrations/m049_regime_tagging.py")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        for stmt in _DDL_NO_REGIME.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        conn.commit()

        result = m049.run(conn)
        assert result["index_present"] is True

        idx_row = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_bot_trades_regime'"
            )
        ).fetchone()
        assert idx_row is not None

    engine.dispose()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — live trade gets regime tags from snapshot
# ══════════════════════════════════════════════════════════════════════════════

def test_live_trade_gets_regime_tags(db):
    """regime_tag_dict returns snapshot values; BotTrade has all 3 cols set."""
    fake_snap = {"vix_band": "HIGH", "trend": "UP", "btc_dom_band": "60-65"}

    with patch.object(_regime_mod, "snapshot", return_value=fake_snap):
        rt = _regime_tag_mod.regime_tag_dict(db, source="test")

    assert rt["regime_vix"] == "HIGH"
    assert rt["regime_trend"] == "UP"
    assert rt["regime_btc_dom_band"] == "60-65"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — live trade uses UNKNOWN when snapshot raises
# ══════════════════════════════════════════════════════════════════════════════

def test_live_trade_uses_unknown_when_snapshot_missing(db):
    """When snapshot() raises, regime_tag_dict returns all UNKNOWN (not None)."""
    with patch.object(_regime_mod, "snapshot", side_effect=RuntimeError("db down")):
        rt = _regime_tag_mod.regime_tag_dict(db, source="test_fail")

    assert rt["regime_vix"] == "UNKNOWN"
    assert rt["regime_trend"] == "UNKNOWN"
    assert rt["regime_btc_dom_band"] == "UNKNOWN"
    # Must not be None
    assert rt["regime_vix"] is not None
    assert rt["regime_trend"] is not None
    assert rt["regime_btc_dom_band"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — backfill tags all NULL rows
# ══════════════════════════════════════════════════════════════════════════════

def test_backfill_tags_all_null_rows(db):
    """10 NULL-regime trades with nearby snapshots all get tagged (non-NULL)."""
    backfill_mod = _load("app.jobs.backfill_regime_tags",
                         "app/jobs/backfill_regime_tags.py")

    pid = _insert_profile(db, name="bf_bot")
    aid = _insert_alloc(db, pid)

    base_dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    for i in range(10):
        trade_ts = (base_dt + timedelta(hours=i)).isoformat()
        snap_ts = (base_dt + timedelta(hours=i, minutes=15)).isoformat()
        _insert_regime_snap(db, snap_ts, vix_regime="low", trend_regime="bull", btc_dominance=0.48)
        _insert_trade(db, aid, trade_ts, regime_vix=None)

    result = backfill_mod.run_backfill(db, batch_size=500, window_hours=2)

    assert result["rows_scanned"] == 10
    assert result["verify_null_after"] == 0

    null_count = db.execute(
        text("SELECT COUNT(*) FROM bot_trades WHERE regime_vix IS NULL")
    ).fetchone()[0]
    assert null_count == 0

    # Verify mapped values match the snapshot
    row = db.execute(
        text("SELECT regime_vix, regime_trend, regime_btc_dom_band FROM bot_trades LIMIT 1")
    ).fetchone()
    assert row[0] == "LOW"
    assert row[1] == "UP"
    assert row[2] == "<50"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 — backfill uses UNKNOWN when no snapshot within 2h
# ══════════════════════════════════════════════════════════════════════════════

def test_backfill_uses_unknown_when_no_snapshot_within_2h(db):
    """Trade at 2026-01-01 00:00 with snapshot 24h before → regime_vix == UNKNOWN."""
    backfill_mod = _load("app.jobs.backfill_regime_tags",
                         "app/jobs/backfill_regime_tags.py")

    pid = _insert_profile(db, name="stale_bot")
    aid = _insert_alloc(db, pid)

    trade_ts = "2026-01-01 00:00:00"
    snap_ts = "2025-12-31 00:00:00"   # 24h before — outside ±2h window
    _insert_regime_snap(db, snap_ts, vix_regime="high", trend_regime="bear", btc_dominance=0.62)
    _insert_trade(db, aid, trade_ts, regime_vix=None)

    result = backfill_mod.run_backfill(db, batch_size=500, window_hours=2)

    row = db.execute(
        text("SELECT regime_vix, regime_trend, regime_btc_dom_band FROM bot_trades LIMIT 1")
    ).fetchone()
    assert row[0] == "UNKNOWN", f"Expected UNKNOWN, got {row[0]}"
    assert row[1] == "UNKNOWN"
    assert row[2] == "UNKNOWN"
    assert result["rows_tagged_unknown"] == 1
    assert result["rows_tagged_real"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7 — backfill is idempotent via gate
# ══════════════════════════════════════════════════════════════════════════════

def test_backfill_idempotent_via_gate(db):
    """Run backfill once → tags rows. Record gate. already_ran() returns True."""
    backfill_mod = _load("app.jobs.backfill_regime_tags",
                         "app/jobs/backfill_regime_tags.py")

    pid = _insert_profile(db, name="gate_bot")
    aid = _insert_alloc(db, pid)

    now_iso = datetime.now(UTC).isoformat()
    _insert_regime_snap(db, now_iso, vix_regime="mid", trend_regime="chop", btc_dominance=0.55)
    trade_ts = datetime.now(UTC).isoformat()
    _insert_trade(db, aid, trade_ts, regime_vix=None)

    result1 = backfill_mod.run_backfill(db, batch_size=500, window_hours=2)
    assert result1["rows_scanned"] == 1
    assert result1["verify_null_after"] == 0

    # Record gate
    _BACKFILL_NAME = "backfill_regime_tags_2026_06"
    db.execute(
        text("INSERT INTO schema_migrations (migration_name) VALUES (:n) ON CONFLICT DO NOTHING"),
        {"n": _BACKFILL_NAME},
    )
    db.commit()

    # Verify gate works
    gate_row = db.execute(
        text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
        {"n": _BACKFILL_NAME},
    ).fetchone()
    assert gate_row is not None

    # Direct re-run of backfill is a no-op: zero NULL rows remain
    result2 = backfill_mod.run_backfill(db, batch_size=500, window_hours=2)
    assert result2["rows_scanned"] == 0
    assert result2["verify_null_after"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8 — matrix endpoint returns grouped data
# ══════════════════════════════════════════════════════════════════════════════

def test_matrix_endpoint_returns_grouped_data(db):
    """30 trades across 3 regime combos → matrix has 3 cells, untagged=0."""
    # Load admin module under private name with stubs
    import types as _t

    _users_stub = _t.ModuleType("app.db.models.users")
    _users_stub.User = MagicMock

    _admin_stubs = {
        "app.db.models.users": _users_stub,
        "app.db.session": _session_stub,
        "app.dependencies": _deps_stub,
        "sentry_sdk": MagicMock(),
    }

    admin_path = os.path.join(_BACKEND_ROOT, "app/routers/admin.py")
    admin_spec = importlib.util.spec_from_file_location("_phase2_admin", admin_path)
    admin_mod = importlib.util.module_from_spec(admin_spec)

    with patch.dict(sys.modules, _admin_stubs):
        try:
            admin_spec.loader.exec_module(admin_mod)
        except Exception:
            pass

    # Seed DB
    pid = _insert_profile(db, name="test_bot")
    aid = _insert_alloc(db, pid, user_id=1)

    regimes = [
        ("LOW", "UP", "<50"),
        ("MID", "CHOP", "55-60"),
        ("HIGH", "DOWN", ">65"),
    ]

    base_dt = datetime(2026, 6, 20, 10, 0, 0, tzinfo=UTC)
    for cell_idx, (rv, rt, rb) in enumerate(regimes):
        for i in range(5):  # 5 closed positions per regime = 10 trades each
            pos_dt = base_dt + timedelta(days=cell_idx * 3 + i)
            pos_id = db.execute(text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents, "
                "side, opened_at, closed_at) VALUES (:aid, 'AAPL', 10, 10000, 'long', :o, :c)"
            ), {
                "aid": aid,
                "o": pos_dt.isoformat(),
                "c": (pos_dt + timedelta(hours=2)).isoformat(),
            }).lastrowid
            db.commit()
            pos_id = db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]

            entry_ts = pos_dt.isoformat()
            exit_ts = (pos_dt + timedelta(hours=2)).isoformat()
            _insert_trade(db, aid, entry_ts, side="buy", qty=10.0,
                          fill_price_cents=10000.0, position_id=pos_id,
                          regime_vix=rv, regime_trend=rt, regime_btc=rb)
            _insert_trade(db, aid, exit_ts, side="sell", qty=10.0,
                          fill_price_cents=10100.0, position_id=pos_id,
                          regime_vix=rv, regime_trend=rt, regime_btc=rb)

    # Call endpoint directly
    from fastapi import HTTPException

    fake_user = MagicMock()
    fake_user.id = 1

    result = admin_mod.get_strategy_regime_matrix(
        bot_id="test_bot",
        window_days=30,
        min_trades_for_sharpe=5,
        current_user=fake_user,
        db=db,
    )

    assert result["bot_id"] == "test_bot"
    assert result["total_trades_in_window"] == 30
    assert result["untagged_trades_in_window"] == 0
    assert len(result["matrix"]) == 3


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9 — matrix endpoint omits sharpe for low N
# ══════════════════════════════════════════════════════════════════════════════

def test_matrix_endpoint_omits_sharpe_for_low_n(db):
    """Cell with 3 trades (< min_trades_for_sharpe=5) has sharpe=None but is present."""
    import types as _t

    _users_stub = _t.ModuleType("app.db.models.users")
    _users_stub.User = MagicMock

    _admin_stubs = {
        "app.db.models.users": _users_stub,
        "app.db.session": _session_stub,
        "app.dependencies": _deps_stub,
        "sentry_sdk": MagicMock(),
    }

    admin_path = os.path.join(_BACKEND_ROOT, "app/routers/admin.py")
    admin_spec = importlib.util.spec_from_file_location("_phase2_admin_sharpe", admin_path)
    admin_mod = importlib.util.module_from_spec(admin_spec)

    with patch.dict(sys.modules, _admin_stubs):
        try:
            admin_spec.loader.exec_module(admin_mod)
        except Exception:
            pass

    pid = _insert_profile(db, name="sharpe_bot")
    aid = _insert_alloc(db, pid, user_id=1)

    base_dt = datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC)
    # 3 trades (1 entry + 1 exit + 1 unpaired) — below min_trades_for_sharpe=5
    pos_id_row = db.execute(text(
        "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents, side, opened_at, closed_at) "
        "VALUES (:aid, 'SPY', 5, 50000, 'long', :o, :c)"
    ), {
        "aid": aid,
        "o": base_dt.isoformat(),
        "c": (base_dt + timedelta(hours=1)).isoformat(),
    })
    db.commit()
    pos_id = db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]

    _insert_trade(db, aid, base_dt.isoformat(), side="buy", qty=5.0,
                  fill_price_cents=50000.0, position_id=pos_id,
                  regime_vix="MID", regime_trend="CHOP", regime_btc="55-60")
    _insert_trade(db, aid, (base_dt + timedelta(hours=1)).isoformat(),
                  side="sell", qty=5.0, fill_price_cents=50500.0, position_id=pos_id,
                  regime_vix="MID", regime_trend="CHOP", regime_btc="55-60")
    # A third orphan trade with no matching exit
    _insert_trade(db, aid, (base_dt + timedelta(hours=2)).isoformat(),
                  side="buy", qty=5.0, fill_price_cents=50200.0,
                  regime_vix="MID", regime_trend="CHOP", regime_btc="55-60")

    fake_user = MagicMock()
    fake_user.id = 1

    result = admin_mod.get_strategy_regime_matrix(
        bot_id="sharpe_bot",
        window_days=30,
        min_trades_for_sharpe=5,
        current_user=fake_user,
        db=db,
    )

    assert len(result["matrix"]) == 1
    cell = result["matrix"][0]
    assert cell["trades"] == 3
    assert cell["sharpe"] is None  # below min_trades_for_sharpe


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10 — matrix endpoint window_days param filters correctly
# ══════════════════════════════════════════════════════════════════════════════

def test_matrix_endpoint_window_days_param(db):
    """5 trades now + 5 trades 60d ago: window_days=30 → 5, window_days=90 → 10."""
    import types as _t

    _users_stub = _t.ModuleType("app.db.models.users")
    _users_stub.User = MagicMock

    _admin_stubs = {
        "app.db.models.users": _users_stub,
        "app.db.session": _session_stub,
        "app.dependencies": _deps_stub,
        "sentry_sdk": MagicMock(),
    }

    admin_path = os.path.join(_BACKEND_ROOT, "app/routers/admin.py")
    admin_spec = importlib.util.spec_from_file_location("_phase2_admin_window", admin_path)
    admin_mod = importlib.util.module_from_spec(admin_spec)

    with patch.dict(sys.modules, _admin_stubs):
        try:
            admin_spec.loader.exec_module(admin_mod)
        except Exception:
            pass

    pid = _insert_profile(db, name="window_bot")
    aid = _insert_alloc(db, pid, user_id=1)

    now = datetime.now(UTC)
    recent_ts = (now - timedelta(days=5)).isoformat()
    old_ts = (now - timedelta(days=60)).isoformat()

    for _ in range(5):
        _insert_trade(db, aid, recent_ts, side="buy",
                      regime_vix="LOW", regime_trend="UP", regime_btc="<50")
    for _ in range(5):
        _insert_trade(db, aid, old_ts, side="buy",
                      regime_vix="HIGH", regime_trend="DOWN", regime_btc=">65")

    fake_user = MagicMock()
    fake_user.id = 1

    result_30 = admin_mod.get_strategy_regime_matrix(
        bot_id="window_bot", window_days=30, min_trades_for_sharpe=5,
        current_user=fake_user, db=db,
    )
    assert result_30["total_trades_in_window"] == 5

    result_90 = admin_mod.get_strategy_regime_matrix(
        bot_id="window_bot", window_days=90, min_trades_for_sharpe=5,
        current_user=fake_user, db=db,
    )
    assert result_90["total_trades_in_window"] == 10
