"""Tests for m045_close_remaining_crypto_equity_violations.

Covers:
  1. Happy path — seeded user_id=1 + crypto_quant_aggressive + AAPL → closed.
  2. Multi-user safety — user_id=3 position IS closed (catches m044's bug).
  3. Idempotency — second run returns already_applied, no new writes.
  4. Clean DB — BTC/USD only → no_violations_found gate is recorded.
  5. Verify-fail — monkey-patched UPDATE → RuntimeError with "post-run verify".
  6. AST guard — SELECT must NOT contain "user_id = :uid" (m044 bug pattern).
  7. AST guard — main.py m045 wrapper uses engine.begin() not engine.connect().
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"
MAIN_PY = REPO_ROOT / "backend" / "app" / "main.py"
M045_PATH = MIGRATIONS_DIR / "m045_close_remaining_crypto_equity_violations.py"


# ---------------------------------------------------------------------------
# Module loader — follows the same pattern as test_m044_crypto_equity_close.py
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_sys_modules():
    snapshot = dict(sys.modules)
    yield
    for k in list(sys.modules.keys()):
        if k not in snapshot:
            del sys.modules[k]
    for k, v in snapshot.items():
        sys.modules[k] = v


def _load_m045():
    """Load m045 using importlib so it works without a full Django/FastAPI env."""
    pkg = "app.db.migrations"
    if pkg not in sys.modules or not hasattr(sys.modules.get(pkg, types.ModuleType(pkg)), "__path__"):
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg
        app_mod = sys.modules.get("app")
        if app_mod is not None:
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

    full_name = "app.db.migrations.m045_close_remaining_crypto_equity_violations"
    # Force reload each time so tests are isolated
    sys.modules.pop(full_name, None)
    spec = importlib.util.spec_from_file_location(full_name, str(M045_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# SQLite in-memory engine factory — matches m044 test pattern exactly
# ---------------------------------------------------------------------------

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
                exit_reason TEXT
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


def _seed_single_position(eng, *, user_id: int, bot_name: str, symbol: str):
    """Seed a minimal setup: one bot_profile, one allocation, one position."""
    with eng.connect() as c:
        c.execute(
            text("INSERT INTO bot_profiles (name, asset_class) VALUES (:n, 'crypto')"),
            {"n": bot_name},
        )
        pid = c.execute(
            text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": bot_name}
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations (user_id, profile_id, enabled, starting_capital_cents) "
                "VALUES (:uid, :pid, 1, 5000000)"
            ),
            {"uid": user_id, "pid": pid},
        )
        aid = c.execute(
            text("SELECT id FROM bot_allocations WHERE user_id = :uid AND profile_id = :pid"),
            {"uid": user_id, "pid": pid},
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, :sym, 5, 20000)"
            ),
            {"aid": aid, "sym": symbol},
        )
        c.commit()
    return eng


# ---------------------------------------------------------------------------
# TEST 1 — Happy path: user_id=1 + crypto_quant_aggressive + AAPL → closed
# ---------------------------------------------------------------------------

def test_happy_path_closes_equity_violation_user1():
    eng = _seed_single_position(
        _make_engine(),
        user_id=1,
        bot_name="crypto_quant_aggressive",
        symbol="AAPL",
    )
    m045 = _load_m045()

    with eng.begin() as conn:
        result = m045.run(conn)

    assert result["executed"] is True
    assert result["closed_total"] == 1
    assert result["quarantined"] == 1

    with eng.connect() as c:
        pos = c.execute(
            text("SELECT closed_at, exit_reason FROM bot_positions WHERE symbol = 'AAPL'")
        ).fetchone()
        assert pos[0] is not None, "closed_at must be set after m045 runs"
        assert pos[1] == "m045_cross_sleeve_violation"

        q_count = c.execute(
            text("SELECT COUNT(*) FROM cross_sleeve_quarantine_s14 WHERE action = 'm045_force_close'")
        ).fetchone()[0]
        assert q_count == 1

        t_count = c.execute(
            text("SELECT COUNT(*) FROM bot_trades WHERE side = 'cover'")
        ).fetchone()[0]
        assert t_count == 1

        gate = c.execute(
            text(
                "SELECT migration_name FROM schema_migrations "
                "WHERE migration_name = 'm045_close_remaining_crypto_equity_violations_2026_06'"
            )
        ).fetchone()
        assert gate is not None, "gate row must be recorded in schema_migrations"


# ---------------------------------------------------------------------------
# TEST 2 — Multi-user safety: user_id=3 position MUST still be closed
#           (this is the test that would have caught m044's bug)
# ---------------------------------------------------------------------------

def test_multi_user_safety_user_id_3_is_closed():
    """m044's bug: WHERE a.user_id = :uid with uid=1 silently skipped user_id=3.
    m045 drops that filter entirely. This test confirms user_id=3 positions
    are found and closed.
    """
    eng = _seed_single_position(
        _make_engine(),
        user_id=3,
        bot_name="crypto_quant_aggressive",
        symbol="AAPL",
    )
    m045 = _load_m045()

    with eng.begin() as conn:
        result = m045.run(conn)

    assert result["executed"] is True
    assert result["closed_total"] == 1, (
        "m045 must close the position even when user_id=3 (m044 missed this)"
    )
    assert result["users_touched"] == [3], (
        f"users_touched must be [3], got {result['users_touched']}"
    )

    with eng.connect() as c:
        pos = c.execute(
            text("SELECT closed_at FROM bot_positions WHERE symbol = 'AAPL'")
        ).fetchone()
        assert pos[0] is not None, "position must be closed for user_id=3"

        q_row = c.execute(
            text("SELECT user_id FROM cross_sleeve_quarantine_s14 WHERE action = 'm045_force_close'")
        ).fetchone()
        assert q_row is not None, "quarantine row must exist"
        assert q_row[0] == 3, f"quarantine row user_id must be 3, got {q_row[0]}"


# ---------------------------------------------------------------------------
# TEST 3 — Idempotency: second run returns already_applied, no new writes
# ---------------------------------------------------------------------------

def test_idempotency_second_run_is_no_op():
    eng = _seed_single_position(
        _make_engine(),
        user_id=1,
        bot_name="crypto_quant_aggressive",
        symbol="AAPL",
    )
    m045 = _load_m045()

    with eng.begin() as conn:
        first = m045.run(conn)

    with eng.begin() as conn:
        second = m045.run(conn)

    assert first["executed"] is True
    assert second == {"skipped_reason": "already_applied", "executed": False}, (
        f"Second run must return exactly the skipped shape, got: {second}"
    )

    with eng.connect() as c:
        q_count = c.execute(
            text("SELECT COUNT(*) FROM cross_sleeve_quarantine_s14")
        ).fetchone()[0]
        assert q_count == 1, "No duplicate quarantine rows on second run"

        t_count = c.execute(
            text("SELECT COUNT(*) FROM bot_trades WHERE side = 'cover'")
        ).fetchone()[0]
        assert t_count == 1, "No duplicate cover trades on second run"

        # closed_at must not have changed
        pos = c.execute(
            text("SELECT closed_at FROM bot_positions WHERE symbol = 'AAPL'")
        ).fetchone()
        assert pos[0] is not None, "Position must still be closed"


# ---------------------------------------------------------------------------
# TEST 4 — Clean DB: only BTC/USD position → no_violations_found + gate recorded
# ---------------------------------------------------------------------------

def test_clean_db_no_equity_violations_records_gate():
    """When only crypto pairs are present (no equity symbols), m045 must
    return no_violations_found AND still record the gate so it doesn't
    re-run on the next boot.
    """
    eng = _seed_single_position(
        _make_engine(),
        user_id=1,
        bot_name="crypto_quant_aggressive",
        symbol="BTC/USD",   # crypto pair — _is_equity_symbol returns False
    )
    m045 = _load_m045()

    with eng.begin() as conn:
        result = m045.run(conn)

    assert result["executed"] is True
    assert result["closed_total"] == 0
    assert result["skipped_reason"] == "no_violations_found"

    with eng.connect() as c:
        gate = c.execute(
            text(
                "SELECT migration_name FROM schema_migrations "
                "WHERE migration_name = 'm045_close_remaining_crypto_equity_violations_2026_06'"
            )
        ).fetchone()
        assert gate is not None, "gate must be recorded even when no violations found"

        # BTC/USD position must remain untouched
        pos = c.execute(
            text("SELECT closed_at FROM bot_positions WHERE symbol = 'BTC/USD'")
        ).fetchone()
        assert pos[0] is None, "BTC/USD position must remain open (not an equity)"


# ---------------------------------------------------------------------------
# TEST 5 — Verify-fail raises RuntimeError when UPDATE is a no-op
# ---------------------------------------------------------------------------

def test_verify_fail_raises_runtime_error():
    """If the UPDATE bot_positions is swallowed (no-op), the post-run verify
    SELECT will still find the open position and must raise RuntimeError.
    """
    eng = _seed_single_position(
        _make_engine(),
        user_id=1,
        bot_name="crypto_quant_aggressive",
        symbol="AAPL",
    )
    m045 = _load_m045()

    # Wrap conn.execute so that UPDATE bot_positions is silently dropped.
    # We need to intercept at the SQLAlchemy Connection level.
    original_run = m045.run

    def patched_run(conn):
        original_execute = conn.execute

        def no_op_update(stmt, params=None):
            sql_text = str(stmt)
            if "UPDATE bot_positions" in sql_text and "closed_at" in sql_text:
                # Return original execute result but don't actually update
                # Instead call with a WHERE clause that matches nothing
                from sqlalchemy import text as _text
                return original_execute(
                    _text("UPDATE bot_positions SET closed_at = :ts WHERE id = -999"),
                    {"ts": "2099-01-01"},
                )
            return original_execute(stmt, params)

        conn.execute = no_op_update
        return original_run(conn)

    with pytest.raises(RuntimeError, match="post-run verify"):
        with eng.begin() as conn:
            patched_run(conn)


# ---------------------------------------------------------------------------
# TEST 6 — AST guard: SELECT must NOT contain "user_id = :uid" (m044 bug)
# ---------------------------------------------------------------------------

def test_ast_guard_no_user_id_filter_in_m045_select():
    """Defense-in-depth: use the AST to inspect only SQL string literals in
    m045 and confirm that none contain "user_id = :uid" or "user_id=:uid".

    The m045 docstring legitimately mentions the m044 bug pattern
    ('m044 filtered WHERE a.user_id = :uid') as a comment — we must NOT
    flag that. We only care about actual SQL strings passed to text().
    """
    import ast as _ast

    source = M045_PATH.read_text()
    tree = _ast.parse(source)

    bug_pattern = re.compile(r"user_id\s*=\s*:uid")

    # Collect all string constants that appear as arguments to text() calls.
    # These are the only strings that become actual SQL.
    # We intentionally do NOT scan docstrings or comments — the m045 module
    # docstring legitimately quotes the m044 bug pattern as documentation.
    sql_strings: list[tuple[int, str]] = []
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Name)
            and node.func.id == "text"
        ):
            for arg in node.args:
                # In Python 3.8+ string constants are ast.Constant
                if isinstance(arg, _ast.Constant) and isinstance(arg.value, str):
                    sql_strings.append((arg.lineno, arg.value))
                # In Python 3.7 they may be ast.Str
                elif hasattr(_ast, "Str") and isinstance(arg, _ast.Str):
                    sql_strings.append((getattr(arg, "lineno", 0), arg.s))
                # JoinedStr / BinOp: walk the subtree for any Constant strings
                # that are concatenated together to form a SQL statement
                else:
                    for sub in _ast.walk(arg):
                        if isinstance(sub, _ast.Constant) and isinstance(sub.value, str):
                            sql_strings.append((getattr(sub, "lineno", 0), sub.value))

    violations = []
    for lineno, sql in sql_strings:
        if bug_pattern.search(sql):
            violations.append(f"  line {lineno}: {sql!r}")

    assert not violations, (
        "m045 SQL strings must NOT contain 'user_id = :uid' — that was m044's bug.\n"
        "Violations found:\n" + "\n".join(violations)
    )

    # Also ensure the hardening comment is present confirming intent
    assert "NOT filter" in source or "NO user_id filter" in source or "no user_id" in source.lower(), (
        "m045 source must contain a comment explaining that user_id filtering is intentionally absent"
    )


# ---------------------------------------------------------------------------
# TEST 7 — AST guard: main.py m045 wrapper uses engine.begin() not engine.connect()
# ---------------------------------------------------------------------------

def test_ast_guard_main_py_uses_engine_begin_for_m045():
    """The spec requires engine.begin() (explicit transaction) at the call site,
    not engine.connect() (commit-as-you-go). Verify this in main.py source.
    """
    source = MAIN_PY.read_text()

    # Find the m045 block — look for the import line first to anchor the search
    m045_import_match = re.search(
        r"from app\.db\.migrations\.m045_close_remaining_crypto_equity_violations import run",
        source,
    )
    assert m045_import_match is not None, (
        "main.py must import run from m045_close_remaining_crypto_equity_violations"
    )

    # Extract a window of source around the m045 import (± 200 chars is plenty
    # to capture the `with engine.begin()` that immediately follows)
    start = max(0, m045_import_match.start() - 50)
    end = min(len(source), m045_import_match.end() + 300)
    m045_block = source[start:end]

    assert "engine.begin()" in m045_block, (
        "main.py m045 wrapper must use engine.begin() (explicit transaction), "
        f"but found block:\n{m045_block}"
    )
    assert "engine.connect()" not in m045_block, (
        "main.py m045 wrapper must NOT use engine.connect() — spec requires begin(). "
        f"Block:\n{m045_block}"
    )


# ---------------------------------------------------------------------------
# EXTRA — _is_equity_symbol helper boundary conditions
# ---------------------------------------------------------------------------

def test_is_equity_symbol_boundary_conditions():
    m045 = _load_m045()
    fn = m045._is_equity_symbol

    # Equity tickers → True
    assert fn("AAPL") is True
    assert fn("MSFT") is True
    assert fn("NVDA") is True
    assert fn("AMZN") is True
    assert fn("GOOGL") is True   # 5 chars
    assert fn("SPY") is True
    assert fn("QQQ") is True
    assert fn("GLD") is True

    # Exactly 6 chars (max allowed)
    assert fn("AAAAAA") is True  # 6 uppercase alpha — boundary

    # 7 chars → False (too long)
    assert fn("AAAAAAA") is False

    # Crypto pairs → False
    assert fn("BTC/USD") is False
    assert fn("ETH/USD") is False

    # OCC options → False (too long + has digits)
    assert fn("TSLA250620C00150000") is False
    assert fn("AAPL250620C00150000") is False

    # Empty → False
    assert fn("") is False
    assert fn(None) is False   # type: ignore[arg-type]

    # Lowercase → False
    assert fn("aapl") is False

    # Mixed case → False
    assert fn("Aapl") is False

    # Has digit → False
    assert fn("AAPL1") is False


# ---------------------------------------------------------------------------
# EXTRA — gate isolation: bot_allocations.starting_capital_cents not mutated
# ---------------------------------------------------------------------------

def test_m045_does_not_touch_starting_capital_cents():
    """Standing decision: m045 must NOT write to starting_capital_cents.
    Seed with a known value and assert it is unchanged after the migration.
    """
    eng = _make_engine()

    with eng.connect() as c:
        c.execute(
            text("INSERT INTO bot_profiles (name, asset_class) VALUES ('crypto_quant_aggressive', 'crypto')")
        )
        pid = c.execute(
            text("SELECT id FROM bot_profiles WHERE name = 'crypto_quant_aggressive'")
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations (user_id, profile_id, enabled, starting_capital_cents) "
                "VALUES (1, :pid, 1, 99999999)"
            ),
            {"pid": pid},
        )
        aid = c.execute(
            text("SELECT id FROM bot_allocations WHERE user_id = 1")
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'AAPL', 5, 20000)"
            ),
            {"aid": aid},
        )
        c.commit()

    m045 = _load_m045()
    with eng.begin() as conn:
        m045.run(conn)

    with eng.connect() as c:
        cap = c.execute(
            text("SELECT starting_capital_cents FROM bot_allocations WHERE user_id = 1")
        ).fetchone()[0]
    assert cap == 99999999, (
        f"starting_capital_cents must not be mutated by m045; got {cap}"
    )


# ---------------------------------------------------------------------------
# EXTRA — missing table guard returns expected skipped_reason shape
# ---------------------------------------------------------------------------

def test_missing_table_returns_skipped_reason():
    """If a required table is absent, run() returns skipped_reason=missing_table_X."""
    # Create engine with only schema_migrations — no bot_positions etc.
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
        c.commit()

    m045 = _load_m045()
    with eng.begin() as conn:
        result = m045.run(conn)

    assert result["executed"] is False
    assert result["skipped_reason"].startswith("missing_table_")
