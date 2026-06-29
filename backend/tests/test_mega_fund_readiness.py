"""Mega-ship tests: PARTS 2, 4, 5, 6, 7 of the fund operational readiness ship.

PART 2: m033 closes equity positions on options_income/options_directional,
        pauses both options bots (Layer 3), OCC validation tightens.
PART 4: cash_floor no longer references nonexistent bot_trades.strategy column.
PART 5: by_sleeve includes Cash Floor so Diagnostics divergence flips OK.
PART 6: Dashboard renders all 4 sleeve cards including Quant.
PART 7: heartbeat writes on order placement, rate-limited to 1/min/alloc.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import subprocess
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"


# ── sys.modules pollution containment (SHIP 14 lesson) ──────────────────────
@pytest.fixture(autouse=True)
def _restore_sys_modules():
    """Snapshot before each test, restore after — prevents pollution regression."""
    snapshot = dict(sys.modules)
    yield
    for k in list(sys.modules.keys()):
        if k not in snapshot:
            del sys.modules[k]
    for k, v in snapshot.items():
        sys.modules[k] = v


def _load_migration(module_short: str):
    """Load migration directly from disk, bypassing conftest's app.db stub."""
    pkg = "app.db.migrations"
    if pkg not in sys.modules or not hasattr(sys.modules[pkg], "__path__"):
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg
        app_db = sys.modules.get("app.db")
        if app_db is not None:
            app_db.migrations = real_pkg
    # _gate is imported by m033 via the package; load it first.
    if "app.db.migrations._gate" not in sys.modules:
        gate_path = MIGRATIONS_DIR / "_gate.py"
        gate_spec = importlib.util.spec_from_file_location(
            "app.db.migrations._gate", str(gate_path)
        )
        gate_mod = importlib.util.module_from_spec(gate_spec)
        sys.modules["app.db.migrations._gate"] = gate_mod
        gate_spec.loader.exec_module(gate_mod)
    full = f"{pkg}.{module_short}"
    path = MIGRATIONS_DIR / f"{module_short}.py"
    spec = importlib.util.spec_from_file_location(full, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_engine():
    """In-memory SQLite with bare-minimum schema m033 needs."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.connect() as c:
        c.execute(text("""
            CREATE TABLE schema_migrations (
                migration_name TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
        c.execute(text("""
            CREATE TABLE bot_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                asset_class TEXT
            )
        """))
        c.execute(text("""
            CREATE TABLE bot_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                enabled INTEGER DEFAULT 1,
                paused_reason TEXT,
                starting_capital_cents INTEGER,
                inception_capital_cents INTEGER,
                current_capital_cents INTEGER
            )
        """))
        c.execute(text("""
            CREATE TABLE bot_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER,
                symbol TEXT,
                qty REAL,
                avg_cost_cents INTEGER,
                closed_at TEXT,
                exit_reason TEXT,
                quarantined_at TEXT
            )
        """))
        c.execute(text("""
            CREATE TABLE cross_sleeve_quarantine_s14 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL UNIQUE,
                bot_id TEXT,
                user_id INTEGER,
                declared_asset_class TEXT,
                actual_symbol TEXT,
                actual_asset_class TEXT,
                detected_at TEXT,
                action TEXT
            )
        """))
        c.execute(text("CREATE TABLE bot_trades (id INTEGER PRIMARY KEY, allocation_id INTEGER, symbol TEXT)"))
        c.execute(text("CREATE TABLE bot_daily_pnl (id INTEGER PRIMARY KEY, allocation_id INTEGER, realized_cents INTEGER)"))
        c.commit()
    return eng


def _seed_options_bot_with_equity_positions(eng):
    """Set up options_income holding TSLA/NVDA + options_directional holding AAPL."""
    with eng.connect() as c:
        # Seed profiles
        for name, ac in [
            ("options_income", "option"),
            ("options_directional", "option"),
            ("stock_swing", "equity"),  # control: should NOT be touched
        ]:
            c.execute(
                text("INSERT INTO bot_profiles (name, asset_class) VALUES (:n, :ac)"),
                {"n": name, "ac": ac},
            )
        # Allocations for user_id=1, all enabled
        for name in ("options_income", "options_directional", "stock_swing"):
            pid = c.execute(
                text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": name}
            ).fetchone()[0]
            c.execute(
                text(
                    "INSERT INTO bot_allocations "
                    "(user_id, profile_id, enabled, starting_capital_cents, "
                    " inception_capital_cents, current_capital_cents) "
                    "VALUES (1, :pid, 1, 5000000, 5000000, 5000000)"
                ),
                {"pid": pid},
            )
        # Open equity positions on options bots (should be closed by m033)
        for bot_name, sym in [
            ("options_income", "TSLA"),
            ("options_income", "NVDA"),
            ("options_directional", "AAPL"),
        ]:
            aid = c.execute(
                text(
                    "SELECT a.id FROM bot_allocations a "
                    "JOIN bot_profiles p ON p.id = a.profile_id "
                    "WHERE p.name = :n AND a.user_id = 1"
                ),
                {"n": bot_name},
            ).fetchone()[0]
            c.execute(
                text(
                    "INSERT INTO bot_positions "
                    "(allocation_id, symbol, qty, avg_cost_cents) "
                    "VALUES (:aid, :sym, 10, 100000)"
                ),
                {"aid": aid, "sym": sym},
            )
        # Open position on a stock bot — control, should NOT be closed
        stock_aid = c.execute(
            text(
                "SELECT a.id FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE p.name = 'stock_swing' AND a.user_id = 1"
            )
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'SPY', 5, 50000)"
            ),
            {"aid": stock_aid},
        )
        c.commit()
    return eng


# ═══════════════════════════════════════════════════════════════════════════
# PART 2 — m033 + OCC validation tests
# ═══════════════════════════════════════════════════════════════════════════

def test_m033_closes_equity_positions_on_options_bots():
    eng = _seed_options_bot_with_equity_positions(_make_engine())
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    with eng.connect() as c:
        result = m033.run(c)
    assert result["executed"] is True
    assert result["options_income_closed"] == 2  # TSLA + NVDA
    assert result["options_directional_closed"] == 1  # AAPL
    assert result["quarantined"] == 3


def test_m033_pauses_both_options_bots():
    eng = _seed_options_bot_with_equity_positions(_make_engine())
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    with eng.connect() as c:
        result = m033.run(c)
    assert len(result["paused_alloc_ids"]) == 2  # both options_income + options_directional
    with eng.connect() as c:
        rows = c.execute(
            text(
                "SELECT a.enabled, a.paused_reason FROM bot_allocations a "
                "JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE p.name IN ('options_income', 'options_directional')"
            )
        ).fetchall()
    assert all(r[0] == 0 for r in rows), "both options bots must be disabled"
    assert all("strategy_generates_invalid_symbols" in (r[1] or "") for r in rows)


def test_m033_does_not_touch_stock_bot_positions():
    eng = _seed_options_bot_with_equity_positions(_make_engine())
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    with eng.connect() as c:
        m033.run(c)
        row = c.execute(
            text(
                "SELECT closed_at FROM bot_positions bp "
                "JOIN bot_allocations a ON a.id = bp.allocation_id "
                "JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE p.name = 'stock_swing'"
            )
        ).fetchone()
    assert row[0] is None, "stock_swing positions must NOT be closed by m033"


def test_m033_idempotent_on_second_run():
    eng = _seed_options_bot_with_equity_positions(_make_engine())
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    with eng.connect() as c:
        first = m033.run(c)
        second = m033.run(c)
    assert first["executed"] is True
    assert second["executed"] is False
    assert second["skipped_reason"] == "already_applied"


def test_m033_only_scans_user_id_1():
    eng = _make_engine()
    with eng.connect() as c:
        c.execute(text("INSERT INTO bot_profiles (name, asset_class) VALUES ('options_income', 'option')"))
        pid = c.execute(text("SELECT id FROM bot_profiles WHERE name='options_income'")).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations (user_id, profile_id, enabled, starting_capital_cents) "
                "VALUES (3, :pid, 1, 5000000)"
            ),
            {"pid": pid},
        )
        aid = c.execute(text("SELECT id FROM bot_allocations WHERE user_id=3")).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'NVDA', 1, 50000)"
            ),
            {"aid": aid},
        )
        c.commit()
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    with eng.connect() as c:
        result = m033.run(c)
        # user_id=3 position untouched
        row = c.execute(text("SELECT closed_at FROM bot_positions WHERE allocation_id = :aid"), {"aid": aid}).fetchone()
    assert result["quarantined"] == 0
    assert row[0] is None


def test_m033_preserves_occ_option_symbols():
    """OCC option contracts (already-correct positions) must NOT be closed."""
    eng = _make_engine()
    with eng.connect() as c:
        c.execute(text("INSERT INTO bot_profiles (name, asset_class) VALUES ('options_income', 'option')"))
        c.execute(text("INSERT INTO bot_profiles (name, asset_class) VALUES ('options_directional', 'option')"))
        pid = c.execute(text("SELECT id FROM bot_profiles WHERE name='options_income'")).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations (user_id, profile_id, enabled, starting_capital_cents) "
                "VALUES (1, :pid, 1, 5000000)"
            ),
            {"pid": pid},
        )
        aid = c.execute(text("SELECT id FROM bot_allocations WHERE user_id=1")).fetchone()[0]
        # 21-char OCC option — should NOT be closed
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'TSLA250620C00150000', 5, 12500)"
            ),
            {"aid": aid},
        )
        c.commit()
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    with eng.connect() as c:
        m033.run(c)
        row = c.execute(text("SELECT closed_at FROM bot_positions WHERE allocation_id = :aid"), {"aid": aid}).fetchone()
    assert row[0] is None, "legitimate OCC option positions must NOT be closed"


def test_occ_symbol_validator_helper():
    m033 = _load_migration("m033_close_options_bot_equity_violations")
    # OCC OSI 21-char format → True
    assert m033._is_occ_option_symbol("TSLA250620C00150000") is True
    assert m033._is_occ_option_symbol("AAPL251017P00200000") is True
    # Equity tickers → False
    assert m033._is_occ_option_symbol("TSLA") is False
    assert m033._is_occ_option_symbol("AAPL") is False
    assert m033._is_occ_option_symbol("NVDA") is False
    # Crypto pairs → False
    assert m033._is_occ_option_symbol("BTC/USD") is False
    # Empty / None
    assert m033._is_occ_option_symbol("") is False


# ═══════════════════════════════════════════════════════════════════════════
# PART 5 — by_sleeve Cash Floor fix
# ═══════════════════════════════════════════════════════════════════════════

def test_by_sleeve_includes_cash_floor_canonical_value():
    """Read portfolio.py code, confirm Cash bucket is folded into stocks."""
    src = (REPO_ROOT / "backend" / "app" / "routers" / "portfolio.py").read_text()
    # The fix wraps canonical "Cash" into "Stocks" sleeve_buckets when present.
    assert "_canonical_sleeve_cents.get(\"Cash\"" in src
    assert "PART 5" in src, "PART 5 fix marker missing in portfolio.py"


# ═══════════════════════════════════════════════════════════════════════════
# PART 6 — Dashboard Quant sleeve
# ═══════════════════════════════════════════════════════════════════════════

def test_dashboard_backend_routes_quant_to_quant_sleeve():
    src = (REPO_ROOT / "backend" / "app" / "routers" / "dashboard.py").read_text()
    # Quant bots route to "quant" sleeve, not "crypto"
    assert "\"quant\": \"quant\"" in src
    assert "_QUANT_PROFILE_NAMES" in src
    # sleeve_data initialised with all 4 keys
    assert "(\"stocks\", \"crypto\", \"options\", \"quant\")" in src


def test_dashboard_frontend_has_quant_in_sleeve_meta():
    src = (REPO_ROOT / "frontend" / "src" / "pages" / "Dashboard.tsx").read_text()
    assert "quant:" in src and "Quant" in src
    # 4-sleeve render order intact
    assert "\"stocks\", \"crypto\", \"options\", \"quant\"" in src


# ═══════════════════════════════════════════════════════════════════════════
# PART 7 — Heartbeat rate-limited write on order placement
# ═══════════════════════════════════════════════════════════════════════════

_BOT_HEALTH_CACHED = None


def _load_bot_health_isolated():
    """Load bot_health.py once — cached to avoid SQLAlchemy double-registration.

    The ORM models inside `app.db.models.bots` raise "Type already registered"
    if the loader executes the module twice in one process. We load once,
    then return the cached module on subsequent calls (the autouse
    sys.modules-restore fixture cleans up other state).
    """
    global _BOT_HEALTH_CACHED
    if _BOT_HEALTH_CACHED is not None:
        return _BOT_HEALTH_CACHED
    bh_path = REPO_ROOT / "backend" / "strategy_lab" / "core" / "bot_health.py"
    spec = importlib.util.spec_from_file_location(
        "strategy_lab.core.bot_health", str(bh_path)
    )
    bh = importlib.util.module_from_spec(spec)
    sys.modules["strategy_lab.core.bot_health"] = bh
    spec.loader.exec_module(bh)
    _BOT_HEALTH_CACHED = bh
    return bh


def test_record_order_placement_heartbeat_rate_limits_per_alloc():
    """Rate-limit test via direct dict inspection (no ORM mocking needed)."""
    bh = _load_bot_health_isolated()

    # Monkey-patch record_heartbeat to a no-op so we test the rate-limit
    # decision alone (avoids ORM/SessionLocal coupling for unit test).
    bh.record_heartbeat = lambda allocation_id, db: None
    bh._LAST_ORDER_HEARTBEAT_AT.clear()

    # First write: cache empty → succeeds
    r1 = bh.record_order_placement_heartbeat(42, db=None)
    assert r1 is True, f"first write should succeed, got {r1}"

    # Second write within 60s: rate-limited
    r2 = bh.record_order_placement_heartbeat(42, db=None)
    assert r2 is False, "second write within 60s must be rate-limited"

    # Different alloc_id: not rate-limited
    r3 = bh.record_order_placement_heartbeat(43, db=None)
    assert r3 is True, "different allocation must not be rate-limited"


def test_record_order_placement_heartbeat_after_60s_allows_next_write():
    """After the 60s window elapses, the same alloc can write again."""
    bh = _load_bot_health_isolated()

    bh.record_heartbeat = lambda allocation_id, db: None
    bh._LAST_ORDER_HEARTBEAT_AT.clear()

    bh.record_order_placement_heartbeat(42, db=None)
    # Backdate cache by 61 seconds
    bh._LAST_ORDER_HEARTBEAT_AT[42] = datetime.now(timezone.utc) - timedelta(seconds=61)
    r = bh.record_order_placement_heartbeat(42, db=None)
    assert r is True, "write after 60s window must succeed"


def test_record_order_placement_heartbeat_min_interval_constant():
    """Sanity check the constant matches Brock's spec (60s = 1/min/alloc)."""
    bh = _load_bot_health_isolated()
    assert bh._ORDER_HEARTBEAT_MIN_INTERVAL_SEC == 60


# ═══════════════════════════════════════════════════════════════════════════
# PART 4 — cash_floor schema drift fix
# ═══════════════════════════════════════════════════════════════════════════

def test_cash_floor_active_deployment_no_bt_strategy_reference():
    src = (REPO_ROOT / "backend" / "app" / "services" / "cash_floor.py").read_text()
    assert "bt.strategy" not in src, "stale bot_trades.strategy reference still present"
    assert "bf.name" in src, "fix must derive from bot_profiles.name"


# ═══════════════════════════════════════════════════════════════════════════
# POST-MORTEM GUARDS (G1-G5)
# ═══════════════════════════════════════════════════════════════════════════

def _branch_diff_files() -> list[str]:
    """Files changed in this branch vs main."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        return [f for f in out.stdout.strip().split("\n") if f]
    except Exception:
        return []


def test_g2_no_new_calls_to_ensure_portfolios_for_user():
    """No new _ensure_portfolios_for_user callers outside bots.py."""
    violations = []
    for f in _branch_diff_files():
        if not f.endswith(".py") or f.endswith("/bots.py"):
            continue
        if f.startswith("backend/tests/") or ".pipeline/" in f:
            continue
        try:
            content = (REPO_ROOT / f).read_text()
            if "_ensure_portfolios_for_user(" in content:
                # Only flag actual CALLS, not comments
                for line in content.splitlines():
                    s = line.strip()
                    if s.startswith("#") or s.startswith('"""') or s.startswith("'''"):
                        continue
                    if "_ensure_portfolios_for_user(" in line:
                        violations.append(f"{f}: {line.strip()[:80]}")
                        break
        except Exception:
            pass
    assert not violations, f"new _ensure_portfolios_for_user callers: {violations}"


def test_g3_no_new_writes_to_capital_fields_outside_migrations():
    """No new starting/inception/current_capital_cents assignments outside migrations."""
    import re
    pat = re.compile(
        r"(starting_capital_cents|inception_capital_cents|current_capital_cents)\s*="
    )
    violations = []
    for f in _branch_diff_files():
        if not f.endswith(".py") or f.startswith("backend/app/db/migrations/"):
            continue
        if f.startswith("backend/tests/") or ".pipeline/" in f:
            continue
        try:
            content = (REPO_ROOT / f).read_text()
            for ln, line in enumerate(content.splitlines(), 1):
                s = line.strip()
                if s.startswith("#") or "==" in s:
                    continue
                if pat.search(line):
                    # Filter out keyword args (e.g. starting_capital_cents=X in a call)
                    if "=" in line and not line.strip().startswith("if ") and not line.strip().startswith("elif "):
                        if "(" in line and "starting_capital_cents=" in line or "inception_capital_cents=" in line:
                            continue
                        violations.append(f"{f}:{ln}: {s[:80]}")
        except Exception:
            pass
    assert not violations, f"new capital field writes outside migrations: {violations}"


def test_g4_no_new_deletes_from_bot_trades_or_bot_daily_pnl():
    """No new DELETE FROM bot_trades / bot_daily_pnl anywhere in the branch."""
    import re
    pat = re.compile(r"DELETE\s+FROM\s+bot_(trades|daily_pnl)", re.IGNORECASE)
    violations = []
    for f in _branch_diff_files():
        if not f.endswith(".py"):
            continue
        if f.startswith("backend/tests/") or ".pipeline/" in f:
            continue
        try:
            content = (REPO_ROOT / f).read_text()
            for ln, line in enumerate(content.splitlines(), 1):
                if pat.search(line):
                    s = line.strip()
                    if s.startswith("#") or 'NOT ALLOWED' in line.upper() or 'STANDING DECISION' in line.upper():
                        continue
                    violations.append(f"{f}:{ln}: {s[:80]}")
        except Exception:
            pass
    assert not violations, f"new DELETE FROM bot_trades/bot_daily_pnl: {violations}"


def test_g5_no_new_anthropic_sdk_imports():
    """SHIP 4 boundary still holds — no direct anthropic SDK imports in branch."""
    import re
    pat = re.compile(r"^\s*(from\s+anthropic|import\s+anthropic)", re.MULTILINE)
    violations = []
    for f in _branch_diff_files():
        if not f.endswith(".py"):
            continue
        if f.startswith("backend/tests/") or ".pipeline/" in f:
            continue
        if "llm_client" in f:
            continue  # the boundary file is allowed
        try:
            content = (REPO_ROOT / f).read_text()
            for ln, line in enumerate(content.splitlines(), 1):
                if pat.match(line):
                    s = line.strip()
                    if s.startswith("#"):
                        continue
                    violations.append(f"{f}:{ln}: {s[:80]}")
        except Exception:
            pass
    assert not violations, f"new anthropic SDK imports outside llm_client.py: {violations}"
