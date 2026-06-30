"""SHIP 3 — Tests for get_all_time_pct and get_all_time_pct_with_meta.

Uses SQLite in-memory + sqlalchemy to test the service in isolation.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as c:
        c.execute(text("""
            CREATE TABLE bot_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                inception_capital_cents INTEGER DEFAULT 0,
                starting_capital_cents INTEGER DEFAULT 0,
                current_capital_cents INTEGER DEFAULT 0
            )
        """))
        c.execute(text("""
            CREATE TABLE bot_daily_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                realized_cents INTEGER NOT NULL DEFAULT 0,
                unrealized_cents INTEGER NOT NULL DEFAULT 0,
                fees_cents INTEGER NOT NULL DEFAULT 0,
                note TEXT
            )
        """))
        c.commit()
    Session = sessionmaker(bind=engine)
    return Session()


def _insert_alloc(db, inception: int, starting: int = 0) -> int:
    if starting == 0:
        starting = inception
    cur = db.execute(
        text(
            "INSERT INTO bot_allocations (inception_capital_cents, starting_capital_cents) "
            "VALUES (:i, :s)"
        ),
        {"i": inception, "s": starting},
    )
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]


def _insert_pnl(db, allocation_id: int, realized: int, note: str | None = None):
    db.execute(
        text(
            "INSERT INTO bot_daily_pnl (allocation_id, date, realized_cents, note) "
            "VALUES (:aid, date('now'), :r, :n)"
        ),
        {"aid": allocation_id, "r": realized, "n": note},
    )
    db.commit()


# ---------------------------------------------------------------------------
# Import the service under test (bypass conftest app.services stub)
# ---------------------------------------------------------------------------

import sys, os, types, importlib.util

def _load_bot_performance():
    """Load bot_performance.py directly, bypassing the conftest app.services stub."""
    services_path = os.path.join(os.path.dirname(__file__), "..", "app", "services")
    bp_path = os.path.join(services_path, "bot_performance.py")

    # Ensure sqlalchemy is real (it's installed)
    # Ensure app.services.bot_performance can be loaded as a real module
    pkg_key = "app.services.bot_performance"
    if pkg_key not in sys.modules or not hasattr(sys.modules[pkg_key], "get_all_time_pct"):
        spec = importlib.util.spec_from_file_location(pkg_key, bp_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[pkg_key]

_bp = _load_bot_performance()
get_all_time_pct = _bp.get_all_time_pct
get_all_time_pct_with_meta = _bp.get_all_time_pct_with_meta


# ---------------------------------------------------------------------------
# Test 1: Basic math — realized / inception
# ---------------------------------------------------------------------------

def test_get_all_time_pct_basic_math():
    """SUM(realized) / inception_capital_cents * 100."""
    db = _make_session()
    aid = _insert_alloc(db, inception=10_000_000)  # $100,000 inception
    _insert_pnl(db, aid, realized=100_000)   # +$1,000 realized
    _insert_pnl(db, aid, realized=50_000)    # +$500 realized

    pct = get_all_time_pct(aid, db)
    # 150_000 / 10_000_000 * 100 = 1.5
    assert pct == 1.5, f"Expected 1.5% got {pct}"
    db.close()


# ---------------------------------------------------------------------------
# Test 2: Marker row excluded from numerator
# ---------------------------------------------------------------------------

def test_get_all_time_pct_excludes_marker_rows():
    """track_reset_marker rows must not inflate the numerator."""
    db = _make_session()
    aid = _insert_alloc(db, inception=10_000_000)
    _insert_pnl(db, aid, realized=200_000)             # real P&L
    _insert_pnl(db, aid, realized=0, note="track_reset_marker")  # marker

    pct = get_all_time_pct(aid, db)
    # Only 200_000 counts; marker (0) is excluded
    assert pct == 2.0, f"Expected 2.0% got {pct}"
    db.close()


# ---------------------------------------------------------------------------
# Test 3: Zero division guard
# ---------------------------------------------------------------------------

def test_get_all_time_pct_zero_inception_returns_zero():
    """When inception_capital_cents = 0 and starting_capital_cents = 0, return 0.0."""
    db = _make_session()
    aid = _insert_alloc(db, inception=0, starting=0)
    _insert_pnl(db, aid, realized=500_000)

    pct = get_all_time_pct(aid, db)
    assert pct == 0.0, f"Expected 0.0 got {pct}"
    db.close()


# ---------------------------------------------------------------------------
# Test 4: get_all_time_pct_with_meta — is_post_reset flag
# ---------------------------------------------------------------------------

def test_get_all_time_pct_with_meta_is_post_reset_true_when_only_marker():
    """is_post_reset=True when only marker rows exist."""
    db = _make_session()
    aid = _insert_alloc(db, inception=10_000_000)
    _insert_pnl(db, aid, realized=0, note="track_reset_marker")

    meta = get_all_time_pct_with_meta(aid, db)
    assert meta["is_post_reset"] is True
    assert meta["pct"] == 0.0
    assert meta["reset_date"] is not None
    assert meta["first_pnl_date"] is None
    db.close()


# ---------------------------------------------------------------------------
# Test 5: get_all_time_pct_with_meta — is_post_reset False when real rows exist
# ---------------------------------------------------------------------------

def test_get_all_time_pct_with_meta_is_post_reset_false_with_real_rows():
    """is_post_reset=False when non-marker rows exist."""
    db = _make_session()
    aid = _insert_alloc(db, inception=10_000_000)
    _insert_pnl(db, aid, realized=300_000)  # real row
    _insert_pnl(db, aid, realized=0, note="track_reset_marker")

    meta = get_all_time_pct_with_meta(aid, db)
    assert meta["is_post_reset"] is False
    assert meta["pct"] == 3.0  # 300_000 / 10_000_000 * 100
    assert meta["first_pnl_date"] is not None
    db.close()


# ---------------------------------------------------------------------------
# Test 6: Missing allocation returns safe defaults
# ---------------------------------------------------------------------------

def test_get_all_time_pct_missing_allocation():
    db = _make_session()
    pct = get_all_time_pct(9999, db)
    assert pct == 0.0
    meta = get_all_time_pct_with_meta(9999, db)
    assert meta["pct"] == 0.0
    assert meta["is_post_reset"] is False
    db.close()


# ---------------------------------------------------------------------------
# Test 7: Falls back to starting_capital_cents when inception is NULL
# ---------------------------------------------------------------------------

def test_get_all_time_pct_falls_back_to_starting_when_inception_null():
    db = _make_session()
    # Force inception=NULL by setting it to 0 but starting to real value
    db.execute(text(
        "INSERT INTO bot_allocations (inception_capital_cents, starting_capital_cents) "
        "VALUES (NULL, 5000000)"
    ))
    db.commit()
    aid = db.execute(text("SELECT last_insert_rowid()")).fetchone()[0]
    _insert_pnl(db, aid, realized=50000)

    pct = get_all_time_pct(aid, db)
    # 50000 / 5000000 * 100 = 1.0
    assert pct == 1.0, f"Expected 1.0% got {pct}"
    db.close()
