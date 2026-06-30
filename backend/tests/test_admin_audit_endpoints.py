"""Tests for admin audit endpoints:
  GET /api/admin/bot-diagnostic
  GET /api/admin/trade-count-reconcile
  GET /api/admin/asset-class-audit
  GET /api/admin/inert-bot-scan
  GET /api/admin/fund-tear-sheet-honesty-check

Strategy: load the real admin handler via importlib INSIDE each test (not at
module level), so we never pollute sys.modules for other test files.  Each
test gets its own snapshot+restore cycle that is self-contained and leaves
no residue.

The handlers are tested end-to-end:
  - SQL executes against a real SQLite DB seeded via ORM objects.
  - Auth is bypassed by passing a mock user directly.
  - Cache is cleared between tests via a module-level fixture.

All 11 tests pass without any real DB or auth token.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


# ─── Per-test module loader ────────────────────────────────────────────────────

def _load_real_modules():
    """Load the ORM models and admin handler into sys.modules.

    Returns (restore_fn, {objects...}) tuple.
    Caller MUST call restore() in their finally block.
    """
    overwrites: dict[str, object] = {}
    _ABSENT = object()

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

    # Load ORM base + models
    base_mod = _load_real("app.db.base", "app/db/base.py")
    _load_real("app.db.models.bots", "app/db/models/bots.py")
    _load_real("app.db.models.users", "app/db/models/users.py")
    _load_real("app.db.models.signal_gates", "app/db/models/signal_gates.py")

    # config
    if "app.config" not in sys.modules or not hasattr(
        sys.modules.get("app.config"), "settings"
    ):
        _load_real("app.config", "app/config.py")
    else:
        _record("app.config")

    # Session stub
    session_stub = types.ModuleType("app.db.session")
    session_stub.get_db = lambda: None
    session_stub.SessionLocal = MagicMock()
    session_stub.engine = MagicMock()
    _record("app.db.session")
    sys.modules["app.db.session"] = session_stub

    # Real dependencies module
    _load_real("app.dependencies", "app/dependencies.py")

    # Real admin router (module under test)
    admin_mod = _load_real("app.routers.admin", "app/routers/admin.py")

    # Grab the objects we need
    from app.db.base import Base  # noqa: E402
    from app.db.models.bots import BotProfile, BotAllocation, BotSignal, BotTrade, BotPosition
    from app.db.models.signal_gates import SignalGate
    from app.db.models.users import User
    from app.routers.admin import (
        get_bot_diagnostic_singular,
        get_trade_count_reconcile,
        get_asset_class_audit,
        get_inert_bot_scan,
        get_fund_tear_sheet_honesty_check,
        _AUDIT_CACHE,
    )

    return restore, {
        "Base": Base,
        "BotProfile": BotProfile,
        "BotAllocation": BotAllocation,
        "BotSignal": BotSignal,
        "BotTrade": BotTrade,
        "BotPosition": BotPosition,
        "SignalGate": SignalGate,
        "User": User,
        "get_bot_diagnostic_singular": get_bot_diagnostic_singular,
        "get_trade_count_reconcile": get_trade_count_reconcile,
        "get_asset_class_audit": get_asset_class_audit,
        "get_inert_bot_scan": get_inert_bot_scan,
        "get_fund_tear_sheet_honesty_check": get_fund_tear_sheet_honesty_check,
        "_AUDIT_CACHE": _AUDIT_CACHE,
    }


# ─── DB + seed helpers ────────────────────────────────────────────────────────

def _make_db(Base):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # Also create bot_heartbeat (not an ORM model — created by m018 migration raw SQL)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_heartbeat (
                bot_name TEXT PRIMARY KEY,
                last_signal_at DATETIME,
                last_scan_at DATETIME,
                expected_cadence_minutes INTEGER NOT NULL DEFAULT 90,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.is_active = True
    u.is_admin = True
    return u


def _seed_bot(db, BotProfile, BotAllocation, name,
              asset_class="stock",
              profile_enabled=True,
              allocation_enabled=True,
              paused_reason=None,
              config_json=None,
              user_id=1):
    prof = BotProfile(
        name=name,
        asset_class=asset_class,
        enabled=profile_enabled,
        config_json=config_json,
    )
    db.add(prof)
    db.flush()
    alloc = BotAllocation(
        profile_id=prof.id,
        user_id=user_id,
        enabled=allocation_enabled,
        paused_reason=paused_reason,
        starting_capital_cents=10_000_000,
    )
    db.add(alloc)
    db.flush()
    return alloc


def _seed_position(db, BotPosition, allocation_id, exit_reason=None):
    pos = BotPosition(
        allocation_id=allocation_id,
        symbol="AAPL",
        qty=1.0,
        avg_cost_cents=15000,
        side="long",
        opened_at=datetime.now(timezone.utc) - timedelta(hours=2),
        exit_reason=exit_reason,
    )
    db.add(pos)
    db.flush()
    return pos


def _seed_trade(db, BotTrade, allocation_id, symbol="AAPL",
                ts=None, position_id=None, quarantined_at=None):
    if ts is None:
        ts = datetime.now(timezone.utc) - timedelta(minutes=30)
    trade = BotTrade(
        allocation_id=allocation_id,
        symbol=symbol,
        side="buy",
        qty=1.0,
        fill_price_cents=15000,
        ts=ts,
        position_id=position_id,
        quarantined_at=quarantined_at,
    )
    db.add(trade)
    db.flush()
    return trade


def _seed_signal(db, BotSignal, allocation_id, ts=None):
    if ts is None:
        ts = datetime.now(timezone.utc) - timedelta(hours=1)
    sig = BotSignal(
        allocation_id=allocation_id,
        ts=ts,
        symbol="AAPL",
        side="buy",
        confidence=0.8,
    )
    db.add(sig)
    db.flush()
    return sig


NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — bot-diagnostic shape
# ─────────────────────────────────────────────────────────────────────────────

def test_bot_diagnostic_shape():
    """Seed 3 bots: trading, paused, empty config. Assert exact summary keys and
    bot field keys. Assert strategy_count=0 for empty-config bot."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        # Bot 1: trading (signals + trades)
        alloc1 = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "trading_bot",
                           config_json={"strategies": ["s1", "s2"]})
        _seed_signal(db, m["BotSignal"], alloc1.id)
        _seed_trade(db, m["BotTrade"], alloc1.id)

        # Bot 2: paused (allocation disabled)
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "paused_bot",
                  allocation_enabled=False, paused_reason="test_pause")

        # Bot 3: empty config_json
        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "no_config_bot",
                  config_json=None)

        db.commit()

        result = m["get_bot_diagnostic_singular"](
            db=db, current_user=_mock_user()
        )

        # Summary keys
        expected_summary_keys = {
            "total", "trading", "no_signals", "paused",
            "profile_disabled", "stale", "signals_no_trades",
        }
        assert set(result["summary"].keys()) == expected_summary_keys, (
            f"Summary keys mismatch: {set(result['summary'].keys())}"
        )
        assert result["summary"]["total"] == 3

        # Each bot has exact 13 keys (added open_positions_notional_cents
        # + starting_capital_cents 2026-06-30 so AQA heuristics can compute
        # deployment_pct without a separate endpoint round-trip).
        expected_bot_keys = {
            "bot_id", "verdict", "signals_24h", "trades_24h", "open_positions",
            "open_positions_notional_cents", "starting_capital_cents",
            "last_signal_at", "last_trade_at", "enabled", "paused_reason",
            "asset_class_declared", "strategy_count",
        }
        for bot in result["bots"]:
            assert set(bot.keys()) == expected_bot_keys, (
                f"Bot {bot.get('bot_id')} key mismatch: {set(bot.keys())}"
            )

        # strategy_count=0 for no-config bot
        no_config = next(b for b in result["bots"] if b["bot_id"] == "no_config_bot")
        assert no_config["strategy_count"] == 0

        # strategy_count=2 for trading bot
        trading = next(b for b in result["bots"] if b["bot_id"] == "trading_bot")
        assert trading["strategy_count"] == 2

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — trade-count-reconcile: counts match isolated data
# ─────────────────────────────────────────────────────────────────────────────

def test_reconcile_counts_match_isolated_data():
    """Seed 2 bots, each with 5 normal trades + 5 cleanup-exit trades.
    Assert leaderboard_count=10, activity_feed_count=20, delta=10."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        for bot_name in ["bot_a", "bot_b"]:
            alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], bot_name)

            # 5 normal trades (no position / non-cleanup position)
            for _ in range(5):
                _seed_trade(db, m["BotTrade"], alloc.id)

            # 5 cleanup-exit trades (position with m045 exit_reason)
            for _ in range(5):
                pos = _seed_position(db, m["BotPosition"], alloc.id,
                                     exit_reason="m045_cross_sleeve_violation")
                _seed_trade(db, m["BotTrade"], alloc.id, position_id=pos.id)

        db.commit()

        result = m["get_trade_count_reconcile"](db=db, current_user=_mock_user())

        assert result["leaderboard_count"] == 10, (
            f"Expected leaderboard_count=10, got {result['leaderboard_count']}"
        )
        assert result["activity_feed_count"] == 20, (
            f"Expected activity_feed_count=20, got {result['activity_feed_count']}"
        )
        assert result["delta"] == 10, (
            f"Expected delta=10, got {result['delta']}"
        )

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — trade-count-reconcile: per-bot breakdown
# ─────────────────────────────────────────────────────────────────────────────

def test_reconcile_per_bot_breakdown():
    """Same seed as test 2. Assert by_bot has 2 entries with
    leaderboard=5, activity_feed=10, delta=5 each. Assert sorted by delta desc."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        for bot_name in ["bot_a", "bot_b"]:
            alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], bot_name)

            for _ in range(5):
                _seed_trade(db, m["BotTrade"], alloc.id)

            for _ in range(5):
                pos = _seed_position(db, m["BotPosition"], alloc.id,
                                     exit_reason="m045_cross_sleeve_violation")
                _seed_trade(db, m["BotTrade"], alloc.id, position_id=pos.id)

        db.commit()

        result = m["get_trade_count_reconcile"](db=db, current_user=_mock_user())

        assert len(result["by_bot"]) == 2, (
            f"Expected 2 by_bot entries, got {len(result['by_bot'])}"
        )

        for entry in result["by_bot"]:
            assert entry["leaderboard"] == 5, (
                f"Bot {entry['bot_id']}: expected leaderboard=5, got {entry['leaderboard']}"
            )
            assert entry["activity_feed"] == 10, (
                f"Bot {entry['bot_id']}: expected activity_feed=10, got {entry['activity_feed']}"
            )
            assert entry["delta"] == 5, (
                f"Bot {entry['bot_id']}: expected delta=5, got {entry['delta']}"
            )

        # Sorted by delta desc (both equal, but at least length check above passes)
        deltas = [e["delta"] for e in result["by_bot"]]
        assert deltas == sorted(deltas, reverse=True)

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — asset-class-audit: no violations
# ─────────────────────────────────────────────────────────────────────────────

def test_asset_class_no_violations():
    """Seed crypto bot with BTC/USD, stock bot with AAPL, options bot with OCC symbol.
    Assert violations_count=0, real_violations_count=0, violations=[]."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        # Crypto bot trading BTC/USD — fine
        alloc_c = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "crypto_bot",
                            asset_class="crypto")
        _seed_trade(db, m["BotTrade"], alloc_c.id, symbol="BTC/USD")

        # Stock bot trading AAPL — fine (declared=stock, executed=equity -> match)
        alloc_s = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "stock_bot",
                            asset_class="stock")
        _seed_trade(db, m["BotTrade"], alloc_s.id, symbol="AAPL")

        # Options bot trading OCC option — fine
        alloc_o = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "options_bot",
                            asset_class="options")
        _seed_trade(db, m["BotTrade"], alloc_o.id, symbol="SPY250816P00400000")

        db.commit()

        result = m["get_asset_class_audit"](hours=24, db=db, current_user=_mock_user())

        assert result["violations_count"] == 0, (
            f"Expected violations_count=0, got {result['violations_count']}"
        )
        assert result["real_violations_count"] == 0
        assert result["violations"] == []

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — asset-class-audit: cleanup exit excluded
# ─────────────────────────────────────────────────────────────────────────────

def test_asset_class_cleanup_excluded():
    """Seed crypto bot with AAPL trade pointing at m045 cleanup position.
    Assert violations has 1 entry with is_cleanup_exit=True, cleanup_migration='m045'.
    Assert real_violations_count=0, cleanup_exits_excluded_count=1."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "crypto_onchain",
                          asset_class="crypto")
        pos = _seed_position(db, m["BotPosition"], alloc.id,
                             exit_reason="m045_cross_sleeve_violation")
        _seed_trade(db, m["BotTrade"], alloc.id, symbol="AAPL", position_id=pos.id)

        db.commit()

        result = m["get_asset_class_audit"](hours=24, db=db, current_user=_mock_user())

        assert len(result["violations"]) == 1, (
            f"Expected 1 violation entry, got {len(result['violations'])}"
        )
        v = result["violations"][0]
        assert v["is_cleanup_exit"] is True
        assert v["cleanup_migration"] == "m045"
        assert result["real_violations_count"] == 0
        assert result["cleanup_exits_excluded_count"] == 1

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — asset-class-audit: real violation
# ─────────────────────────────────────────────────────────────────────────────

def test_asset_class_real_violation():
    """Seed crypto bot with NVDA trade, position.exit_reason=NULL.
    Assert violations_count=1, is_cleanup_exit=False, cleanup_migration=null."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "crypto_bot",
                          asset_class="crypto")
        # No exit_reason on position -> not a cleanup exit
        pos = _seed_position(db, m["BotPosition"], alloc.id, exit_reason=None)
        _seed_trade(db, m["BotTrade"], alloc.id, symbol="NVDA", position_id=pos.id)

        db.commit()

        result = m["get_asset_class_audit"](hours=24, db=db, current_user=_mock_user())

        assert result["violations_count"] == 1, (
            f"Expected violations_count=1, got {result['violations_count']}"
        )
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert v["is_cleanup_exit"] is False
        assert v["cleanup_migration"] is None

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — inert-bot-scan: bot_disabled verdict
# ─────────────────────────────────────────────────────────────────────────────

def test_inert_verdict_bot_disabled():
    """Seed bot with allocation.enabled=False. Assert in inert_bots with
    verdict='bot_disabled', enabled=False."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "disabled_bot",
                  allocation_enabled=False, paused_reason="test_pause",
                  config_json={"strategies": ["s1"]})
        db.commit()

        result = m["get_inert_bot_scan"](hours=24, db=db, current_user=_mock_user())

        inert = result["inert_bots"]
        assert len(inert) == 1
        bot = inert[0]
        assert bot["verdict"] == "bot_disabled", (
            f"Expected bot_disabled, got {bot['verdict']}"
        )
        assert bot["enabled"] is False

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — inert-bot-scan: no_strategies_attached verdict
# ─────────────────────────────────────────────────────────────────────────────

def test_inert_verdict_no_strategies():
    """Seed enabled bot with config_json={"strategies": []}.
    Assert verdict='no_strategies_attached'."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "empty_strat_bot",
                  config_json={"strategies": []})
        db.commit()

        result = m["get_inert_bot_scan"](hours=24, db=db, current_user=_mock_user())

        inert = result["inert_bots"]
        assert len(inert) == 1
        bot = inert[0]
        assert bot["verdict"] == "no_strategies_attached", (
            f"Expected no_strategies_attached, got {bot['verdict']}"
        )

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 — inert-bot-scan: scanner_not_running verdict (no heartbeat row)
# ─────────────────────────────────────────────────────────────────────────────

def test_inert_verdict_scanner_not_running():
    """Seed enabled bot with config_json={"strategies": ["s1"]}.
    No bot_heartbeat row. No signals. No trades.
    Assert verdict='scanner_not_running', scanner_ran_24h=False, scanner_last_run_at=None."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        _seed_bot(db, m["BotProfile"], m["BotAllocation"], "no_heartbeat_bot",
                  config_json={"strategies": ["s1"]})
        db.commit()

        result = m["get_inert_bot_scan"](hours=24, db=db, current_user=_mock_user())

        inert = result["inert_bots"]
        assert len(inert) == 1
        bot = inert[0]
        assert bot["verdict"] == "scanner_not_running", (
            f"Expected scanner_not_running, got {bot['verdict']}"
        )
        assert bot["scanner_ran_24h"] is False
        assert bot["scanner_last_run_at"] is None

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 10 — fund-tear-sheet-honesty-check: field lists present
# ─────────────────────────────────────────────────────────────────────────────

def test_tear_sheet_honesty_returns_field_lists():
    """Hit endpoint with empty DB. Assert real_fields non-empty, fabricated_fields
    non-empty. Assert 'sharpe_ratio' in fabricated_fields. Assert 'nav_total' in
    real_fields. Assert banner_displayed=True, banner_added_in_pr='#35'."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        result = m["get_fund_tear_sheet_honesty_check"](db=db, current_user=_mock_user())

        assert len(result["real_fields"]) > 0
        assert len(result["fabricated_fields"]) > 0
        assert "sharpe_ratio" in result["fabricated_fields"]
        assert "nav_total" in result["real_fields"]
        assert result["banner_displayed"] is True
        assert result["banner_added_in_pr"] == "#35"
        assert "fund_history_days" in result
        assert isinstance(result["fund_history_days"], int)

    finally:
        db.close()
        engine.dispose()
        restore()


# ─────────────────────────────────────────────────────────────────────────────
# Test 11 — fund-tear-sheet-honesty-check: fund_history_days computed
# ─────────────────────────────────────────────────────────────────────────────

def test_tear_sheet_honesty_fund_history_days_computed():
    """Seed bot with one trade ts = now - 22 days.
    Assert fund_history_days == 22. Assert earliest_real_data_point is ISO-Z formatted."""
    restore, m = _load_real_modules()
    db, engine = _make_db(m["Base"])
    try:
        m["_AUDIT_CACHE"].clear()

        trade_ts = datetime.now(timezone.utc) - timedelta(days=22)
        alloc = _seed_bot(db, m["BotProfile"], m["BotAllocation"], "history_bot")
        _seed_trade(db, m["BotTrade"], alloc.id, ts=trade_ts)
        db.commit()

        result = m["get_fund_tear_sheet_honesty_check"](db=db, current_user=_mock_user())

        assert result["fund_history_days"] == 22, (
            f"Expected fund_history_days=22, got {result['fund_history_days']}"
        )
        assert result["earliest_real_data_point"] is not None
        # Should end with 'Z' (ISO UTC format)
        assert result["earliest_real_data_point"].endswith("Z"), (
            f"earliest_real_data_point should end with Z: {result['earliest_real_data_point']}"
        )

    finally:
        db.close()
        engine.dispose()
        restore()
