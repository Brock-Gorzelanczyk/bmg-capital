"""Tests for _gate.verify_count helper.

7 tests covering:
  1. Match with expected=0 (empty result) — returns 0, no exception.
  2. Match with expected=N (non-zero) — returns actual count, no exception.
  3. Mismatch with on_mismatch="raise" (default) — raises RuntimeError.
  4. RuntimeError message contains "verify_count <name>" (name interpolated).
  5. RuntimeError message encodes expected and actual counts.
  6. on_mismatch="log_critical" — does NOT raise, returns actual count.
  7. INFO is logged when count matches expected.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"
GATE_PATH = MIGRATIONS_DIR / "_gate.py"


# ---------------------------------------------------------------------------
# Module loader
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


def _load_gate():
    pkg = "app.db.migrations"
    if pkg not in sys.modules:
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg

    full_name = "app.db.migrations._gate"
    sys.modules.pop(full_name, None)
    spec = importlib.util.spec_from_file_location(full_name, str(GATE_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Minimal in-memory engine factory (only needs a simple table)
# ---------------------------------------------------------------------------

def _make_engine_with_rows(rows: list[tuple]) -> object:
    """Return an engine pre-seeded with a 'items' table containing *rows*."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.connect() as c:
        c.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"))
        for row in rows:
            c.execute(
                text("INSERT INTO items (id, name) VALUES (:id, :name)"),
                {"id": row[0], "name": row[1]},
            )
        c.execute(text("""
            CREATE TABLE schema_migrations (
                migration_name TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
        c.commit()
    return eng


# ---------------------------------------------------------------------------
# TEST 1 — Match expected=0 (empty result) — returns 0, no exception
# ---------------------------------------------------------------------------

def test_verify_count_match_zero_returns_zero():
    """When query returns 0 rows and expected=0, verify_count returns 0."""
    gate = _load_gate()
    eng = _make_engine_with_rows([])

    with eng.connect() as conn:
        result = gate.verify_count(
            conn,
            name="test_migration",
            sql="SELECT * FROM items",
            expected=0,
        )

    assert result == 0


# ---------------------------------------------------------------------------
# TEST 2 — Match expected=N (non-zero) — returns actual count, no exception
# ---------------------------------------------------------------------------

def test_verify_count_match_nonzero_returns_actual():
    """When query returns N rows and expected=N, verify_count returns N."""
    gate = _load_gate()
    eng = _make_engine_with_rows([(1, "a"), (2, "b"), (3, "c")])

    with eng.connect() as conn:
        result = gate.verify_count(
            conn,
            name="test_migration",
            sql="SELECT * FROM items",
            expected=3,
        )

    assert result == 3


# ---------------------------------------------------------------------------
# TEST 3 — Mismatch with on_mismatch="raise" (default) — raises RuntimeError
# ---------------------------------------------------------------------------

def test_verify_count_mismatch_raises_runtime_error():
    """When count != expected and on_mismatch='raise', RuntimeError is raised."""
    gate = _load_gate()
    eng = _make_engine_with_rows([(1, "leftover")])

    with pytest.raises(RuntimeError):
        with eng.connect() as conn:
            gate.verify_count(
                conn,
                name="m999",
                sql="SELECT * FROM items",
                expected=0,
            )


# ---------------------------------------------------------------------------
# TEST 4 — RuntimeError message contains "verify_count <name>"
# ---------------------------------------------------------------------------

def test_verify_count_error_message_contains_name():
    """RuntimeError message must contain 'verify_count <name>' so logs are greppable."""
    gate = _load_gate()
    eng = _make_engine_with_rows([(1, "leftover"), (2, "also_leftover")])

    with pytest.raises(RuntimeError, match="verify_count m045"):
        with eng.connect() as conn:
            gate.verify_count(
                conn,
                name="m045",
                sql="SELECT * FROM items",
                expected=0,
            )


# ---------------------------------------------------------------------------
# TEST 5 — RuntimeError message encodes expected and actual counts
# ---------------------------------------------------------------------------

def test_verify_count_error_message_encodes_counts():
    """RuntimeError message must include both expected and actual counts."""
    gate = _load_gate()
    eng = _make_engine_with_rows([(1, "x"), (2, "y")])

    with pytest.raises(RuntimeError) as exc_info:
        with eng.connect() as conn:
            gate.verify_count(
                conn,
                name="m033",
                sql="SELECT * FROM items",
                expected=0,
            )

    msg = str(exc_info.value)
    # Must encode expected (0) and actual (2)
    assert "0" in msg, f"Expected count '0' not found in error: {msg!r}"
    assert "2" in msg, f"Actual count '2' not found in error: {msg!r}"


# ---------------------------------------------------------------------------
# TEST 6 — on_mismatch="log_critical" — does NOT raise, returns actual count
# ---------------------------------------------------------------------------

def test_verify_count_log_critical_does_not_raise():
    """With on_mismatch='log_critical', mismatch logs CRITICAL but does not raise."""
    gate = _load_gate()
    eng = _make_engine_with_rows([(1, "leftover")])

    # Must not raise
    with eng.connect() as conn:
        result = gate.verify_count(
            conn,
            name="m045",
            sql="SELECT * FROM items",
            expected=0,
            on_mismatch="log_critical",
        )

    assert result == 1, f"Expected actual count 1, got {result}"


# ---------------------------------------------------------------------------
# TEST 7 — INFO is logged when count matches expected
# ---------------------------------------------------------------------------

def test_verify_count_logs_info_on_match(caplog):
    """When count matches expected, an INFO message is emitted."""
    gate = _load_gate()
    eng = _make_engine_with_rows([])

    with caplog.at_level(logging.INFO, logger="app.db.migrations._gate"):
        with eng.connect() as conn:
            gate.verify_count(
                conn,
                name="m045",
                sql="SELECT * FROM items",
                expected=0,
            )

    info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("verify_count" in m for m in info_messages), (
        f"Expected INFO log containing 'verify_count', got: {info_messages}"
    )
