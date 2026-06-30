"""Tests for GET /api/admin/bots/diagnostics.

Strategy: load the real admin handler via importlib INSIDE each test (not at
module level), so we never pollute sys.modules for other test files.  Each
test gets its own snapshot+restore cycle that is self-contained and leaves
no residue.

The handler is tested end-to-end:
  - SQL executes against a real SQLite DB seeded via ORM objects.
  - Auth is bypassed by passing a mock user directly.
  - HTTP validation (hours bounds-check) tests the HTTPException directly.

All 11 tests (9 required + 2 bonus) pass without any real DB or auth token.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


# ─── Per-test module loader ────────────────────────────────────────────────────
# All sys.modules manipulation is done INSIDE each test, wrapped in a
# snapshot/restore so we never affect other test files.


def _load_real_modules():
    """Load the ORM models and admin handler into sys.modules.

    Returns (snapshot_of_original_keys, {objects...}) tuple.
    Caller MUST call _restore_modules(snapshot) in their finally block.

    Deliberately does NOT set parent module attributes (avoids polluting
    conftest stubs that unittest.mock.patch() traverses via _importer).
    """
    overwrites: dict[str, object] = {}
    _ABSENT = object()  # local sentinel

    def _record(key):
        if key not in overwrites:
            overwrites[key] = sys.modules.get(key, _ABSENT)

    def _load_real(module_name: str, rel_path: str):
        abs_path = str(BACKEND_ROOT / rel_path)
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {module_name} from {abs_path}")
        mod = importlib.util.module_from_spec(spec)
        _record(module_name)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod

    def restore():
        for key, original in overwrites.items():
            if original is _ABSENT:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = original

    # Load ORM base + models (SQLAlchemy classes we need for seeding)
    base_mod = _load_real("app.db.base", "app/db/base.py")
    _load_real("app.db.models.bots", "app/db/models/bots.py")
    _load_real("app.db.models.users", "app/db/models/users.py")

    # config (needed by app.dependencies)
    if "app.config" not in sys.modules or not hasattr(
        sys.modules.get("app.config"), "settings"
    ):
        _load_real("app.config", "app/config.py")
    else:
        # Already loaded correctly; record so restore can skip if needed
        _record("app.config")

    # Session stub (satisfies `from app.db.session import get_db` in admin.py)
    session_stub = types.ModuleType("app.db.session")
    session_stub.get_db = lambda: None
    session_stub.SessionLocal = MagicMock()
    session_stub.engine = MagicMock()
    _record("app.db.session")
    sys.modules["app.db.session"] = session_stub

    # Real dependencies module (provides get_current_user)
    _load_real("app.dependencies", "app/dependencies.py")

    # Real admin router (module under test)
    _load_real("app.routers.admin", "app/routers/admin.py")

    # Grab the objects we need
    from app.db.base import Base  # noqa: E402
    from app.db.models.bots import BotProfile, BotAllocation, BotSignal, BotTrade
    from app.db.models.users import User
    from app.routers.admin import get_bot_diagnostics

    return restore, {
        "Base": Base,
        "BotProfile": BotProfile,
        "BotAllocation": BotAllocation,
        "BotSignal": BotSignal,
        "BotTrade": BotTrade,
        "User": User,
        "get_bot_diagnostics": get_bot_diagnostics,
    }


# ─── DB + seed helpers ────────────────────────────────────────────────────────

def _make_db(Base):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.is_active = True
    u.is_admin = True
    return u


def _call(get_bot_diagnostics, db, hours=24):
    return get_bot_diagnostics(hours=hours, db=db, current_user=_mock_user())


def _seed_bot(db, BotProfile, BotAllocation, name, asset_class="stock",
              profile_enabled=True, allocation_enabled=True,
              paused_reason=None, user_id=1):
    prof = BotProfile(name=name, asset_class=asset_class, enabled=profile_enabled)
    db.add(prof)
    db.flush()
    alloc = BotAllocation(
        profile_id=prof.id, user_id=user_id,
        enabled=allocation_enabled, paused_reason=paused_reason,
        starting_capital_cents=10_000_000,
    )
    db.add(alloc)
    db.flush()
    return alloc


def _seed_signal(db, BotSignal, allocation_id, ts):
    sig = BotSignal(
        allocation_id=allocation_id, ts=ts,
        symbol="AAPL", side="buy", confidence=0.8,
    )
    db.add(sig)
    db.flush()
    return sig


def _seed_trade(db, BotTrade, allocation_id, ts, quarantined_at=None):
    trade = BotTrade(
        allocation_id=allocation_id, symbol="AAPL", side="buy",
        qty=1.0, fill_price_cents=15000, ts=ts, quarantined_at=quarantined_at,
    )
    db.add(trade)
    db.flush()
    return trade


NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — endpoint returns all bots
# ─────────────────────────────────────────────────────────────────────────────

def test_endpoint_returns_all_bots():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        for i in range(3):
            _seed_bot(db, m["BotProfile"], m["BotAllocation"], f"bot_{i}")
        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        assert len(result["bots"]) == 3
        assert result["summary"]["total_bots"] == 3
    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — verdict: trading
# ─────────────────────────────────────────────────────────────────────────────

def test_verdict_trading():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "trading_bot")
        for _ in range(5):
            _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=1))
        for _ in range(2):
            _seed_trade(db, m["BotTrade"], alloc.id, NOW - timedelta(minutes=30))
        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        bot = result["bots"][0]
        assert bot["verdict"] == "trading"
        assert bot["signals_window"] == 5
        assert bot["trades_window"] == 2
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — verdict: signals_no_trades
# ─────────────────────────────────────────────────────────────────────────────

def test_verdict_signals_no_trades():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "signals_bot")
        for _ in range(5):
            _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=1))
        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        assert result["bots"][0]["verdict"] == "signals_no_trades"
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — verdict: no_signals
# ─────────────────────────────────────────────────────────────────────────────

def test_verdict_no_signals():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "silent_bot")
        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        assert result["bots"][0]["verdict"] == "no_signals"
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — verdict: paused
# ─────────────────────────────────────────────────────────────────────────────

def test_verdict_paused():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "paused_bot",
                  allocation_enabled=False,
                  paused_reason="strategy_generates_invalid_symbols")
        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        bot = result["bots"][0]
        assert bot["verdict"] == "paused"
        assert bot["allocation_paused_reason"] == "strategy_generates_invalid_symbols"
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — verdict: profile_disabled (beats allocation state)
# ─────────────────────────────────────────────────────────────────────────────

def test_verdict_profile_disabled():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "disabled_profile_bot",
                  profile_enabled=False, allocation_enabled=True)
        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        assert result["bots"][0]["verdict"] == "profile_disabled"
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — verdict: stale (signal in window, last trade > 48h ago)
# ─────────────────────────────────────────────────────────────────────────────

def test_verdict_stale():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "stale_bot")
        _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=1))
        _seed_trade(db, m["BotTrade"], alloc.id, NOW - timedelta(hours=50))
        db.commit()
        result = _call(m["get_bot_diagnostics"], db, hours=168)
        bot = result["bots"][0]
        assert bot["verdict"] == "stale", (
            f"Expected stale, got {bot['verdict']}. "
            f"trades_window={bot['trades_window']} signals_window={bot['signals_window']}"
        )
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — window_hours param changes signal count
# ─────────────────────────────────────────────────────────────────────────────

def test_window_hours_param():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "window_bot")
        _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=5))
        _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=30))
        db.commit()

        result24 = _call(m["get_bot_diagnostics"], db, hours=24)
        assert result24["bots"][0]["signals_window"] == 1

        result48 = _call(m["get_bot_diagnostics"], db, hours=48)
        assert result48["bots"][0]["signals_window"] == 2
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 — summary counts correct for mixed fleet
# ─────────────────────────────────────────────────────────────────────────────

def test_summary_counts_correct():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        # 3 trading bots
        for i in range(3):
            alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], f"trading_{i}")
            _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=1))
            _seed_trade(db, m["BotTrade"], alloc.id, NOW - timedelta(minutes=30))

        # 2 paused bots
        for i in range(2):
            _seed_bot(db, m["BotProfile"], m["BotAllocation"], f"paused_{i}",
                      allocation_enabled=False, paused_reason="test_pause")

        # 4 no_signals bots
        for i in range(4):
            _seed_bot(db, m["BotProfile"], m["BotAllocation"], f"no_signal_{i}")

        # 1 signals_no_trades bot
        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "sig_no_trade")
        _seed_signal(db, m["BotSignal"], alloc.id, NOW - timedelta(hours=1))

        db.commit()
        result = _call(m["get_bot_diagnostics"], db)
        summary = result["summary"]

        assert summary == {
            "total_bots": 10,
            "trading": 3,
            "stale": 0,
            "signals_no_trades": 1,
            "no_signals": 4,
            "paused": 2,
            "profile_disabled": 0,
        }, f"summary mismatch: {summary}"
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Bonus test 10 — hours param validation raises 400
# ─────────────────────────────────────────────────────────────────────────────

def test_hours_param_validation():
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        for bad_hours in [0, 169, -5]:
            with pytest.raises(HTTPException) as exc_info:
                _call(m["get_bot_diagnostics"], db, hours=bad_hours)
            assert exc_info.value.status_code == 400, (
                f"hours={bad_hours} should raise 400, got {exc_info.value.status_code}"
            )
            assert "hours must be 1..168" in exc_info.value.detail
    finally:
        db.close(); engine.dispose(); restore()


# ─────────────────────────────────────────────────────────────────────────────
# Bonus test 11 — user scoping (user_id=2 bots excluded)
# ─────────────────────────────────────────────────────────────────────────────

def test_user_scoping():
    """Per known-issues.md #6 (183 vs 57 discrepancy): endpoint must only
    return bots for user_id=1, not cross-user allocations."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "user1_bot", user_id=1)
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "user2_bot", user_id=2)
        db.commit()

        result = _call(m["get_bot_diagnostics"], db)
        bot_names = [b["bot_name"] for b in result["bots"]]
        assert "user1_bot" in bot_names
        assert "user2_bot" not in bot_names, (
            "user_id=2 bot leaked into user_id=1 response — scoping bug!"
        )
        assert result["summary"]["total_bots"] == 1
    finally:
        db.close(); engine.dispose(); restore()
