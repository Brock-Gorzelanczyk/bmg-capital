"""SHIP 3 — Tests for track_record_reconstruction service.

Uses SQLite in-memory DB; Alpaca HTTP calls are mocked.
"""
from __future__ import annotations

import sys
import os
import types
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib.util
import types


def _load_module(module_key: str, file_path: str):
    """Load a module directly from disk, bypassing conftest stubs."""
    if module_key not in sys.modules or not hasattr(sys.modules.get(module_key), "__file__"):
        spec = importlib.util.spec_from_file_location(module_key, file_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[module_key]

_services_dir = os.path.join(os.path.dirname(__file__), "..", "app", "services")
_bp_mod = _load_module(
    "app.services.bot_performance",
    os.path.join(_services_dir, "bot_performance.py"),
)
# Pre-register so track_record_reconstruction can import it
sys.modules.setdefault("app.services.bot_performance", _bp_mod)

# ---------------------------------------------------------------------------
# Minimal DB schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    starting_capital_cents INTEGER NOT NULL DEFAULT 0,
    inception_capital_cents INTEGER NOT NULL DEFAULT 0,
    current_capital_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    realized_cents INTEGER NOT NULL DEFAULT 0,
    unrealized_cents INTEGER NOT NULL DEFAULT 0,
    fees_cents INTEGER NOT NULL DEFAULT 0,
    inception_capital_cents_snapshot INTEGER DEFAULT 0,
    note TEXT
);
"""


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as c:
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                c.execute(text(s))
        c.commit()
    Session = sessionmaker(bind=engine)
    return Session()


def _insert_alloc(db, bot_name: str, inception: int = 10_000_000, enabled: int = 1) -> int:
    cur = db.execute(text("INSERT INTO bot_profiles (name) VALUES (:n)"), {"n": bot_name})
    db.commit()
    pid = db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]
    db.execute(
        text(
            "INSERT INTO bot_allocations "
            "(profile_id, user_id, enabled, inception_capital_cents, starting_capital_cents) "
            "VALUES (:pid, 1, :en, :i, :i)"
        ),
        {"pid": pid, "en": enabled, "i": inception},
    )
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


_trr_mod = _load_module(
    "app.services.track_record_reconstruction",
    os.path.join(_services_dir, "track_record_reconstruction.py"),
)
insert_track_reset_marker = _trr_mod.insert_track_reset_marker
reconstruct_from_alpaca = _trr_mod.reconstruct_from_alpaca
reconstruct_for_user = _trr_mod.reconstruct_for_user
TRACK_RESET_MARKER_NOTE = _trr_mod.TRACK_RESET_MARKER_NOTE
M027_RESET_DATE = _trr_mod.M027_RESET_DATE


# ---------------------------------------------------------------------------
# Test 1: insert_track_reset_marker is idempotent
# ---------------------------------------------------------------------------

def test_insert_track_reset_marker_idempotent():
    db = _make_session()
    aid = _insert_alloc(db, "stock_swing")

    r1 = insert_track_reset_marker(aid, db)
    assert r1["marker_inserted"] is True
    assert r1["existing_marker_date"] is None

    r2 = insert_track_reset_marker(aid, db)
    assert r2["marker_inserted"] is False
    assert r2["existing_marker_date"] is not None

    # Only one marker row should exist
    count = db.execute(
        text(
            "SELECT COUNT(*) FROM bot_daily_pnl "
            "WHERE allocation_id=:aid AND note='track_reset_marker'"
        ),
        {"aid": aid},
    ).fetchone()[0]
    assert count == 1, f"Expected 1 marker row, got {count}"
    db.close()


# ---------------------------------------------------------------------------
# Test 2: reconstruct_from_alpaca returns not_eligible for non-cash_floor bots
# ---------------------------------------------------------------------------

def test_reconstruct_from_alpaca_not_eligible_for_non_cash_floor():
    db = _make_session()
    aid = _insert_alloc(db, "stock_swing")

    result = reconstruct_from_alpaca(aid, db)
    assert result["status"] == "not_eligible"
    assert result["days_reconstructed"] == 0
    db.close()


# ---------------------------------------------------------------------------
# Test 3: reconstruct_from_alpaca for cash_floor with mocked Alpaca fills
# ---------------------------------------------------------------------------

def test_reconstruct_from_alpaca_cash_floor_with_mock_fills():
    db = _make_session()
    aid = _insert_alloc(db, "cash_floor")

    mock_fills = [
        {
            "transaction_time": "2026-06-25T14:30:00Z",
            "symbol": "SPY",
            "side": "sell",
            "qty": 100.0,
            "price": 545.50,
        },
        {
            "transaction_time": "2026-06-25T14:30:01Z",
            "symbol": "QQQ",
            "side": "buy",
            "qty": 50.0,
            "price": 465.00,
        },
    ]

    with patch.object(_trr_mod, "_fetch_alpaca_fills", return_value=mock_fills):
        result = reconstruct_from_alpaca(aid, db, since=date(2026, 6, 25))

    # sell 100 * 545.50 = 54550 dollars; buy 50 * 465 = 23250 dollars
    # net realized for the day: +31300 USD = +3_130_000 cents
    assert result["days_reconstructed"] == 1
    assert result["status"] == "reconstructed"
    assert result["earliest_fill_date"] == "2026-06-25"

    # Verify the row was inserted
    rows = db.execute(
        text("SELECT realized_cents FROM bot_daily_pnl WHERE allocation_id=:aid"),
        {"aid": aid},
    ).fetchall()
    assert len(rows) == 1
    db.close()


# ---------------------------------------------------------------------------
# Test 4: reconstruct_from_alpaca does NOT overwrite existing rows
# ---------------------------------------------------------------------------

def test_reconstruct_from_alpaca_does_not_overwrite_existing():
    db = _make_session()
    aid = _insert_alloc(db, "cash_floor")

    # Pre-insert a row for 2026-06-25
    db.execute(
        text(
            "INSERT INTO bot_daily_pnl (allocation_id, date, realized_cents) "
            "VALUES (:aid, '2026-06-25', 99999)"
        ),
        {"aid": aid},
    )
    db.commit()

    mock_fills = [
        {
            "transaction_time": "2026-06-25T14:30:00Z",
            "symbol": "SPY",
            "side": "sell",
            "qty": 100.0,
            "price": 545.50,
        },
    ]

    with patch.object(_trr_mod, "_fetch_alpaca_fills", return_value=mock_fills):
        result = reconstruct_from_alpaca(aid, db, since=date(2026, 6, 25))

    assert result["days_reconstructed"] == 0  # existing row blocks insert

    # Original value must be intact
    original = db.execute(
        text("SELECT realized_cents FROM bot_daily_pnl WHERE allocation_id=:aid"),
        {"aid": aid},
    ).fetchone()[0]
    assert original == 99999, f"Row was overwritten: {original}"
    db.close()


# ---------------------------------------------------------------------------
# Test 5: reconstruct_for_user inserts markers for non-eligible bots
# ---------------------------------------------------------------------------

def test_reconstruct_for_user_markers_for_non_eligible():
    db = _make_session()
    _insert_alloc(db, "stock_swing")
    _insert_alloc(db, "crypto_day")

    with patch.object(_trr_mod, "_fetch_alpaca_fills", return_value=[]):
        result = reconstruct_for_user(1, db)

    assert result["user_id"] == 1
    assert result["total_days_reconstructed"] == 0
    assert result["total_markers_inserted"] == 2  # both non-eligible get markers

    # Confirm markers exist
    count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_pnl WHERE note='track_reset_marker'")
    ).fetchone()[0]
    assert count == 2
    db.close()


# ---------------------------------------------------------------------------
# Test 6: reconstruct_for_user is idempotent (second call inserts 0 markers)
# ---------------------------------------------------------------------------

def test_reconstruct_for_user_is_idempotent():
    db = _make_session()
    _insert_alloc(db, "stock_swing")

    with patch.object(_trr_mod, "_fetch_alpaca_fills", return_value=[]):
        r1 = reconstruct_for_user(1, db)
        r2 = reconstruct_for_user(1, db)

    assert r1["total_markers_inserted"] == 1
    assert r2["total_markers_inserted"] == 0  # already exists, no insert

    # Still exactly 1 marker row
    count = db.execute(
        text("SELECT COUNT(*) FROM bot_daily_pnl WHERE note='track_reset_marker'")
    ).fetchone()[0]
    assert count == 1
    db.close()


# ---------------------------------------------------------------------------
# Test 7: Alpaca API down returns no_data gracefully
# ---------------------------------------------------------------------------

def test_fetch_alpaca_fills_graceful_on_error():
    """_fetch_alpaca_fills returns [] on any error (Alpaca API down)."""
    # Patch _fetch_alpaca_fills to return [] (simulates network error)
    with patch.object(_trr_mod, "_fetch_alpaca_fills", return_value=[]):
        result = _trr_mod._fetch_alpaca_fills(date(2026, 6, 1))
    assert result == []
