"""Tests for Phase 1 closed-loop learning: per-bot daily journal.

Tests 1-17 per spec Section 5. All use fixed target_date (never date.today()).
Sentry patched to a no-op. Uses SQLite in-memory DB with minimal raw SQL DDL
(avoids FK resolution issues from users table not being loaded — mirrors the
pattern used in test_track_record_reconstruction.py).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
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
    """Load a module from a file path, bypassing conftest stubs.

    Skips re-loading if already loaded with a real __file__.
    """
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


# ── Stub heavy dependencies before loading any modules ───────────────────────

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

# Pre-stub app.routers as a package so "from app.routers.X import Y" works via importlib
_routers_stub = MagicMock()
sys.modules.setdefault("app.routers", _routers_stub)

# Pre-stub app.db.session BEFORE loading dependencies (it imports session).
# IMPORTANT: use setdefault-style attribute setting to avoid overwriting
# get_db / SessionLocal that test_cio_observability.py (or any earlier test
# file) may have already set on this stub — overwriting them would sever
# admin.py's Depends(get_db) references and produce 422 in endpoint tests.
import types as _types
_session_stub = sys.modules.get("app.db.session")
if _session_stub is None:
    _session_stub = _types.ModuleType("app.db.session")
    sys.modules["app.db.session"] = _session_stub
if not hasattr(_session_stub, "SessionLocal"):
    _session_stub.SessionLocal = MagicMock()
if not hasattr(_session_stub, "get_db"):
    _session_stub.get_db = MagicMock()

# Ensure app.dependencies has at least stub require_admin / get_current_user
# so that "from app.dependencies import require_admin" inside strategy_journal.py
# succeeds at collection time. Use setdefault so we never overwrite a stub that
# test_cio_observability.py (or any earlier test file) already registered —
# replacing that stub would sever admin.py's Depends() references and cause
# 422 failures in test_cio_observability.py endpoint tests.
_deps_stub_for_router = _types.ModuleType("app.dependencies")
_deps_stub_for_router.require_admin = MagicMock(name="require_admin")
_deps_stub_for_router.get_current_user = MagicMock(name="get_current_user")
_deps_stub_for_router.get_db = _session_stub.get_db  # same stub get_db
sys.modules.setdefault("app.dependencies", _deps_stub_for_router)

# Load the REAL app.dependencies under a private name so test 16 can call
# _deps_mod.require_admin(token=None, db=...) to verify the 401 behaviour.
# This does NOT touch sys.modules["app.dependencies"].
_deps_spec = importlib.util.spec_from_file_location(
    "_phase1_deps_real", os.path.join(_BACKEND_ROOT, "app/dependencies.py")
)
_deps_mod = importlib.util.module_from_spec(_deps_spec)
_deps_spec.loader.exec_module(_deps_mod)

# Load ORM models needed by daily_journal.py and our test assertions.
#
# Cross-test isolation constraints:
#   A. test_factor_attribution.py loads factor_attribution_service at COLLECTION
#      time with conftest MagicMock BotPosition. If we later change what
#      sys.modules["app.db.models.bots"].BotPosition points to, FakeSession
#      key lookups in that file break (service has old mock, test imports new).
#      Fix: also patch factor_attribution_service's module-level references.
#
#   B. test_canonical_reconciliation.py's db_session fixture imports
#      StrategyPortfolio. Normally, the conftest stub doesn't have this class
#      so the fixture catches ImportError and SKIPS. If we replace the stub
#      with the full real bots module, StrategyPortfolio becomes available,
#      the fixture succeeds the import, but then Base.metadata.create_all()
#      fails due to missing 'users' table FK → ERROR instead of SKIP.
#      Fix: do NOT put StrategyPortfolio into sys.modules["app.db.models.bots"].
#
# Strategy: load bots.py under a private internal name (not as the canonical
# "app.db.models.bots" sys.modules key), then PATCH the EXISTING stub with
# only the specific classes we need. The stub still lacks StrategyPortfolio,
# so canonical_reconciliation continues to skip. But because the existing stub
# has __file__ = None (conftest types.ModuleType), _load() would try to reload
# it — so we use importlib directly with a private name instead.
_bots_spec = importlib.util.spec_from_file_location(
    "_phase1_bots_real", os.path.join(_BACKEND_ROOT, "app/db/models/bots.py")
)
_bots_private_mod = importlib.util.module_from_spec(_bots_spec)
# Register under private name FIRST so cross-imports inside bots.py resolve.
sys.modules["_phase1_bots_real"] = _bots_private_mod
# Also temporarily register as the canonical name so "from app.db.base import Base"
# and other internal imports inside bots.py resolve correctly.
# We will RESTORE sys.modules["app.db.models.bots"] to the original stub afterwards.
_orig_bots_stub = sys.modules.get("app.db.models.bots")
sys.modules["app.db.models.bots"] = _bots_private_mod
_bots_spec.loader.exec_module(_bots_private_mod)
# Restore original stub so other tests aren't affected by the full module
# (notably: test_canonical_reconciliation.py which must NOT see StrategyPortfolio).
if _orig_bots_stub is not None:
    sys.modules["app.db.models.bots"] = _orig_bots_stub
else:
    del sys.modules["app.db.models.bots"]

BotProfile = _bots_private_mod.BotProfile
BotAllocation = _bots_private_mod.BotAllocation
BotTrade = _bots_private_mod.BotTrade
BotPosition = _bots_private_mod.BotPosition
BotSignal = _bots_private_mod.BotSignal
RegimeSnapshot = _bots_private_mod.RegimeSnapshot

# Patch the existing stub with real ORM classes. daily_journal.py imports via
# `from app.db.models.bots import BotAllocation` — with these real classes
# in the stub, SQLAlchemy ORM queries work against the in-memory SQLite DB.
# We do NOT add StrategyPortfolio, so canonical_reconciliation fixture still
# gets ImportError and skips (as it does without our test file present).
_bots_stub = sys.modules.get("app.db.models.bots")
if _bots_stub is not None:
    _bots_stub.BotProfile = BotProfile
    _bots_stub.BotAllocation = BotAllocation
    _bots_stub.BotTrade = BotTrade
    _bots_stub.BotPosition = BotPosition
    _bots_stub.BotSignal = BotSignal
    _bots_stub.RegimeSnapshot = RegimeSnapshot

# Patch factor_attribution_service if already loaded, so its BotPosition
# reference matches what test_factor_attribution.py imports at test execution.
_fa_service = sys.modules.get("app.services.factor_attribution_service")
if _fa_service is not None and hasattr(_fa_service, "BotPosition"):
    _fa_service.BotAllocation = BotAllocation
    _fa_service.BotProfile = BotProfile
    _fa_service.BotPosition = BotPosition

# Load bot_daily_journal model
_journal_model_mod = _load("app.db.models.bot_daily_journal", "app/db/models/bot_daily_journal.py")
BotDailyJournal = _journal_model_mod.BotDailyJournal
sys.modules["app.db.models.bot_daily_journal"] = _journal_model_mod

# Load services
_regime_mod = _load("app.services.regime_snapshot", "app/services/regime_snapshot.py")
_writer_mod = _load("app.services.journal_writer", "app/services/journal_writer.py")
_rolling_mod = _load("app.services.journal_rolling", "app/services/journal_rolling.py")

sys.modules["app.services.regime_snapshot"] = _regime_mod
sys.modules["app.services.journal_writer"] = _writer_mod
sys.modules["app.services.journal_rolling"] = _rolling_mod


# ── Minimal raw SQL DDL (avoids FK resolution issues) ────────────────────────

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

CREATE TABLE IF NOT EXISTS bot_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    size_hint REAL,
    reason TEXT,
    strategy TEXT,
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    discord_posted_at TEXT,
    discord_message_id TEXT,
    is_test INTEGER DEFAULT 0,
    executed_at TEXT
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
    regime_vix TEXT,
    regime_trend TEXT,
    regime_btc_dom_band TEXT,
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

CREATE TABLE IF NOT EXISTS bot_daily_journals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 1,
    journal_date TEXT NOT NULL,
    sleeve TEXT,
    asset_class TEXT,
    starting_capital_cents INTEGER NOT NULL DEFAULT 0,
    ending_pv_cents INTEGER NOT NULL DEFAULT 0,
    day_pnl_cents INTEGER NOT NULL DEFAULT 0,
    day_return_pct REAL NOT NULL DEFAULT 0.0,
    trades_count INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    win_rate REAL,
    avg_winner_cents INTEGER,
    avg_loser_cents INTEGER,
    profit_factor REAL,
    avg_hold_minutes REAL,
    max_concurrent_positions INTEGER NOT NULL DEFAULT 0,
    end_of_day_positions INTEGER NOT NULL DEFAULT 0,
    end_of_day_deployed_cents INTEGER NOT NULL DEFAULT 0,
    deployment_pct_avg REAL,
    regime_vix_band TEXT,
    regime_trend TEXT,
    regime_btc_dom_band TEXT,
    strategies_breakdown_json TEXT,
    errors_24h INTEGER NOT NULL DEFAULT 0,
    sentry_issues_json TEXT,
    body_md TEXT,
    frontmatter_yaml TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(allocation_id, journal_date)
);
"""


# ── DB session factory ────────────────────────────────────────────────────────

def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        conn.commit()
    return engine


@pytest.fixture
def db():
    """Yield a Session backed by an in-memory SQLite DB with the minimal schema."""
    engine = _make_engine()
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()

    # Bind the SQLAlchemy ORM models to this engine so queries work
    # We use the raw-SQL tables above rather than create_all() to avoid
    # FK resolution issues with the users/strategy_portfolios tables.
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _insert_profile(db, name="test_bot", asset_class="stock") -> int:
    db.execute(text(
        "INSERT INTO bot_profiles (name, asset_class) VALUES (:n, :ac)"
    ), {"n": name, "ac": asset_class})
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_alloc(db, profile_id, user_id=1, enabled=1, capital=100_000_00) -> int:
    db.execute(text(
        "INSERT INTO bot_allocations (user_id, profile_id, enabled, starting_capital_cents) "
        "VALUES (:uid, :pid, :en, :cap)"
    ), {"uid": user_id, "pid": profile_id, "en": enabled, "cap": capital})
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_trade(db, alloc_id, symbol="AAPL", side="buy", qty=10.0,
                  fill_price_cents=15000.0, fees_cents=0, position_id=None,
                  signal_id=None, target_date=TARGET_DATE) -> int:
    ts = f"{target_date.year}-{target_date.month:02d}-{target_date.day:02d} 12:00:00"
    db.execute(text(
        "INSERT INTO bot_trades (allocation_id, symbol, side, qty, fill_price_cents, "
        "fees_cents, ts, position_id, signal_id) "
        "VALUES (:aid, :sym, :side, :qty, :fp, :fees, :ts, :pid, :sid)"
    ), {
        "aid": alloc_id, "sym": symbol, "side": side, "qty": qty,
        "fp": fill_price_cents, "fees": fees_cents, "ts": ts,
        "pid": position_id, "sid": signal_id,
    })
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_position(db, alloc_id, symbol="AAPL", qty=10.0, avg_cost_cents=15000.0,
                     side="long", target_date=TARGET_DATE, closed=True) -> int:
    opened_at = f"{target_date.year}-{target_date.month:02d}-{target_date.day:02d} 10:00:00"
    closed_at = f"{target_date.year}-{target_date.month:02d}-{target_date.day:02d} 14:00:00" if closed else None
    db.execute(text(
        "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents, side, opened_at, closed_at) "
        "VALUES (:aid, :sym, :qty, :ac, :side, :oa, :ca)"
    ), {
        "aid": alloc_id, "sym": symbol, "qty": qty, "ac": avg_cost_cents,
        "side": side, "oa": opened_at, "ca": closed_at,
    })
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_journal(db, alloc_id, bot_id, pnl_cents, trades_count,
                    day_ret_pct=0.05, journal_date=None, winners=1, losers=0) -> int:
    d = journal_date or TARGET_DATE
    breakdown = json.dumps({})
    db.execute(text(
        "INSERT INTO bot_daily_journals "
        "(allocation_id, bot_id, user_id, journal_date, starting_capital_cents, "
        "ending_pv_cents, day_pnl_cents, day_return_pct, trades_count, winning_trades, "
        "losing_trades, errors_24h, strategies_breakdown_json) "
        "VALUES (:aid, :bid, 1, :jd, 100000000, :epv, :pnl, :ret, :tc, :w, :l, 0, :bd)"
    ), {
        "aid": alloc_id, "bid": bot_id, "jd": d.isoformat(),
        "epv": 100_000_00 + pnl_cents, "pnl": pnl_cents, "ret": day_ret_pct,
        "tc": trades_count, "w": winners, "l": losers, "bd": breakdown,
    })
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _sample_data(alloc_id=1, bot_id="test_bot") -> dict:
    return {
        "allocation_id": alloc_id,
        "bot_id": bot_id,
        "user_id": 1,
        "journal_date": TARGET_DATE,
        "date": TARGET_DATE.isoformat(),
        "sleeve": "stocks",
        "asset_class": "stock",
        "starting_capital_cents": 100_000_00,
        "ending_pv_cents": 100_050_00,
        "day_pnl_cents": 5000,
        "day_return_pct": 0.05,
        "trades_count": 3,
        "winning_trades": 2,
        "losing_trades": 1,
        "win_rate": 0.6667,
        "avg_winner_cents": 3000,
        "avg_loser_cents": -1000,
        "profit_factor": 2.0,
        "avg_hold_minutes": 120.0,
        "max_concurrent_positions": 2,
        "end_of_day_positions": 1,
        "end_of_day_deployed_cents": 150_000,
        "deployment_pct_avg": 0.15,
        "regime_vix_band": "LOW",
        "regime_trend": "UP",
        "regime_btc_dom_band": "<50",
        "regime_when_active": {"vix_band": "LOW", "trend": "UP", "btc_dom_band": "<50"},
        "strategies_breakdown": {
            "momentum": {"signals": 2, "trades": 2, "pnl_cents": 4000},
            "mean_rev": {"signals": 1, "trades": 1, "pnl_cents": 1000},
        },
        "strategies_breakdown_json": json.dumps({
            "momentum": {"signals": 2, "trades": 2, "pnl_cents": 4000},
            "mean_rev": {"signals": 1, "trades": 1, "pnl_cents": 1000},
        }),
        "errors_24h": 0,
        "sentry_issues_24h": [],
    }


# ── Helpers that load the daily_journal job freshly per test ──────────────────

def _load_daily_job():
    """Re-load daily_journal.py so it picks up the current sys.modules stubs."""
    return _load("app.jobs.daily_journal", "app/jobs/daily_journal.py")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1 — write journal row to DB
# ═══════════════════════════════════════════════════════════════════════════════

def test_journal_row_writes_to_db(db):
    """write_journal_row persists a row with matching fields."""
    pid = _insert_profile(db, name="test_bot")
    aid = _insert_alloc(db, pid)

    data = _sample_data(alloc_id=aid, bot_id="test_bot")
    row_id = _writer_mod.write_journal_row(db, data)
    db.commit()

    named = db.execute(
        text("SELECT bot_id, day_pnl_cents, trades_count, winning_trades, losing_trades "
             "FROM bot_daily_journals WHERE id=:id"),
        {"id": row_id}
    ).fetchone()
    assert named is not None
    assert named[0] == "test_bot"
    assert named[1] == 5000
    assert named[2] == 3
    assert named[3] == 2
    assert named[4] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2 — idempotent write (UPSERT)
# ═══════════════════════════════════════════════════════════════════════════════

def test_journal_row_idempotent(db):
    """Writing same data twice leaves exactly one row."""
    pid = _insert_profile(db, name="idem_bot")
    aid = _insert_alloc(db, pid)

    data = _sample_data(alloc_id=aid, bot_id="idem_bot")
    _writer_mod.write_journal_row(db, data)
    db.commit()
    _writer_mod.write_journal_row(db, data)
    db.commit()

    count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_journals WHERE bot_id=:bid AND journal_date=:jd"),
        {"bid": "idem_bot", "jd": TARGET_DATE.isoformat()}
    ).fetchone()[0]
    assert count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3 — frontmatter field order
# ═══════════════════════════════════════════════════════════════════════════════

def test_render_frontmatter_field_order():
    """YAML keys appear in the EXACT order specified in the spec."""
    data = _sample_data()
    fm = _writer_mod.render_frontmatter(data)
    lines = fm.splitlines()

    keys = []
    for line in lines:
        if line.strip() in ("---", ""):
            continue
        if not line.startswith(" ") and ":" in line:
            key = line.split(":")[0].strip()
            keys.append(key)

    expected_order = _writer_mod._FRONTMATTER_KEY_ORDER
    common = [k for k in expected_order if k in keys]
    actual_common = [k for k in keys if k in expected_order]
    assert actual_common == common, (
        f"Key order mismatch.\nExpected: {common}\nGot: {actual_common}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4 — frontmatter nested shape
# ═══════════════════════════════════════════════════════════════════════════════

def test_render_frontmatter_nested_shape():
    """regime_when_active has 3 child keys; strategies_breakdown has expected strategy names."""
    data = _sample_data()
    fm = _writer_mod.render_frontmatter(data)

    assert "  vix_band:" in fm
    assert "  trend:" in fm
    assert "  btc_dom_band:" in fm
    assert "  momentum:" in fm
    assert "  mean_rev:" in fm


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5 — daily job creates one row per enabled bot
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_daily_journal_creates_one_row_per_enabled_bot(db):
    """Seeding 3 enabled bots → 3 journal rows + 3 rolling pseudo-rows."""
    _daily_mod = _load_daily_job()

    alloc_ids = []
    for i in range(3):
        pid = _insert_profile(db, name=f"bot_{i}", asset_class="stock")
        aid = _insert_alloc(db, pid)
        alloc_ids.append(aid)
        # Seed 5 trades per allocation inside target_date window
        for j in range(5):
            _insert_trade(db, aid, symbol=f"SYM{j}", target_date=TARGET_DATE)

    result = _daily_mod.run_daily_journal(db, target_date=TARGET_DATE, user_id=1)

    assert result["bots_processed"] == 3
    assert result["rows_written"] == 3

    real_count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_journals WHERE journal_date=:d AND bot_id NOT LIKE '%__rolling30'"),
        {"d": TARGET_DATE.isoformat()}
    ).fetchone()[0]
    assert real_count == 3

    rolling_count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_journals WHERE bot_id LIKE '%__rolling30' AND journal_date=:d"),
        {"d": TARGET_DATE.isoformat()}
    ).fetchone()[0]
    assert rolling_count == 3


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6 — disabled allocations skipped
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_daily_journal_skips_disabled_allocations(db):
    """1 enabled + 1 disabled → only 1 journal row written."""
    _daily_mod = _load_daily_job()

    pid_en = _insert_profile(db, name="enabled_bot")
    _insert_alloc(db, pid_en, enabled=1)
    pid_dis = _insert_profile(db, name="disabled_bot")
    _insert_alloc(db, pid_dis, enabled=0)

    result = _daily_mod.run_daily_journal(db, target_date=TARGET_DATE, user_id=1)

    assert result["bots_processed"] == 1
    real_count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_journals WHERE bot_id NOT LIKE '%__rolling30'")
    ).fetchone()[0]
    assert real_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7 — idempotent run (no duplicates)
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_daily_journal_idempotent(db):
    """Running twice for same target_date produces no duplicate rows."""
    _daily_mod = _load_daily_job()

    pid = _insert_profile(db, name="idem_job_bot")
    _insert_alloc(db, pid)

    _daily_mod.run_daily_journal(db, target_date=TARGET_DATE, user_id=1)
    _daily_mod.run_daily_journal(db, target_date=TARGET_DATE, user_id=1)

    count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_journals WHERE bot_id=:bid AND journal_date=:jd AND bot_id NOT LIKE '%__rolling30'"),
        {"bid": "idem_job_bot", "jd": TARGET_DATE.isoformat()}
    ).fetchone()[0]
    assert count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8 — zero trades → None win_rate, None profit_factor
# ═══════════════════════════════════════════════════════════════════════════════

def test_compute_win_rate_handles_zero_trades(db):
    """Allocation with 0 closed positions → win_rate=None, profit_factor=None, no exception."""
    _daily_mod = _load_daily_job()

    pid = _insert_profile(db, name="zero_trade_bot")
    aid = _insert_alloc(db, pid, capital=100_000_00)

    # Use ORM objects built from raw DB rows to match the job's interface
    alloc = db.query(BotAllocation).filter(BotAllocation.id == aid).first()
    profile = db.query(BotProfile).filter(BotProfile.id == pid).first()

    data = _daily_mod._compute_bot_day(db, alloc, profile, TARGET_DATE)

    assert data["trades_count"] == 0
    assert data["win_rate"] is None
    assert data["profit_factor"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 9 — max_concurrent_positions math
# ═══════════════════════════════════════════════════════════════════════════════

def test_compute_max_concurrent_handles_overlap(db):
    """3 overlapping positions → max_concurrent=3; 3 sequential → max_concurrent=1."""
    _daily_mod = _load_daily_job()

    pid = _insert_profile(db, name="overlap_bot")
    aid = _insert_alloc(db, pid, capital=100_000_00)

    alloc = db.query(BotAllocation).filter(BotAllocation.id == aid).first()
    profile = db.query(BotProfile).filter(BotProfile.id == pid).first()

    # ── Scenario 1: all 3 open simultaneously ────────────────────────────────
    opened_at = "2026-06-29 10:00:00"
    closed_at = "2026-06-29 15:00:00"
    for sym in ("A", "B", "C"):
        db.execute(text(
            "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents, side, opened_at, closed_at) "
            "VALUES (:aid, :sym, 1.0, 10000.0, 'long', :oa, :ca)"
        ), {"aid": aid, "sym": sym, "oa": opened_at, "ca": closed_at})
    db.commit()

    data = _daily_mod._compute_bot_day(db, alloc, profile, TARGET_DATE)
    assert data["max_concurrent_positions"] == 3

    # ── Scenario 2: sequential (1 at a time) ─────────────────────────────────
    db.execute(text("DELETE FROM bot_positions WHERE allocation_id=:aid"), {"aid": aid})
    db.commit()

    for h in range(3):
        t_o = f"2026-06-29 {9 + h:02d}:00:00"
        t_c = f"2026-06-29 {9 + h:02d}:30:00"
        db.execute(text(
            "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents, side, opened_at, closed_at) "
            "VALUES (:aid, :sym, 1.0, 10000.0, 'long', :oa, :ca)"
        ), {"aid": aid, "sym": f"SEQ{h}", "oa": t_o, "ca": t_c})
    db.commit()

    data2 = _daily_mod._compute_bot_day(db, alloc, profile, TARGET_DATE)
    assert data2["max_concurrent_positions"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 10 — rolling 30d aggregates existing journals
# ═══════════════════════════════════════════════════════════════════════════════

def test_rolling_30d_aggregates_existing_journals(db):
    """5 journal rows → pseudo-row total_pnl == sum, total_trades == sum."""
    pid = _insert_profile(db, name="rolling_bot")
    aid = _insert_alloc(db, pid, capital=100_000_00)

    total_pnl = 0
    total_trades = 0
    base = date(2026, 6, 25)
    for i in range(5):
        d = date(base.year, base.month, base.day + i)
        pnl = (i + 1) * 1000
        trades = i + 1
        total_pnl += pnl
        total_trades += trades
        _insert_journal(db, aid, "rolling_bot", pnl, trades, journal_date=d)

    summary = _rolling_mod.compute_rolling_30d(db, "rolling_bot", TARGET_DATE)
    assert summary["total_pnl_cents"] == total_pnl
    assert summary["total_trades"] == total_trades
    assert summary["journals_count"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 11 — rolling Sharpe is 0.0 when fewer than 5 days
# ═══════════════════════════════════════════════════════════════════════════════

def test_rolling_30d_handles_fewer_than_30(db):
    """3 journal rows → rolling_sharpe == 0.0 (insufficient sample)."""
    pid = _insert_profile(db, name="sparse_bot")
    aid = _insert_alloc(db, pid, capital=100_000_00)

    base = date(2026, 6, 27)
    for i in range(3):
        d = date(base.year, base.month, base.day + i)
        _insert_journal(db, aid, "sparse_bot", 500, 1, journal_date=d)

    _rolling_mod.write_rolling_summary(db, "sparse_bot", TARGET_DATE)
    db.commit()

    row = db.execute(
        text("SELECT strategies_breakdown_json FROM bot_daily_journals WHERE bot_id=:bid"),
        {"bid": "sparse_bot__rolling30"}
    ).fetchone()
    assert row is not None

    raw = json.loads(row[0])
    assert raw["rolling_sharpe"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 12 — regime_snapshot returns UNKNOWN when table empty, then mapped values
# ═══════════════════════════════════════════════════════════════════════════════

def test_regime_snapshot_returns_known_or_unknown(db):
    """Empty regime_snapshots → all UNKNOWN. Insert row → mapped values."""
    result = _regime_mod.snapshot(db)
    assert result == {"vix_band": "UNKNOWN", "trend": "UNKNOWN", "btc_dom_band": "UNKNOWN"}

    # Insert a fresh (non-stale) row
    now_iso = datetime.now(UTC).isoformat()
    db.execute(text(
        "INSERT INTO regime_snapshots (ts, vix_regime, trend_regime, btc_dominance) "
        "VALUES (:ts, 'low', 'bull', 0.45)"
    ), {"ts": now_iso})
    db.commit()

    result2 = _regime_mod.snapshot(db)
    assert result2["vix_band"] == "LOW"
    assert result2["trend"] == "UP"
    assert result2["btc_dom_band"] == "<50"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 13 — btc_dom_band threshold table-driven test
# ═══════════════════════════════════════════════════════════════════════════════

def test_regime_snapshot_btc_dom_band_thresholds(db):
    """Table-driven btc_dom_band thresholds + percent-form coercion."""
    cases = [
        (0.45, "<50"),
        (0.52, "50-55"),
        (0.58, "55-60"),
        (0.62, "60-65"),
        (0.70, ">65"),
        (45.0, "<50"),   # percent form coercion
    ]
    now_iso = datetime.now(UTC).isoformat()
    for btc_val, expected_band in cases:
        db.execute(text("DELETE FROM regime_snapshots"))
        db.commit()

        db.execute(text(
            "INSERT INTO regime_snapshots (ts, vix_regime, trend_regime, btc_dominance) "
            "VALUES (:ts, 'mid', 'chop', :btc)"
        ), {"ts": now_iso, "btc": btc_val})
        db.commit()

        result = _regime_mod.snapshot(db)
        assert result["btc_dom_band"] == expected_band, (
            f"btc={btc_val} expected band={expected_band}, got {result['btc_dom_band']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 14 — scheduler registers daily_journal_nightly job
# ═══════════════════════════════════════════════════════════════════════════════

def test_scheduler_registers_daily_journal_job():
    """setup_bot_scheduler registers job id='daily_journal_nightly' with CronTrigger hour=4, UTC."""
    from apscheduler.triggers.cron import CronTrigger as _CT

    recorded_calls: list[dict] = []

    class MockScheduler:
        def add_job(self, func, trigger=None, id=None, **kwargs):
            recorded_calls.append({"id": id, "trigger": trigger, "func": func})

        def __getattr__(self, name):
            return MagicMock()

    mock_sched = MockScheduler()

    # Load bot_scheduler with heavy deps patched
    sched_path = os.path.join(_BACKEND_ROOT, "strategy_lab", "bot_scheduler.py")
    spec = importlib.util.spec_from_file_location("_bot_sched_under_test", sched_path)
    bot_sched_mod = importlib.util.module_from_spec(spec)

    heavy_stubs = {
        "app.db.session": MagicMock(SessionLocal=MagicMock()),
        "app.services.capital_invariant": MagicMock(),
        "app.services.discord": MagicMock(),
        "app.services.notify": MagicMock(),
        "sentry_sdk": MagicMock(),
        "app.services.discipline": MagicMock(),
        "app.jobs.daily_journal": MagicMock(),
    }

    with patch.dict(sys.modules, heavy_stubs):
        try:
            spec.loader.exec_module(bot_sched_mod)
        except Exception:
            pass

        try:
            bot_sched_mod.setup_bot_scheduler(mock_sched)
        except Exception:
            pass

    journal_calls = [c for c in recorded_calls if c.get("id") == "daily_journal_nightly"]
    assert len(journal_calls) >= 1, (
        f"daily_journal_nightly not found. Registered ids: {[c.get('id') for c in recorded_calls]}"
    )

    trigger = journal_calls[0]["trigger"]
    assert isinstance(trigger, _CT), f"Expected CronTrigger, got {type(trigger)}"
    field_map = {f.name: f for f in trigger.fields}
    assert str(field_map["hour"]) == "4", f"Expected hour=4, got {field_map['hour']}"
    assert str(field_map["minute"]) == "0", f"Expected minute=0, got {field_map['minute']}"


# ── Router module (shared by tests 15-17) ────────────────────────────────────

_sj_mod = _load("app.routers.strategy_journal", "app/routers/strategy_journal.py")
sys.modules["app.routers.strategy_journal"] = _sj_mod


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 15 — endpoint 404 when journal missing
# ═══════════════════════════════════════════════════════════════════════════════

def test_endpoint_404_when_missing(db):
    """get_journal raises HTTPException(404) when journal row is absent.

    Called directly (not via TestClient) to bypass FastAPI dependency injection
    issues in the test environment.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _sj_mod.get_journal(
            bot_id="nonexistent_bot",
            journal_date=date(2026, 1, 1),
            db=db,
            _admin=MagicMock(),
        )
    assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 16 — endpoint 401 without auth
# ═══════════════════════════════════════════════════════════════════════════════

def test_endpoint_401_without_auth(db):
    """require_admin raises HTTPException(401) when no auth token provided.

    Tests the auth dependency directly — the endpoint itself is protected by
    require_admin which raises 401 on no/invalid token. We call require_admin
    directly without providing a token to verify the 401 behavior.
    """
    from fastapi import HTTPException

    # Stub app.db.models.users so the import in get_current_user works
    _users_stub = MagicMock()
    _users_stub.User = MagicMock()
    with patch.dict(sys.modules, {"app.db.models.users": _users_stub}):
        # require_admin calls get_current_user with token=None → raises 401
        with pytest.raises(HTTPException) as exc_info:
            _deps_mod.require_admin(token=None, db=db)
    assert exc_info.value.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 17 — endpoint returns frontmatter_yaml, body_md, vault_path
# ═══════════════════════════════════════════════════════════════════════════════

def test_endpoint_returns_frontmatter_and_body(db):
    """get_journal returns dict with frontmatter_yaml, body_md, vault_path for a seeded row.

    Called directly (not via TestClient) to bypass FastAPI dependency injection
    issues in the test environment.
    """
    pid = _insert_profile(db, name="stock_swing_ep", asset_class="stock")
    aid = _insert_alloc(db, pid, capital=100_000_00)

    data = _sample_data(alloc_id=aid, bot_id="stock_swing_ep")
    _writer_mod.write_journal_row(db, data)
    db.commit()

    result = _sj_mod.get_journal(
        bot_id="stock_swing_ep",
        journal_date=TARGET_DATE,
        db=db,
        _admin=MagicMock(),
    )

    assert "frontmatter_yaml" in result
    assert "body_md" in result
    assert "vault_path" in result
    assert result["bot_id"] == "stock_swing_ep"
    assert "---" in result["frontmatter_yaml"]
    assert "Day Summary" in result["body_md"]
    assert "BMG-Capital-Vault" in result["vault_path"]
