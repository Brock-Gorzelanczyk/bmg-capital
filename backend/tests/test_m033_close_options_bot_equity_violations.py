"""Tests for m033_close_options_bot_equity_violations.

Covers:
  1. Happy path — options_income bot with AAPL equity symbol → position closed.
  2. OCC option symbol is NOT closed (TSLA250620C00150000 left alone).
  3. Idempotency — second run returns already_applied.
  4. Missing table returns skipped_reason.
  5. Multi-user: user_id=1 positions closed, user_id=3 positions NOT touched
     (m033 is intentionally scoped to user_id=1 per docstring).
  6. test_m033_now_calls_verify_count — AST/import check that m033 imports
     verify_count and calls it with name="m033"; fails if call removed.
  7. verify_count raises RuntimeError when equity positions remain after run.
  8. Bots are PAUSED after run (enabled=0, paused_reason set).
  9. starting_capital_cents not mutated.
  10. verify_count call in m033 uses the same SQL equity heuristic as m045.
"""
from __future__ import annotations

import ast as _ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"
M033_PATH = MIGRATIONS_DIR / "m033_close_options_bot_equity_violations.py"


# ---------------------------------------------------------------------------
# sys.modules restore fixture
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


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def _load_m033():
    pkg = "app.db.migrations"
    if pkg not in sys.modules or not hasattr(sys.modules.get(pkg, types.ModuleType(pkg)), "__path__"):
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg

    if "app.db.migrations._gate" not in sys.modules:
        gate_path = MIGRATIONS_DIR / "_gate.py"
        gate_spec = importlib.util.spec_from_file_location(
            "app.db.migrations._gate", str(gate_path)
        )
        gate_mod = importlib.util.module_from_spec(gate_spec)
        sys.modules["app.db.migrations._gate"] = gate_mod
        gate_spec.loader.exec_module(gate_mod)

    full_name = "app.db.migrations.m033_close_options_bot_equity_violations"
    sys.modules.pop(full_name, None)
    spec = importlib.util.spec_from_file_location(full_name, str(M033_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# SQLite in-memory engine factory
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
                starting_capital_cents INTEGER,
                paused_reason TEXT
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


def _seed_position(eng, *, user_id: int, bot_name: str, symbol: str,
                   starting_capital_cents: int = 5_000_000):
    """Seed one bot_profile, one bot_allocation, one bot_position."""
    with eng.connect() as c:
        # Insert or ignore in case the profile already exists
        c.execute(
            text("INSERT OR IGNORE INTO bot_profiles (name, asset_class) VALUES (:n, 'option')"),
            {"n": bot_name},
        )
        pid = c.execute(
            text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": bot_name}
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations "
                "(user_id, profile_id, enabled, starting_capital_cents) "
                "VALUES (:uid, :pid, 1, :cap)"
            ),
            {"uid": user_id, "pid": pid, "cap": starting_capital_cents},
        )
        aid = c.execute(
            text(
                "SELECT id FROM bot_allocations "
                "WHERE user_id = :uid AND profile_id = :pid ORDER BY id DESC LIMIT 1"
            ),
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
# TEST 1 — Happy path: options_income + AAPL (equity) → position closed
# ---------------------------------------------------------------------------

def test_happy_path_closes_equity_violation():
    eng = _seed_position(
        _make_engine(),
        user_id=1,
        bot_name="options_income",
        symbol="AAPL",
    )
    m033 = _load_m033()

    # m033 calls conn.commit() internally, so use connect() not begin()
    with eng.connect() as conn:
        result = m033.run(conn)

    assert result["executed"] is True
    assert result["options_income_closed"] == 1
    assert result["quarantined"] == 1

    with eng.connect() as c:
        pos = c.execute(
            text("SELECT closed_at, exit_reason FROM bot_positions WHERE symbol = 'AAPL'")
        ).fetchone()
        assert pos[0] is not None, "closed_at must be set"
        assert pos[1] == "m033_options_equity_violation"

        gate = c.execute(
            text(
                "SELECT migration_name FROM schema_migrations "
                "WHERE migration_name = 'm033_close_options_bot_equity_violations_2026_06'"
            )
        ).fetchone()
        assert gate is not None, "gate row must be recorded"


# ---------------------------------------------------------------------------
# TEST 2 — OCC option symbol NOT closed (legitimate option left alone)
# ---------------------------------------------------------------------------

def test_occ_option_symbol_not_closed():
    """A valid OCC option symbol on options_income must be left open."""
    occ_symbol = "TSLA250620C00150000"
    eng = _seed_position(
        _make_engine(),
        user_id=1,
        bot_name="options_income",
        symbol=occ_symbol,
    )
    m033 = _load_m033()

    with eng.connect() as conn:
        result = m033.run(conn)

    assert result["executed"] is True
    assert result["options_income_closed"] == 0, "OCC option must not be closed"

    with eng.connect() as c:
        pos = c.execute(
            text(f"SELECT closed_at FROM bot_positions WHERE symbol = '{occ_symbol}'")
        ).fetchone()
        assert pos[0] is None, "OCC option position must remain open"


# ---------------------------------------------------------------------------
# TEST 3 — Idempotency: second run returns already_applied
# ---------------------------------------------------------------------------

def test_idempotency_second_run_is_no_op():
    eng = _seed_position(
        _make_engine(),
        user_id=1,
        bot_name="options_income",
        symbol="MSFT",
    )
    m033 = _load_m033()

    with eng.connect() as conn:
        first = m033.run(conn)
    with eng.connect() as conn:
        second = m033.run(conn)

    assert first["executed"] is True
    assert second == {"skipped_reason": "already_applied", "executed": False}


# ---------------------------------------------------------------------------
# TEST 4 — Missing table returns skipped_reason
# ---------------------------------------------------------------------------

def test_missing_table_returns_skipped_reason():
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

    m033 = _load_m033()
    with eng.connect() as conn:
        result = m033.run(conn)

    assert result["executed"] is False
    assert result["skipped_reason"].startswith("missing_table_")


# ---------------------------------------------------------------------------
# TEST 5 — Multi-user scoping: user_id=1 closed, user_id=3 NOT touched
#           (m033 is intentionally scoped to user_id=1 unlike m045)
# ---------------------------------------------------------------------------

def test_multi_user_scoping_user3_not_touched():
    """m033 scopes to user_id=1 only (WHERE a.user_id = :uid with uid=1).
    user_id=3 positions must remain open — different behavior from m045.
    """
    eng = _make_engine()

    # Seed user_id=1 position (options_income, AAPL)
    _seed_position(eng, user_id=1, bot_name="options_income", symbol="AAPL")

    # Seed user_id=3 position (options_income, MSFT)
    # Re-use same bot_profile, add a second allocation
    with eng.connect() as c:
        pid = c.execute(
            text("SELECT id FROM bot_profiles WHERE name = 'options_income'")
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations (user_id, profile_id, enabled, starting_capital_cents) "
                "VALUES (3, :pid, 1, 5000000)"
            ),
            {"pid": pid},
        )
        aid3 = c.execute(
            text(
                "SELECT id FROM bot_allocations WHERE user_id = 3 ORDER BY id DESC LIMIT 1"
            )
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_positions (allocation_id, symbol, qty, avg_cost_cents) "
                "VALUES (:aid, 'MSFT', 5, 30000)"
            ),
            {"aid": aid3},
        )
        c.commit()

    m033 = _load_m033()
    with eng.connect() as conn:
        result = m033.run(conn)

    assert result["executed"] is True
    assert result["options_income_closed"] == 1, "only user_id=1 AAPL should be closed"

    with eng.connect() as c:
        aapl = c.execute(
            text("SELECT closed_at FROM bot_positions WHERE symbol = 'AAPL'")
        ).fetchone()
        msft = c.execute(
            text("SELECT closed_at FROM bot_positions WHERE symbol = 'MSFT'")
        ).fetchone()

    assert aapl[0] is not None, "user_id=1 AAPL must be closed"
    assert msft[0] is None, "user_id=3 MSFT must NOT be closed (m033 scoped to uid=1)"


# ---------------------------------------------------------------------------
# TEST 6 — test_m033_now_calls_verify_count
#           AST confirms m033 imports verify_count AND calls it with name="m033"
# ---------------------------------------------------------------------------

def test_m033_now_calls_verify_count():
    """Spec test #6: m033 must import verify_count and call it with name='m033'.

    This test is designed to FAIL if the verify_count call is removed from m033.
    """
    source = M033_PATH.read_text()
    tree = _ast.parse(source)

    # 1. Confirm import: from app.db.migrations._gate import ... verify_count
    import_found = False
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom):
            if node.module and "_gate" in node.module:
                names = [alias.name for alias in node.names]
                if "verify_count" in names:
                    import_found = True
                    break

    assert import_found, (
        "m033 must import verify_count from app.db.migrations._gate. "
        "Found no such import — was it removed?"
    )

    # 2. Confirm call: verify_count(..., name="m033", ...)
    call_found = False
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Name)
            and node.func.id == "verify_count"
        ):
            # Check keyword arg name="m033"
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, _ast.Constant):
                    if kw.value.value == "m033":
                        call_found = True
                        break
            if call_found:
                break

    assert call_found, (
        "m033 must call verify_count(..., name='m033', ...). "
        "No such call found — was the verify_count call removed?"
    )


# ---------------------------------------------------------------------------
# TEST 7 — verify_count raises RuntimeError when equity positions remain
# ---------------------------------------------------------------------------

def test_verify_fail_raises_runtime_error():
    """If UPDATE bot_positions is a no-op, post-run verify must raise RuntimeError."""
    eng = _seed_position(
        _make_engine(),
        user_id=1,
        bot_name="options_income",
        symbol="AAPL",
    )
    m033 = _load_m033()

    original_run = m033.run

    def patched_run(conn):
        original_execute = conn.execute

        def no_op_update(stmt, params=None):
            sql_text = str(stmt)
            if "UPDATE bot_positions" in sql_text and "closed_at" in sql_text:
                from sqlalchemy import text as _text
                return original_execute(
                    _text("UPDATE bot_positions SET closed_at = :ts WHERE id = -999"),
                    {"ts": "2099-01-01"},
                )
            return original_execute(stmt, params)

        conn.execute = no_op_update
        return original_run(conn)

    with pytest.raises(RuntimeError, match="verify_count m033"):
        with eng.connect() as conn:
            patched_run(conn)


# ---------------------------------------------------------------------------
# TEST 8 — Bots are PAUSED after successful run
# ---------------------------------------------------------------------------

def test_bots_are_paused_after_run():
    """m033 must set enabled=0 and paused_reason on options_income and
    options_directional allocations for user_id=1.
    """
    eng = _make_engine()

    # Seed both options bots with user_id=1
    for bot_name in ("options_income", "options_directional"):
        _seed_position(eng, user_id=1, bot_name=bot_name, symbol="AAPL")

    m033 = _load_m033()
    with eng.connect() as conn:
        result = m033.run(conn)

    assert result["executed"] is True
    assert len(result["paused_alloc_ids"]) >= 2, (
        f"Both bots must be paused, got paused_alloc_ids={result['paused_alloc_ids']}"
    )

    with eng.connect() as c:
        rows = c.execute(
            text(
                "SELECT a.enabled, a.paused_reason "
                "FROM bot_allocations a "
                "JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE p.name IN ('options_income', 'options_directional') "
                "AND a.user_id = 1"
            )
        ).fetchall()

    assert len(rows) >= 2
    for row in rows:
        assert row[0] == 0, f"enabled must be 0 after m033, got {row[0]}"
        assert row[1] == "strategy_generates_invalid_symbols", (
            f"paused_reason wrong: {row[1]}"
        )


# ---------------------------------------------------------------------------
# TEST 9 — starting_capital_cents not mutated
# ---------------------------------------------------------------------------

def test_m033_does_not_touch_starting_capital_cents():
    """Standing decision: m033 must NOT write to starting_capital_cents."""
    eng = _seed_position(
        _make_engine(),
        user_id=1,
        bot_name="options_income",
        symbol="AAPL",
        starting_capital_cents=88888888,
    )
    m033 = _load_m033()

    with eng.connect() as conn:
        m033.run(conn)

    with eng.connect() as c:
        cap = c.execute(
            text("SELECT starting_capital_cents FROM bot_allocations WHERE user_id = 1")
        ).fetchone()[0]
    assert cap == 88888888, f"starting_capital_cents mutated; got {cap}"


# ---------------------------------------------------------------------------
# TEST 10 — verify_count SQL uses same equity heuristics as m045
# ---------------------------------------------------------------------------

def test_m033_verify_sql_uses_equity_heuristic():
    """The verify_count call in m033 must use the same SQL-side equity filter
    clauses as m045: length<=6, NOT LIKE '%/%', GLOB '[A-Z]*', NOT GLOB '*[0-9]*'.
    """
    source = M033_PATH.read_text()
    tree = _ast.parse(source)

    # Find the verify_count call and extract the sql= keyword value
    verify_sql = None
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Name)
            and node.func.id == "verify_count"
        ):
            for kw in node.keywords:
                if kw.arg == "sql":
                    # Could be a string constant or a concatenated expression
                    if isinstance(kw.value, _ast.Constant):
                        verify_sql = kw.value.value
                    else:
                        # walk for string constants and join them
                        parts = []
                        for sub in _ast.walk(kw.value):
                            if isinstance(sub, _ast.Constant) and isinstance(sub.value, str):
                                parts.append(sub.value)
                        verify_sql = " ".join(parts)
                    break

    assert verify_sql is not None, "Could not find sql= argument in verify_count call"

    for clause in (
        "length",
        "NOT LIKE",
        "GLOB",
        "[A-Z]",
        "[0-9]",
    ):
        assert clause in verify_sql, (
            f"verify_count SQL in m033 missing equity heuristic clause '{clause}'. "
            f"Full sql: {verify_sql!r}"
        )
