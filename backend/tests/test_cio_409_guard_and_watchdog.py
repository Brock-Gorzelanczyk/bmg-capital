"""test_cio_409_guard_and_watchdog — 7 tests for the 409-guard SQL fix and m046 watchdog.

Tests:
  1. test_409_guard_excludes_stale_running_row — stale ISO-format row must NOT block new meeting
  2. test_409_guard_blocks_fresh_running_row — fresh ISO-format row MUST return 409
  3. test_409_guard_ignores_completed_row — completed status rows are invisible to guard
  4. test_409_guard_ignores_failed_killed_row — failed_killed rows are invisible to guard
  5. test_watchdog_fires_on_long_meeting — asyncio.wait_for marks row failed_timeout on timeout
  6. test_m046_kills_only_stale_running_rows — m046 kills >30min running, leaves fresh/completed
  7. test_m046_is_idempotent — m046 on clean DB returns killed_count=0 both times

CRITICAL: All seeded started_at values use Python isoformat() (T separator, +00:00 suffix),
NOT SQLite datetime('now', '-N minutes'). This reproduces the production bug where the old
SQL's lexicographic comparison always treated ISO-format strings as "in the future".
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# ─── Paths ─────────────────────────────────────────────────────────────────────

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(REPO_DIR, "backend")

import importlib.util as _ilu


def _load_real(module_name: str, rel_path: str):
    """Load a real source file and register it in sys.modules."""
    abs_path = os.path.join(BACKEND_DIR, rel_path)
    spec = _ilu.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {abs_path}")
    mod = _ilu.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    parts = module_name.split(".")
    if len(parts) > 1:
        parent_name = ".".join(parts[:-1])
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, parts[-1], mod)
    return mod


def _ensure_app_core():
    core_name = "app.core"
    if core_name not in sys.modules or not hasattr(sys.modules[core_name], "canonical"):
        core_init = os.path.join(BACKEND_DIR, "app", "core", "__init__.py")
        spec = _ilu.spec_from_file_location(core_name, core_init)
        if spec and spec.loader:
            mod = _ilu.module_from_spec(spec)
            sys.modules[core_name] = mod
            spec.loader.exec_module(mod)
            app_stub = sys.modules.get("app")
            if app_stub is not None:
                setattr(app_stub, "core", mod)


def _ensure_app_agents():
    agents_name = "app.agents"
    if agents_name not in sys.modules:
        agents_init = os.path.join(BACKEND_DIR, "app", "agents", "__init__.py")
        spec = _ilu.spec_from_file_location(agents_name, agents_init)
        if spec and spec.loader:
            mod = _ilu.module_from_spec(spec)
            sys.modules[agents_name] = mod
            spec.loader.exec_module(mod)
            app_stub = sys.modules.get("app")
            if app_stub is not None:
                setattr(app_stub, "agents", mod)


def _ensure_app_routers():
    routers_name = "app.routers"
    if routers_name not in sys.modules:
        mod = types.ModuleType(routers_name)
        sys.modules[routers_name] = mod
        app_stub = sys.modules.get("app")
        if app_stub is not None:
            setattr(app_stub, "routers", mod)


_ensure_app_core()
_ensure_app_agents()
_ensure_app_routers()

# Stub app.db.models.users so real app.dependencies can load without a live database.
_users_stub = types.ModuleType("app.db.models.users")
_users_stub.User = MagicMock(name="User")
sys.modules.setdefault("app.db.models.users", _users_stub)
_app_db_models = sys.modules.get("app.db.models")
if _app_db_models is not None:
    setattr(_app_db_models, "users", _users_stub)

_llm_client  = _load_real("app.services.llm_client",        "app/services/llm_client.py")
_agent_or    = _load_real("app.services.agent_opening_read", "app/services/agent_opening_read.py")
_cio_chair   = _load_real("app.services.cio_chair",         "app/services/cio_chair.py")
_cio_discord = _load_real("app.services.cio_discord",       "app/services/cio_discord.py")
_cio_runner  = _load_real("app.services.cio_meeting_runner","app/services/cio_meeting_runner.py")
_cio_orch    = _load_real("app.agents.cio_orchestrator",    "app/agents/cio_orchestrator.py")
_app_config  = _load_real("app.config",       "app/config.py")
if "app.dependencies" not in sys.modules:
    _app_deps = _load_real("app.dependencies", "app/dependencies.py")
else:
    _app_deps = sys.modules["app.dependencies"]


# ─── SQLite in-memory test DB ──────────────────────────────────────────────────

def _make_test_engine():
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(migration_name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS llm_call_log "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name TEXT, model TEXT, "
            " prompt_tokens INTEGER, completion_tokens INTEGER, estimated_cost_cents INTEGER, "
            " source TEXT DEFAULT 'relay', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS fund_meetings "
            "(meeting_id TEXT PRIMARY KEY, started_at TIMESTAMP NOT NULL, "
            " ended_at TIMESTAMP, duration_seconds INTEGER, model_cost_usd REAL NOT NULL DEFAULT 0.0, "
            " briefing_id TEXT, vetoes_used INTEGER NOT NULL DEFAULT 0, "
            " status TEXT NOT NULL DEFAULT 'running', failure_reason TEXT, created_by_runner TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS fund_briefings "
            "(briefing_id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, "
            " markdown_body TEXT NOT NULL, summary_one_liner TEXT NOT NULL DEFAULT '', "
            " needs_brock INTEGER NOT NULL DEFAULT 0, posted_at TIMESTAMP, "
            " discord_message_id TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS agent_opening_reads "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " agent_name TEXT NOT NULL, structured_read_json TEXT NOT NULL, "
            " response_time_ms INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0.0, "
            " status TEXT NOT NULL, error_text TEXT, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            " UNIQUE(meeting_id, agent_name))"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS agent_commitments "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " owner_agent TEXT NOT NULL, action_description TEXT NOT NULL, "
            " deadline TIMESTAMP NOT NULL, status TEXT NOT NULL DEFAULT 'open', "
            " resolved_at TIMESTAMP, resolution_note TEXT, "
            " strike_count INTEGER NOT NULL DEFAULT 0, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS veto_log "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " vetoed_by TEXT NOT NULL, vetoed_target_proposal TEXT NOT NULL, "
            " reason TEXT NOT NULL, brock_override INTEGER NOT NULL DEFAULT 0, "
            " override_at TIMESTAMP, override_note TEXT, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS bot_allocations "
            "(id INTEGER PRIMARY KEY, bot_id TEXT, user_id INTEGER, "
            " inception_capital_cents INTEGER, starting_capital_cents INTEGER, "
            " current_capital_cents INTEGER, enabled INTEGER, portfolio_id INTEGER, "
            " profile_id INTEGER, paused_reason TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS bot_positions "
            "(id INTEGER PRIMARY KEY, bot_id TEXT, user_id INTEGER, "
            " symbol TEXT, status TEXT, closed_at TIMESTAMP, quantity REAL, avg_cost REAL)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS strategy_portfolios "
            "(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)"
        ))
        conn.commit()
    return engine


def _make_session(engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    return Session()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 1 — stale ISO-format row must NOT block a new meeting
# ════════════════════════════════════════════════════════════════════════════════

def test_409_guard_excludes_stale_running_row():
    """Reproduces the production bug. With the old SQLite datetime() SQL this test FAILS.
    With the Python-bound :cutoff fix it PASSES."""
    from sqlalchemy import text
    from app.agents.cio_orchestrator import create_meeting_record

    engine = _make_test_engine()
    db = _make_session(engine)
    stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    db.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                    "VALUES ('mtg_stale_iso', :s, 'running')"),
               {"s": stale_iso})
    db.commit()

    new_mid = create_meeting_record(db, runner_label="test")
    assert new_mid.startswith("mtg_")
    assert new_mid != "mtg_stale_iso"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 2 — fresh ISO-format row MUST trigger 409
# ════════════════════════════════════════════════════════════════════════════════

def test_409_guard_blocks_fresh_running_row():
    """A running row started 5 minutes ago (Python ISO format) must raise 409."""
    from fastapi import HTTPException
    from sqlalchemy import text
    from app.agents.cio_orchestrator import create_meeting_record

    engine = _make_test_engine()
    db = _make_session(engine)
    fresh_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    db.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                    "VALUES ('mtg_fresh_iso', :s, 'running')"),
               {"s": fresh_iso})
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        create_meeting_record(db, runner_label="test")
    assert exc_info.value.status_code == 409
    assert "mtg_fresh_iso" in exc_info.value.detail
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 3 — completed row from 1 min ago must NOT trigger 409
# ════════════════════════════════════════════════════════════════════════════════

def test_409_guard_ignores_completed_row():
    """A recently completed row (status='completed') must not block a new meeting."""
    from sqlalchemy import text
    from app.agents.cio_orchestrator import create_meeting_record

    engine = _make_test_engine()
    db = _make_session(engine)
    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    db.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                    "VALUES ('mtg_done', :s, 'completed')"),
               {"s": recent_iso})
    db.commit()

    new_mid = create_meeting_record(db, runner_label="test")
    assert new_mid != "mtg_done"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 4 — failed_killed row from 1 min ago must NOT trigger 409
# ════════════════════════════════════════════════════════════════════════════════

def test_409_guard_ignores_failed_killed_row():
    """A recently failed_killed row must not block a new meeting (m046 cleanup case)."""
    from sqlalchemy import text
    from app.agents.cio_orchestrator import create_meeting_record

    engine = _make_test_engine()
    db = _make_session(engine)
    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    db.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                    "VALUES ('mtg_killed', :s, 'failed_killed')"),
               {"s": recent_iso})
    db.commit()

    new_mid = create_meeting_record(db, runner_label="test")
    assert new_mid != "mtg_killed"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 5 — asyncio watchdog fires and marks row failed_timeout
# ════════════════════════════════════════════════════════════════════════════════

def test_watchdog_fires_on_long_meeting(monkeypatch):
    """Patches BG_WATCHDOG_SECONDS to 0.5s and _run_meeting_inner to sleep 5s.
    The watchdog must fire and update the row to failed_timeout."""
    from sqlalchemy import text
    import app.services.cio_meeting_runner as runner_mod

    engine = _make_test_engine()
    db = _make_session(engine)

    # Seed the row that create_meeting_record would normally have created
    meeting_id = "mtg_watchdog_test"
    started_iso = datetime.now(timezone.utc).isoformat()
    db.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                    "VALUES (:m, :s, 'running')"),
               {"m": meeting_id, "s": started_iso})
    db.commit()

    # Patch the runner's SessionLocal to return our in-memory session
    monkeypatch.setattr(runner_mod, "SessionLocal", lambda: db)

    # Shorten watchdog to 0.5s
    monkeypatch.setattr(runner_mod, "BG_WATCHDOG_SECONDS", 0.5)

    # Replace _run_meeting_inner with a coroutine that sleeps 5s
    async def _slow_inner(*args, **kwargs):
        await asyncio.sleep(5.0)

    monkeypatch.setattr(runner_mod, "_run_meeting_inner", _slow_inner)

    asyncio.run(runner_mod.run_meeting_background(meeting_id, runner_label="test"))

    row = db.execute(text(
        "SELECT status, failure_reason, ended_at FROM fund_meetings WHERE meeting_id=:m"
    ), {"m": meeting_id}).fetchone()
    assert row is not None
    assert row[0] == "failed_timeout", f"expected failed_timeout, got {row[0]}"
    assert row[1] and ("watchdog" in row[1].lower() or "timeout" in row[1].lower()), \
        f"failure_reason should mention watchdog/timeout, got {row[1]}"
    assert row[2] is not None, "ended_at should be set"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 6 — m046 kills only stale running rows (>30 min), leaves fresh + completed
# ════════════════════════════════════════════════════════════════════════════════

def test_m046_kills_only_stale_running_rows():
    """m046 must update only the row that is both status='running' AND started >30min ago."""
    from sqlalchemy import text

    # Load m046 directly via file path — conftest stubs app.db as a mock module,
    # so the normal package import path (app.db.migrations.*) is unavailable.
    _m046_mod = _load_real(
        "app.db.migrations.m046_force_kill_stuck_running_meetings",
        "app/db/migrations/m046_force_kill_stuck_running_meetings.py",
    )
    run_m046 = _m046_mod.run

    engine = _make_test_engine()

    old_iso    = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
    fresh_iso  = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                          "VALUES ('mtg_old_running', :s, 'running')"), {"s": old_iso})
        conn.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                          "VALUES ('mtg_fresh_running', :s, 'running')"), {"s": fresh_iso})
        conn.execute(text("INSERT INTO fund_meetings (meeting_id, started_at, status) "
                          "VALUES ('mtg_old_completed', :s, 'completed')"), {"s": old_iso})

    with engine.begin() as conn:
        result = run_m046(conn)

    assert result["executed"] is True
    assert result["killed_count"] == 1

    with engine.connect() as conn:
        row_old = conn.execute(text(
            "SELECT status, failure_reason, ended_at FROM fund_meetings "
            "WHERE meeting_id='mtg_old_running'"
        )).fetchone()
        assert row_old[0] == "failed_killed"
        assert row_old[1] == "boot_orphan_cleanup"
        assert row_old[2] is not None

        row_fresh = conn.execute(text(
            "SELECT status FROM fund_meetings WHERE meeting_id='mtg_fresh_running'"
        )).fetchone()
        assert row_fresh[0] == "running"

        row_completed = conn.execute(text(
            "SELECT status FROM fund_meetings WHERE meeting_id='mtg_old_completed'"
        )).fetchone()
        assert row_completed[0] == "completed"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 7 — m046 is idempotent (no-op on clean DB)
# ════════════════════════════════════════════════════════════════════════════════

def test_m046_is_idempotent():
    """On a clean DB, m046 returns killed_count=0 both times it runs."""
    # Load m046 directly via file path — conftest stubs app.db as a mock module,
    # so the normal package import path (app.db.migrations.*) is unavailable.
    _m046_mod = _load_real(
        "app.db.migrations.m046_force_kill_stuck_running_meetings",
        "app/db/migrations/m046_force_kill_stuck_running_meetings.py",
    )
    run_m046 = _m046_mod.run

    engine = _make_test_engine()

    with engine.begin() as conn:
        r1 = run_m046(conn)
    with engine.begin() as conn:
        r2 = run_m046(conn)

    assert r1["executed"] is True
    assert r1["killed_count"] == 0
    assert r2["executed"] is True
    assert r2["killed_count"] == 0
