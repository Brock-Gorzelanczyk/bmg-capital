"""Tests for the daily Strategy Lab audit job (m050).

11 tests total, all using in-memory SQLite with direct SQL (no ORM class
re-registration). Raw SQL inserts + queries avoid SQLAlchemy MetaData conflicts
that arise when multiple test files load app.db.models.bots in the same session.

All real module loading (admin router, aqa_admin, audit runner) happens inside
each test via _load_real_modules() + restore() to prevent sys.modules pollution.

Tests:
  1.  test_audit_green_state
  2.  test_audit_red_on_capital_drift
  3.  test_audit_red_on_options_format_regression
  4.  test_audit_red_on_crypto_equity_violation
  5.  test_audit_yellow_on_low_deployment
  6.  test_audit_red_on_silent_bot
  7.  test_audit_persists_to_db
  8.  test_audit_endpoint_returns_latest
  9.  test_audit_endpoint_run_now
  10. test_audit_scheduler_wired
  11. test_audit_discord_post_handles_missing_webhook
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── Path setup ───────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
BACKEND_ROOT_STR = str(BACKEND_ROOT)
if BACKEND_ROOT_STR not in sys.path:
    sys.path.insert(0, BACKEND_ROOT_STR)


# ─── Module loader + restore helper ───────────────────────────────────────────

_ABSENT = object()


def _load_real_modules():
    """Load admin router, aqa_admin, and audit runner for one test.

    Returns (restore_fn, module_dict).
    MUST call restore_fn() in finally block.

    Uses minimal stub setup — no ORM models are loaded at module level.
    All SQL runs via raw text() against an in-memory SQLite created per test.
    """
    overwrites: dict = {}

    def _record(key):
        if key not in overwrites:
            overwrites[key] = sys.modules.get(key, _ABSENT)

    def _load(module_name: str, rel_path: str):
        abs_path = str(BACKEND_ROOT / rel_path)
        existing = sys.modules.get(module_name)
        if existing is not None and getattr(existing, "__file__", None):
            return existing
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {module_name} from {abs_path}")
        mod = importlib.util.module_from_spec(spec)
        _record(module_name)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod

    def restore():
        for key, orig in overwrites.items():
            if orig is _ABSENT:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = orig

    # ── Stubs ─────────────────────────────────────────────────────────────────
    _record("sentry_sdk")
    sys.modules.setdefault("sentry_sdk", MagicMock())

    _record("httpx")
    sys.modules.setdefault("httpx", MagicMock())

    config_stub = MagicMock()
    config_stub.settings = MagicMock()
    config_stub.settings.jwt_secret = "test_secret"
    config_stub.settings.jwt_algorithm = "HS256"
    _record("app.config")
    if "app.config" not in sys.modules or not hasattr(sys.modules.get("app.config"), "settings"):
        sys.modules["app.config"] = config_stub

    session_stub = types.ModuleType("app.db.session")
    session_stub.get_db = lambda: None
    session_stub.SessionLocal = MagicMock()
    session_stub.engine = MagicMock()
    _record("app.db.session")
    sys.modules["app.db.session"] = session_stub

    deps_stub = types.ModuleType("app.dependencies")
    deps_stub.get_db = MagicMock()
    deps_stub.get_current_user = MagicMock()
    deps_stub.require_admin = MagicMock()
    _record("app.dependencies")
    sys.modules["app.dependencies"] = deps_stub

    users_stub = types.ModuleType("app.db.models.users")
    users_stub.User = MagicMock()
    _record("app.db.models.users")
    sys.modules.setdefault("app.db.models.users", users_stub)

    discord_stub = types.ModuleType("app.services.discord")
    discord_stub.send_ops_alert = MagicMock()
    _record("app.services.discord")
    sys.modules["app.services.discord"] = discord_stub

    aqa_safety_stub = types.ModuleType("app.services.aqa_safety")
    aqa_safety_stub.freeze = MagicMock()
    aqa_safety_stub.unfreeze = MagicMock()
    aqa_safety_stub.is_frozen = MagicMock(return_value=False)
    _record("app.services.aqa_safety")
    sys.modules["app.services.aqa_safety"] = aqa_safety_stub

    # ── Real modules ──────────────────────────────────────────────────────────
    # Do NOT load app.db.base or app.db.models.bots — those cause MetaData
    # conflicts with test_phase1_daily_journal.py and test_phase2_regime_tagging.py.
    # We use raw SQL for all DB operations.

    _load("app.routers.aqa_admin", "app/routers/aqa_admin.py")
    admin_mod = _load("app.routers.admin", "app/routers/admin.py")
    audit_mod = _load("app.jobs.daily_strategy_lab_audit", "app/jobs/daily_strategy_lab_audit.py")

    run_daily_audit = audit_mod.run_daily_audit
    post_daily_audit_run_now = admin_mod.post_daily_audit_run_now
    get_daily_audit_latest = admin_mod.get_daily_audit_latest

    return restore, {
        "run_daily_audit": run_daily_audit,
        "post_daily_audit_run_now": post_daily_audit_run_now,
        "get_daily_audit_latest": get_daily_audit_latest,
        "admin_mod": admin_mod,
        "audit_mod": audit_mod,
    }


# ─── DB helpers (raw SQL — no ORM, no MetaData pollution) ─────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    asset_class TEXT NOT NULL DEFAULT 'stock',
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    paused_reason TEXT,
    starting_capital_cents INTEGER NOT NULL DEFAULT 0,
    inception_capital_cents INTEGER,
    capital_cents_within_portfolio INTEGER,
    tier TEXT DEFAULT 'T0',
    capital_pct REAL DEFAULT 10.0,
    risk_profile TEXT DEFAULT 'standard',
    paper_mode INTEGER DEFAULT 1,
    go_live_requested INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
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
    quarantined_at TEXT,
    quarantine_reason TEXT,
    is_paper INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bot_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    fill_price_cents REAL NOT NULL,
    fees_cents INTEGER DEFAULT 0,
    ts TEXT NOT NULL,
    position_id INTEGER,
    is_paper INTEGER DEFAULT 1,
    quarantined_at TEXT
);
CREATE TABLE IF NOT EXISTS bot_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    alerts_json TEXT NOT NULL,
    summary_markdown TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_audit_log_run_at ON daily_audit_log(run_at DESC);
CREATE TABLE IF NOT EXISTS aqa_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frozen INTEGER DEFAULT 0,
    frozen_reason TEXT,
    frozen_at TEXT,
    frozen_by TEXT,
    deploys_today INTEGER DEFAULT 0,
    llm_calls_today INTEGER DEFAULT 0,
    counter_date TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS aqa_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT,
    created_at TEXT,
    issue_tags TEXT,
    outcome TEXT
);
CREATE TABLE IF NOT EXISTS llm_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    agent_name TEXT,
    estimated_cost_cents INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bot_heartbeat (
    bot_name TEXT PRIMARY KEY,
    last_signal_at TEXT,
    last_scan_at TEXT,
    expected_cadence_minutes INTEGER NOT NULL DEFAULT 90,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


def _make_db():
    """Create isolated in-memory SQLite with all tables needed by the audit runner."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        # Seed one aqa_state row
        conn.execute(text(
            "INSERT INTO aqa_state (id, frozen, deploys_today, llm_calls_today)"
            " VALUES (1, 0, 0, 0)"
        ))
        conn.commit()
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _mock_user():
    u = MagicMock()
    u.id = 1
    u.is_active = True
    u.is_admin = True
    return u


BOT_NAMES = [
    "stock_swing", "stock_momentum", "stock_mean_reversion",
    "options_directional", "options_income",
    "crypto_quant_scalper", "crypto_quant_mean_reversion", "crypto_quant_aggressive",
    "crypto_onchain",
    "macro_rotation", "quality_factor", "value_quality", "earnings_nlp",
]
assert len(BOT_NAMES) == 13, "Fixture must have exactly 13 bots"


def _seed_13_bots(db, capital_per_bot=None):
    """Seed exactly 13 enabled bots for user_id=1 via raw SQL."""
    if capital_per_bot is None:
        capitals = [100_000_000 // 13] * 13
        capitals[-1] += 100_000_000 - sum(capitals)
    else:
        capitals = [capital_per_bot] * 13

    alloc_ids = []
    for i, name in enumerate(BOT_NAMES):
        asset_class = "crypto" if "crypto" in name else "stock"
        db.execute(text(
            "INSERT INTO bot_profiles (name, asset_class, enabled) VALUES (:n, :ac, 1)"
        ), {"n": name, "ac": asset_class})
        prof_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
        cap = capitals[i]
        db.execute(text("""
            INSERT INTO bot_allocations
                (user_id, profile_id, enabled, starting_capital_cents, inception_capital_cents)
            VALUES (:uid, :pid, 1, :cap, :cap)
        """), {"uid": 1, "pid": prof_id, "cap": cap})
        alloc_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
        alloc_ids.append((alloc_id, name))
    db.commit()
    return alloc_ids  # list of (alloc_id, bot_name)


def _make_healthy_bots():
    """Return 13 healthy bot dicts for compute_bot_diagnostics mock."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        {
            "bot_id": name,
            "verdict": "trading",
            "last_signal_at": now_str,
            "signals_24h": 5,
            "trades_24h": 2,
            "open_positions": 1,
            "last_trade_at": now_str,
            "enabled": True,
            "paused_reason": None,
            "asset_class_declared": "stock",
            "strategy_count": 1,
        }
        for name in BOT_NAMES
    ]


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Green state
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_green_state(monkeypatch):
    """13 enabled bots, $1M capital, 0 violations, ~50% deployment → GREEN."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        allocs = _seed_13_bots(db)

        # Seed open positions at ~50% deployment
        # 5 positions * (1 qty * 10_000_000 avg_cost_cents) = 50_000_000 cents = 50%
        for alloc_id, _ in allocs[:5]:
            db.execute(text("""
                INSERT INTO bot_positions
                    (allocation_id, symbol, qty, avg_cost_cents, side, opened_at)
                VALUES (:aid, 'AAPL', 1.0, 10000000, 'long', datetime('now', '-2 hours'))
            """), {"aid": alloc_id})
        db.commit()

        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())

        result = m["run_daily_audit"](db)

        assert result["overall_status"] == "GREEN", (
            f"Expected GREEN, got {result['overall_status']}. alerts={result['alerts']}"
        )
        assert len(result["alerts"]) == 0, f"Expected 0 alerts, got: {result['alerts']}"
        assert len(result["checks"]) == 8
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Capital drift → RED
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_red_on_capital_drift():
    """Bots summing to less than $1M (drift) → RED with capital invariant alert."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        # Seed 13 bots with $999,000 total instead of $1,000,000
        _seed_13_bots(db, capital_per_bot=99_900_000 // 13)

        result = m["run_daily_audit"](db)

        assert result["overall_status"] == "RED", (
            f"Expected RED, got {result['overall_status']}"
        )
        alert_text = " ".join(result["alerts"]).lower()
        assert "capital invariant" in alert_text or "capital" in alert_text, (
            f"Expected 'capital invariant' in alerts, got: {result['alerts']}"
        )
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Options format regression → RED
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_red_on_options_format_regression(monkeypatch):
    """options_directional trade with equity symbol (SPY) → RED with OCC alert."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        allocs = _seed_13_bots(db)

        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())

        # Find the options_directional allocation
        opts_alloc_id = None
        for alloc_id, bot_name in allocs:
            if bot_name == "options_directional":
                opts_alloc_id = alloc_id
                break

        assert opts_alloc_id is not None

        # Insert an equity-format trade (fails OCC regex) within last 24h
        db.execute(text("""
            INSERT INTO bot_trades (allocation_id, symbol, side, qty, fill_price_cents, ts)
            VALUES (:aid, 'SPY', 'buy', 1.0, 40000, datetime('now', '-1 hour'))
        """), {"aid": opts_alloc_id})
        db.commit()

        result = m["run_daily_audit"](db)

        assert result["overall_status"] == "RED", (
            f"Expected RED, got {result['overall_status']}"
        )
        alert_text = " ".join(result["alerts"]).lower()
        assert "occ" in alert_text or "options" in alert_text, (
            f"Expected OCC/options in alerts, got: {result['alerts']}"
        )
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Crypto-equity violation → RED
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_red_on_crypto_equity_violation(monkeypatch):
    """Mock compute_migration_status to return a crypto-bot equity violation → RED."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        _seed_13_bots(db)

        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())
        monkeypatch.setattr(
            m["admin_mod"],
            "compute_migration_status",
            lambda db: {
                "crypto_bot_equity_violations": [
                    {"bot_id": "crypto_onchain", "symbol": "SPY"}
                ]
            },
        )

        result = m["run_daily_audit"](db)

        assert result["overall_status"] == "RED", (
            f"Expected RED, got {result['overall_status']}"
        )
        viol_check = next(
            (c for c in result["checks"] if c["name"] == "crypto_equity_violations"),
            None,
        )
        assert viol_check is not None
        assert viol_check["status"] == "ALERT"
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Low deployment → YELLOW
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_yellow_on_low_deployment(monkeypatch):
    """$20M notional in open positions (~20% deployment, <30% threshold) → YELLOW."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        allocs = _seed_13_bots(db)

        # 2 positions * 1 qty * 10_000_000 avg_cost_cents = 20_000_000 cents = 20%
        for alloc_id, _ in allocs[:2]:
            db.execute(text("""
                INSERT INTO bot_positions
                    (allocation_id, symbol, qty, avg_cost_cents, side, opened_at)
                VALUES (:aid, 'AAPL', 1.0, 10000000, 'long', datetime('now', '-1 hour'))
            """), {"aid": alloc_id})
        db.commit()

        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())

        result = m["run_daily_audit"](db)

        assert result["overall_status"] == "YELLOW", (
            f"Expected YELLOW, got {result['overall_status']}. alerts={result['alerts']}"
        )
        deploy_check = next(
            (c for c in result["checks"] if c["name"] == "fund_deployment"),
            None,
        )
        assert deploy_check is not None
        assert deploy_check["status"] == "WARN", f"fund_deployment status: {deploy_check}"
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: Silent bot → RED (spec 1.2: no_signals >7d is ALERT)
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_red_on_silent_bot(monkeypatch):
    """Mock compute_bot_diagnostics to return a bot silent 8d → RED."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        _seed_13_bots(db)

        eight_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fake_bots = [
            {
                "bot_id": "stock_swing",
                "verdict": "no_signals",
                "last_signal_at": eight_days_ago,
                "signals_24h": 0, "trades_24h": 0, "open_positions": 0,
                "last_trade_at": None, "enabled": True, "paused_reason": None,
                "asset_class_declared": "stock", "strategy_count": 1,
            }
        ] + [
            {
                "bot_id": f"other_bot_{i}",
                "verdict": "trading",
                "last_signal_at": now_str,
                "signals_24h": 5, "trades_24h": 2, "open_positions": 1,
                "last_trade_at": now_str, "enabled": True, "paused_reason": None,
                "asset_class_declared": "stock", "strategy_count": 1,
            }
            for i in range(12)
        ]

        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: fake_bots)

        result = m["run_daily_audit"](db)

        assert result["overall_status"] == "RED", (
            f"Expected RED (silent bot >7d is ALERT per spec 1.2), "
            f"got {result['overall_status']}. alerts={result['alerts']}"
        )
        alert_text = " ".join(result["alerts"])
        assert "stock_swing" in alert_text, (
            f"Expected stock_swing in alerts, got: {result['alerts']}"
        )
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Persist to DB
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_persists_to_db(monkeypatch):
    """run_daily_audit writes exactly 1 row to daily_audit_log with 8 checks."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        _seed_13_bots(db)
        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())

        m["run_daily_audit"](db)

        count = db.execute(text("SELECT COUNT(*) FROM daily_audit_log")).scalar()
        assert count == 1, f"Expected 1 row in daily_audit_log, got {count}"

        row = db.execute(text(
            "SELECT overall_status, checks_json FROM daily_audit_log ORDER BY id DESC LIMIT 1"
        )).fetchone()
        assert row is not None
        checks = json.loads(row[1])
        assert len(checks) == 8, f"Expected 8 checks in checks_json, got {len(checks)}"
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8: GET /api/admin/daily-audit/latest returns most recent row
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_endpoint_returns_latest(monkeypatch):
    """Run audit twice, GET latest → most recent row (by id DESC)."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        _seed_13_bots(db)
        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())

        m["run_daily_audit"](db)
        m["run_daily_audit"](db)

        response = m["get_daily_audit_latest"](db=db, current_user=_mock_user())

        count = db.execute(text("SELECT COUNT(*) FROM daily_audit_log")).scalar()
        assert count == 2

        max_id = db.execute(text("SELECT MAX(id) FROM daily_audit_log")).scalar()
        assert response.get("id") == max_id, (
            f"Expected latest id={max_id}, got id={response.get('id')}"
        )
        assert "as_of" in response
        assert "overall_status" in response
        assert isinstance(response.get("checks"), list)
        assert isinstance(response.get("alerts"), list)
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9: POST /api/admin/daily-audit/run-now
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_endpoint_run_now(monkeypatch):
    """POST run-now returns correct keys and 8 checks; inserts a DB row."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        _seed_13_bots(db)
        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())

        result = m["post_daily_audit_run_now"](db=db, current_user=_mock_user())

        expected_keys = {"as_of", "overall_status", "checks", "alerts", "summary_markdown"}
        assert expected_keys.issubset(set(result.keys())), (
            f"Missing keys: {expected_keys - set(result.keys())}"
        )
        assert len(result["checks"]) == 8, f"Expected 8 checks, got {len(result['checks'])}"

        count = db.execute(text("SELECT COUNT(*) FROM daily_audit_log")).scalar()
        assert count == 1, f"Expected 1 daily_audit_log row, got {count}"
    finally:
        restore()
        db.close()
        engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10: Scheduler wired (substring check on bot_scheduler.py source)
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_scheduler_wired():
    """bot_scheduler.py contains daily_strategy_lab_audit job with correct cron."""
    scheduler_path = BACKEND_ROOT / "strategy_lab" / "bot_scheduler.py"
    src = scheduler_path.read_text()

    assert "daily_strategy_lab_audit" in src, (
        "bot_scheduler.py must contain job id 'daily_strategy_lab_audit'"
    )
    assert "hour=4" in src, (
        "bot_scheduler.py must set hour=4 for daily_strategy_lab_audit"
    )
    assert "minute=30" in src, (
        "bot_scheduler.py must set minute=30 for daily_strategy_lab_audit"
    )
    # Must appear after the 04:00 UTC daily_journal_nightly job
    journal_idx = src.find("daily_journal_nightly")
    audit_idx = src.find("daily_strategy_lab_audit")
    assert audit_idx > journal_idx, (
        "daily_strategy_lab_audit job must be registered AFTER daily_journal_nightly"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11: Discord missing webhook — no exception, row still persisted
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_discord_post_handles_missing_webhook(monkeypatch):
    """With DISCORD_WH_DAILY_AUDIT unset, audit completes + persists to DB."""
    restore, m = _load_real_modules()
    db, engine = _make_db()
    try:
        _seed_13_bots(db)
        monkeypatch.setattr(m["admin_mod"], "compute_bot_diagnostics",
                            lambda db, user_id=1: _make_healthy_bots())
        monkeypatch.delenv("DISCORD_WH_DAILY_AUDIT", raising=False)

        result = m["run_daily_audit"](db)

        assert result is not None
        assert "overall_status" in result

        count = db.execute(text("SELECT COUNT(*) FROM daily_audit_log")).scalar()
        assert count == 1, f"Expected 1 row in daily_audit_log, got {count}"
    finally:
        restore()
        db.close()
        engine.dispose()
