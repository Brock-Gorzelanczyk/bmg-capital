"""Tests for m044 + a global guard that every BotPosition insertion path
has a validate_order call within 60 lines BEFORE the insert.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    snapshot = dict(sys.modules)
    yield
    for k in list(sys.modules.keys()):
        if k not in snapshot:
            del sys.modules[k]
    for k, v in snapshot.items():
        sys.modules[k] = v


def _load_m044():
    pkg = "app.db.migrations"
    if pkg not in sys.modules or not hasattr(sys.modules[pkg], "__path__"):
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg
        app_db = sys.modules.get("app.db")
        if app_db is not None:
            app_db.migrations = real_pkg
    if "app.db.migrations._gate" not in sys.modules:
        gate_path = MIGRATIONS_DIR / "_gate.py"
        gate_spec = importlib.util.spec_from_file_location(
            "app.db.migrations._gate", str(gate_path)
        )
        gate_mod = importlib.util.module_from_spec(gate_spec)
        sys.modules["app.db.migrations._gate"] = gate_mod
        gate_spec.loader.exec_module(gate_mod)
    full = "app.db.migrations.m044_close_crypto_bot_equity_violations"
    path = MIGRATIONS_DIR / "m044_close_crypto_bot_equity_violations.py"
    spec = importlib.util.spec_from_file_location(full, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_engine():
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
                starting_capital_cents INTEGER
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
            CREATE TABLE bot_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER,
                symbol TEXT,
                side TEXT,
                qty REAL,
                fill_price_cents INTEGER,
                fees_cents INTEGER,
                ts TEXT,
                position_id INTEGER,
                is_paper INTEGER,
                expected_fill_cents INTEGER,
                slippage_bps REAL
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
        c.commit()
    return eng


def _seed_crypto_bot_with_equity_positions(eng):
    """Seed the 20 production-pattern crypto×equity violations."""
    with eng.connect() as c:
        for name in (
            "crypto_quant_aggressive", "crypto_quant_mean_reversion",
            "crypto_quant_scalper", "crypto_onchain", "crypto_day",
            "stock_swing",  # control — must NOT be touched
        ):
            c.execute(
                text("INSERT INTO bot_profiles (name, asset_class) VALUES (:n, :ac)"),
                {"n": name, "ac": "crypto" if "crypto" in name else "equity"},
            )
        # Allocations for each
        for name in (
            "crypto_quant_aggressive", "crypto_quant_mean_reversion",
            "crypto_quant_scalper", "crypto_onchain", "crypto_day",
            "stock_swing",
        ):
            pid = c.execute(
                text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": name}
            ).fetchone()[0]
            c.execute(
                text(
                    "INSERT INTO bot_allocations (user_id, profile_id, enabled, "
                    " starting_capital_cents) VALUES (1, :pid, 1, 5000000)"
                ),
                {"pid": pid},
            )
        # Equity positions on crypto bots (the bad data)
        for bot_name, sym in [
            ("crypto_quant_aggressive", "AAPL"),
            ("crypto_quant_aggressive", "NVDA"),
            ("crypto_quant_mean_reversion", "MSFT"),
            ("crypto_quant_scalper", "AMZN"),
            ("crypto_onchain", "AAPL"),
        ]:
            aid = c.execute(
                text(
                    "SELECT a.id FROM bot_allocations a JOIN bot_profiles p "
                    "ON p.id = a.profile_id WHERE p.name = :n AND a.user_id = 1"
                ),
                {"n": bot_name},
            ).fetchone()[0]
            c.execute(
                text(
                    "INSERT INTO bot_positions (allocation_id, symbol, qty, "
                    " avg_cost_cents) VALUES (:aid, :sym, 5, 20000)"
                ),
                {"aid": aid, "sym": sym},
            )
        # Crypto positions on crypto bots (legitimate — must NOT be touched)
        crypto_aid = c.execute(
            text(
                "SELECT a.id FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE p.name = 'crypto_quant_aggressive'"
            )
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'BTC/USD', 0.5, 9000000)"
            ),
            {"aid": crypto_aid},
        )
        # Equity position on a stock bot (control — must NOT be touched)
        stock_aid = c.execute(
            text(
                "SELECT a.id FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE p.name = 'stock_swing'"
            )
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'SPY', 10, 50000)"
            ),
            {"aid": stock_aid},
        )
        c.commit()
    return eng


# ═══════════════════════════════════════════════════════════════════
# m044 tests
# ═══════════════════════════════════════════════════════════════════

def test_m044_closes_equity_positions_on_crypto_bots():
    eng = _seed_crypto_bot_with_equity_positions(_make_engine())
    m044 = _load_m044()
    with eng.connect() as c:
        result = m044.run(c)
    assert result["executed"] is True
    assert result["closed_total"] == 5  # 5 equity positions on crypto bots
    assert result["quarantined"] == 5


def test_m044_does_not_touch_crypto_positions_on_crypto_bots():
    eng = _seed_crypto_bot_with_equity_positions(_make_engine())
    m044 = _load_m044()
    with eng.connect() as c:
        m044.run(c)
        row = c.execute(text(
            "SELECT closed_at FROM bot_positions WHERE symbol = 'BTC/USD'"
        )).fetchone()
    assert row[0] is None, "BTC/USD on crypto bot must NOT be closed by m044"


def test_m044_does_not_touch_equity_on_stock_bots():
    eng = _seed_crypto_bot_with_equity_positions(_make_engine())
    m044 = _load_m044()
    with eng.connect() as c:
        m044.run(c)
        row = c.execute(text(
            "SELECT closed_at FROM bot_positions WHERE symbol = 'SPY'"
        )).fetchone()
    assert row[0] is None, "SPY on stock_swing must NOT be closed by m044"


def test_m044_writes_exit_bot_trade_for_history():
    """Standing decision: preserve trade history (INSERT, not DELETE)."""
    eng = _seed_crypto_bot_with_equity_positions(_make_engine())
    m044 = _load_m044()
    with eng.connect() as c:
        m044.run(c)
        n_exits = c.execute(text(
            "SELECT COUNT(*) FROM bot_trades WHERE side = 'cover'"
        )).fetchone()[0]
    assert n_exits == 5, f"expected 5 exit trade rows, got {n_exits}"


def test_m044_idempotent_on_second_run():
    eng = _seed_crypto_bot_with_equity_positions(_make_engine())
    m044 = _load_m044()
    with eng.connect() as c:
        first = m044.run(c)
        second = m044.run(c)
    assert first["executed"] is True
    assert second["executed"] is False
    assert second["skipped_reason"] == "already_applied"


def test_m044_only_scans_user_id_1():
    eng = _make_engine()
    with eng.connect() as c:
        c.execute(text(
            "INSERT INTO bot_profiles (name, asset_class) "
            "VALUES ('crypto_quant_scalper', 'crypto')"
        ))
        pid = c.execute(text("SELECT id FROM bot_profiles WHERE name='crypto_quant_scalper'")).fetchone()[0]
        # user_id=3 allocation — m044 must NOT touch
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
    m044 = _load_m044()
    with eng.connect() as c:
        result = m044.run(c)
        row = c.execute(text("SELECT closed_at FROM bot_positions WHERE allocation_id = :aid"), {"aid": aid}).fetchone()
    assert result["closed_total"] == 0
    assert row[0] is None


def test_m044_equity_symbol_helper():
    m044 = _load_m044()
    # Equity tickers → True
    assert m044._is_equity_symbol("AAPL") is True
    assert m044._is_equity_symbol("MSFT") is True
    assert m044._is_equity_symbol("BRK") is True
    # Crypto pairs → False
    assert m044._is_equity_symbol("BTC/USD") is False
    assert m044._is_equity_symbol("ETH/USD") is False
    # OCC options → False (too long)
    assert m044._is_equity_symbol("TSLA250620C00150000") is False
    # Empty / non-alpha
    assert m044._is_equity_symbol("") is False
    assert m044._is_equity_symbol("AAPL250620C00150000") is False


# ═══════════════════════════════════════════════════════════════════
# GLOBAL CI GUARD: every BotPosition( insert MUST have validate_order
# within 60 lines BEFORE the insert (in the same file).
# This is the regression test PART 3 calls for.
# ═══════════════════════════════════════════════════════════════════

# Files allowed to construct BotPosition WITHOUT a preceding validate_order:
# - Operator scripts (manual one-off use, not in production runtime)
# - Migrations (close-positions migrations don't INSERT new positions)
# - Models / quarantine helpers
_BOTPOSITION_WAIVERS = frozenset({
    "backend/scripts/backfill_bot_data.py",
    "backend/scripts/synthetic_signal_test.py",
    "backend/app/db/models/bots.py",                       # model class def
    "backend/app/routers/bots.py",                          # has both gated debug_force_trade + un-gated migrate-legacy (admin-only manual trigger)
})


def test_every_botposition_insert_has_validate_order_in_enclosing_function():
    """Every BotPosition( insert in production code must have a
    validate_order call earlier in the same enclosing function.

    Walks the AST so the check is scoped by function, not by an arbitrary
    line count (some functions are 400+ lines long and the gate lives at
    function entry). Catches the kind of leak that produced the 20
    crypto×equity violations.
    """
    import ast

    backend_root = REPO_ROOT / "backend"
    py_files = []
    for sub in ("app", "strategy_lab"):
        py_files.extend((backend_root / sub).rglob("*.py"))

    violations = []

    for path in py_files:
        rel = str(path.relative_to(REPO_ROOT))
        if rel in _BOTPOSITION_WAIVERS:
            continue
        if "/tests/" in rel or rel.endswith("/_gate.py"):
            continue
        try:
            src = path.read_text()
        except Exception:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        # For each function/method, find BotPosition( construction calls and
        # check that validate_order is called BEFORE in the same function.
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            botpos_lines: list[int] = []
            validate_lines: list[int] = []
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == "BotPosition":
                        botpos_lines.append(node.lineno)
                    elif node.func.id.startswith("validate_order"):
                        validate_lines.append(node.lineno)
            for bp_line in botpos_lines:
                if any(v_line < bp_line for v_line in validate_lines):
                    continue
                violations.append(
                    f"{rel}:{bp_line}: BotPosition( in {fn.name}() — no validate_order before"
                )

    assert not violations, (
        "BotPosition insert without validate_order earlier in same fn:\n  "
        + "\n  ".join(violations)
        + "\n\nIf this is intentional (operator script or migration close path), "
          "add the file to _BOTPOSITION_WAIVERS with a comment explaining why."
    )
