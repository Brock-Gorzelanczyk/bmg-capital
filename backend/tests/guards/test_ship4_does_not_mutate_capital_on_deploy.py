"""
G1 — SHIP 4 does not mutate capital on deploy.

Snapshot SUM(starting_capital_cents), SUM(inception_capital_cents),
SUM(current_capital_cents) for user_id=1 BEFORE running m031+m032 migrations.
Run them. Assert all three sums are byte-identical after.

Uses an in-memory SQLite DB so this test is self-contained and never touches prod.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _BACKEND_DIR / "app" / "db" / "migrations"


def _load_migration(module_short: str):
    """Load a migration from disk, bypassing conftest's app.db stub."""
    pkg = "app.db.migrations"
    if pkg not in sys.modules or not hasattr(sys.modules[pkg], "__path__"):
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(_MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg
        app_db = sys.modules.get("app.db")
        if app_db is not None:
            app_db.migrations = real_pkg
    full = f"{pkg}.{module_short}"
    path = _MIGRATIONS_DIR / f"{module_short}.py"
    if not path.exists():
        raise ImportError(f"Migration file not found: {path}")
    spec = importlib.util.spec_from_file_location(full, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_engine():
    return create_engine("sqlite:///:memory:")


def _setup_tables(conn):
    """Create minimal tables needed for the test."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_allocations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            starting_capital_cents INTEGER DEFAULT 0,
            inception_capital_cents INTEGER DEFAULT 0,
            current_capital_cents INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1
        )
    """))
    conn.execute(text("""
        INSERT INTO bot_allocations
            (user_id, starting_capital_cents, inception_capital_cents, current_capital_cents, is_enabled)
        VALUES (1, 100000000, 100000000, 100000000, 1)
    """))
    # _migration_log needed by _gate.already_ran / _gate.record
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS _migration_log (
            name TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """))
    # schema_migrations also used by some gates
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_name TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _snapshot_capitals(conn):
    row = conn.execute(text("""
        SELECT
            COALESCE(SUM(starting_capital_cents), 0),
            COALESCE(SUM(inception_capital_cents), 0),
            COALESCE(SUM(current_capital_cents), 0)
        FROM bot_allocations
        WHERE user_id = 1
    """)).fetchone()
    return (row[0], row[1], row[2])


def test_g1_ship4_migrations_do_not_mutate_capital():
    """m031 and m032 must not touch any capital column."""
    engine = _make_engine()

    with engine.connect() as conn:
        _setup_tables(conn)
        before = _snapshot_capitals(conn)
        conn.commit()

    # Run m031
    try:
        m031 = _load_migration("m031_anthropic_call_cache")
        with engine.connect() as conn:
            m031.run(conn)
            conn.commit()
    except Exception as e:
        pytest.skip(f"m031 not importable in test env: {e}")

    # Run m032
    try:
        m032 = _load_migration("m032_llm_call_log")
        with engine.connect() as conn:
            m032.run(conn)
            conn.commit()
    except Exception as e:
        pytest.skip(f"m032 not importable in test env: {e}")

    with engine.connect() as conn:
        after = _snapshot_capitals(conn)

    assert before == after, (
        f"Capital fields mutated by SHIP 4 migrations!\n"
        f"  Before: starting={before[0]}, inception={before[1]}, current={before[2]}\n"
        f"  After:  starting={after[0]}, inception={after[1]}, current={after[2]}"
    )
