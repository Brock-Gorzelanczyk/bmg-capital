"""test_cio_meeting_async — async background-task refactor tests.

Tests for:
  - POST /meeting/start returns 202 immediately with meeting_id
  - GET /meeting/{id}/status returns running then completed
  - 409 guard for running meeting started within 15 min
  - Stale (>15 min) running rows do NOT trigger 409
  - 9 agents fire in parallel (asyncio.gather)
  - One agent failure does not kill the meeting
  - kick_off_cio_meeting(dry_run=True) makes no DB writes

All LLM calls mocked — ZERO real calls to Claude.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import types
from datetime import datetime, timezone
from typing import Optional
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


def _ensure_cio_meeting_runner_module():
    """Ensure app.services.cio_meeting_runner is loaded as the real module."""
    name = "app.services.cio_meeting_runner"
    if name not in sys.modules or not hasattr(sys.modules[name], "run_meeting_background"):
        _load_real(name, "app/services/cio_meeting_runner.py")


_ensure_app_core()
_ensure_app_agents()
_ensure_app_routers()

# Stub app.db.models.users so the real app.dependencies can be loaded without
# a live database. get_current_user imports User lazily (inside the function body),
# but when the fund_floor router tests call it (in test_cio_meeting.py) via the
# REAL get_current_user (not overridden), the import fires. Stubbing here prevents
# ModuleNotFoundError when both test files are collected in the same pytest session.
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
# Use setdefault to avoid replacing app.dependencies if already loaded by test_cio_meeting.py.
# Reloading it creates a new module object, breaking dependency_overrides in the old test's
# fund_floor TestClient (which holds a reference to the original get_current_user function).
if "app.dependencies" not in sys.modules:
    _app_deps = _load_real("app.dependencies", "app/dependencies.py")
else:
    _app_deps = sys.modules["app.dependencies"]
_cio_mtg_router = _load_real("app.routers.cio_meeting", "app/routers/cio_meeting.py")


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


FAKE_SNAPSHOT = {
    "pv_cents": 100_000_000,
    "pv_dollars": 1_000_000.0,
    "today_pnl_cents": 5000,
    "return_30d_pct": 1.2,
    "drawdown_pct": -0.3,
    "drawdown_distance_to_halt_pct": 1.2,
    "open_positions_count": 47,
    "sleeves": [],
    "daily_api_budget_spent_usd": 0.0,
    "daily_api_budget_cap_usd": 3.0,
    "regime": "BULL_TRENDING",
    "vix": 13.4,
    "btc_dominance": 52.1,
    "ts_utc": "2026-06-29T09:00:00+00:00",
}


def _fake_opening_read_json() -> str:
    return json.dumps({
        "what_im_seeing": "Portfolio healthy at $1M NAV",
        "whats_working": "- Crypto sleeve +1.2%",
        "whats_broken": "[P2] minor slippage",
        "asks": "Review sizing",
        "metrics_i_track": {"pv": 1000000},
        "confidence_in_book": "8/10",
    })


def _fake_chair_json() -> str:
    return json.dumps({
        "top_items": [],
        "deferred": [],
    })


def _make_fake_call_llm(db, cost_per_call_cents: int = 2):
    from sqlalchemy import text

    def fake_call_llm(*, model, prompt, system_prompt="", max_tokens=1024,
                      agent_name="unknown", db=db, temperature=0.3):
        db.execute(
            text("INSERT INTO llm_call_log (agent_name, model, prompt_tokens, "
                 "completion_tokens, estimated_cost_cents, source) "
                 "VALUES (:an, 'claude-haiku', 100, 200, :cc, 'relay')"),
            {"an": agent_name, "cc": cost_per_call_cents},
        )
        db.commit()
        prompt_lower = prompt.lower()
        if "top_items" in prompt_lower or "pick the top 3" in prompt_lower:
            return _fake_chair_json()
        return _fake_opening_read_json()

    return fake_call_llm


def _make_test_app(db, monkeypatch):
    """Build a FastAPI test app with overridden DB + auth dependencies."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.cio_meeting import router
    from app.dependencies import get_db, get_current_user

    # Stub cio_meeting_runner so background tasks don't actually run LLMs
    import app.services.cio_meeting_runner as runner_mod
    monkeypatch.setattr(runner_mod, "run_meeting_background",
                        lambda *a, **kw: asyncio.coroutine(lambda: None)())

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return MagicMock(id=1, is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    return TestClient(app)


# ════════════════════════════════════════════════════════════════════════════════
# TEST 1 — start returns 202 + running immediately
# ════════════════════════════════════════════════════════════════════════════════

def test_start_returns_running_immediately(monkeypatch):
    """POST /meeting/start returns 202 + {meeting_id, status:'running'} in <2s."""
    engine = _make_test_engine()
    db = _make_session(engine)

    # Stub _spawn_runner so BackgroundTasks doesn't actually run the meeting
    import app.routers.cio_meeting as router_mod
    monkeypatch.setattr(router_mod, "_spawn_runner", lambda **kw: None)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.cio_meeting import router
    from app.dependencies import get_db, get_current_user

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return MagicMock(id=1, is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)

    t0 = time.monotonic()
    resp = client.post("/api/agents/cio/meeting/start", json={"runner_label": "test"})
    elapsed = time.monotonic() - t0

    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "running"
    assert body["meeting_id"].startswith("mtg_")
    assert elapsed < 2.0, f"Response took {elapsed:.2f}s — expected <2s"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 2 — status endpoint returns running then completed
# ════════════════════════════════════════════════════════════════════════════════

def test_status_endpoint_returns_running_then_completed(monkeypatch):
    """GET /meeting/{id}/status returns running before runner finishes, completed after."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    import app.routers.cio_meeting as router_mod
    monkeypatch.setattr(router_mod, "_spawn_runner", lambda **kw: None)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.cio_meeting import router
    from app.dependencies import get_db, get_current_user

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return MagicMock(id=1, is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)

    # Insert meeting row directly
    meeting_id = "mtg_test_status_001"
    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) "
        "VALUES (:m, :s, 'running')"
    ), {"m": meeting_id, "s": "2026-06-29T10:00:00+00:00"})
    db.commit()

    resp = client.get(f"/api/agents/cio/meeting/{meeting_id}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["ended_at"] is None
    assert body["posted_to_discord"] is False

    # Mark completed + add briefing row
    db.execute(text(
        "UPDATE fund_meetings SET status='completed', ended_at=:e, "
        "duration_seconds=42, model_cost_usd=0.85 WHERE meeting_id=:m"
    ), {"e": "2026-06-29T10:01:00+00:00", "m": meeting_id})
    db.execute(text(
        "INSERT INTO fund_briefings (briefing_id, meeting_id, markdown_body, "
        "summary_one_liner, needs_brock, discord_message_id) "
        "VALUES ('brf_x', :m, '...', 'all good', 0, 'discord_msg_id_123')"
    ), {"m": meeting_id})
    db.commit()

    resp = client.get(f"/api/agents/cio/meeting/{meeting_id}/status")
    body = resp.json()
    assert body["status"] == "completed"
    assert body["briefing_id"] == "brf_x"
    assert body["posted_to_discord"] is True
    assert body["discord_message_id"] == "discord_msg_id_123"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 3 — 404 for unknown meeting
# ════════════════════════════════════════════════════════════════════════════════

def test_status_404_for_unknown_meeting(monkeypatch):
    engine = _make_test_engine()
    db = _make_session(engine)

    import app.routers.cio_meeting as router_mod
    monkeypatch.setattr(router_mod, "_spawn_runner", lambda **kw: None)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.cio_meeting import router
    from app.dependencies import get_db, get_current_user

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return MagicMock(id=1, is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)
    resp = client.get("/api/agents/cio/meeting/mtg_does_not_exist/status")
    assert resp.status_code == 404
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 4 — 409 when running meeting exists (within 15 min)
# ════════════════════════════════════════════════════════════════════════════════

def test_409_when_running_meeting_exists(monkeypatch):
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    import app.routers.cio_meeting as router_mod
    monkeypatch.setattr(router_mod, "_spawn_runner", lambda **kw: None)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.cio_meeting import router
    from app.dependencies import get_db, get_current_user

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return MagicMock(id=1, is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)

    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) "
        "VALUES ('mtg_inflight', datetime('now', '-2 minutes'), 'running')"
    ))
    db.commit()

    resp = client.post("/api/agents/cio/meeting/start", json={"runner_label": "test"})
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    assert "already in progress" in resp.json()["detail"]
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 5 — 409 NOT triggered by stale running row (>15 min)
# ════════════════════════════════════════════════════════════════════════════════

def test_409_not_triggered_by_stale_running_row(monkeypatch):
    """If a 'running' row is older than 15 min, do NOT block — assume it wedged."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    import app.routers.cio_meeting as router_mod
    monkeypatch.setattr(router_mod, "_spawn_runner", lambda **kw: None)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.cio_meeting import router
    from app.dependencies import get_db, get_current_user

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return MagicMock(id=1, is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)

    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) "
        "VALUES ('mtg_wedged', datetime('now', '-30 minutes'), 'running')"
    ))
    db.commit()

    resp = client.post("/api/agents/cio/meeting/start", json={"runner_label": "test"})
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 6 — 9 agents fire in parallel
# ════════════════════════════════════════════════════════════════════════════════

def test_nine_agents_fire_in_parallel(monkeypatch):
    """When run_meeting_async fans out 9 opening reads, all start within 1s of each other."""
    engine = _make_test_engine()
    db = _make_session(engine)

    start_times: list = []

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        start_times.append((agent_name, time.monotonic()))
        time.sleep(0.3)  # simulate LLM latency
        from app.services.agent_opening_read import OpeningReadResult
        return OpeningReadResult(
            agent_name=agent_name, meeting_id=meeting_id,
            what_im_seeing="healthy", whats_working="ok", whats_broken="none",
            asks="nothing", metrics_i_track={}, confidence_in_book="8/10",
            cost_usd=0.01, response_time_ms=300, raw_text="{}",
            status="ok", error_text=None,
        )

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    monkeypatch.setattr(
        "app.services.cio_chair.compute_strategy_lab_aggregate",
        lambda user_id, db_: FAKE_SNAPSHOT,
    )
    monkeypatch.setattr(
        "app.services.cio_chair._call_chair_llm",
        lambda db, prompt, agent_name="cio", max_tokens=600, model="claude-haiku-4-5-20251001":
            (_fake_chair_json(), None),
    )

    from app.services.cio_chair import run_meeting_async

    t0 = time.monotonic()
    result = asyncio.run(run_meeting_async(
        db, meeting_id="mtg_parallel_test",
        budget_cap_usd=5.0, daily_cap_usd=10.0, wall_clock_cap_seconds=60,
        poll_dick_veto=False, dry_run=True,
    ))
    total_elapsed = time.monotonic() - t0

    # Serial would be 9 * 0.3 = 2.7s. Parallel should be ~0.4s.
    assert total_elapsed < 1.5, f"agents not parallel — took {total_elapsed:.2f}s"
    assert len(start_times) == 9, f"Expected 9 agent starts, got {len(start_times)}"

    # All 9 starts within 200ms of each other
    spread = max(t for _, t in start_times) - min(t for _, t in start_times)
    assert spread < 0.2, f"agent starts spread over {spread:.3f}s — not parallel"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 7 — one agent failure does not kill the meeting
# ════════════════════════════════════════════════════════════════════════════════

def test_one_agent_failure_does_not_kill_meeting(monkeypatch):
    """gather(return_exceptions=True) — one failure persists relay_down row, others succeed."""
    engine = _make_test_engine()
    db = _make_session(engine)

    call_count = [0]

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        call_count[0] += 1
        if agent_name == "quant_researcher":
            raise RuntimeError("simulated agent failure")
        from app.services.agent_opening_read import OpeningReadResult
        return OpeningReadResult(
            agent_name=agent_name, meeting_id=meeting_id,
            what_im_seeing="healthy", whats_working="ok", whats_broken="none",
            asks="nothing", metrics_i_track={}, confidence_in_book="8/10",
            cost_usd=0.01, response_time_ms=200, raw_text="{}",
            status="ok", error_text=None,
        )

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    monkeypatch.setattr(
        "app.services.cio_chair.compute_strategy_lab_aggregate",
        lambda user_id, db_: FAKE_SNAPSHOT,
    )
    monkeypatch.setattr(
        "app.services.cio_chair._call_chair_llm",
        lambda db, prompt, agent_name="cio", max_tokens=600, model="claude-haiku-4-5-20251001":
            (_fake_chair_json(), None),
    )

    from app.services.cio_chair import run_meeting_async

    result = asyncio.run(run_meeting_async(
        db, meeting_id="mtg_failure_test",
        budget_cap_usd=5.0, daily_cap_usd=10.0, wall_clock_cap_seconds=60,
        poll_dick_veto=False, dry_run=True,
    ))

    # 9 results total
    assert len(result.opening_reads) == 9, f"Expected 9 opening reads, got {len(result.opening_reads)}"

    # 1 relay_down, 8 ok
    relay_down = [r for r in result.opening_reads if r.status == "relay_down"]
    ok_reads = [r for r in result.opening_reads if r.status == "ok"]
    assert len(relay_down) == 1, f"Expected 1 relay_down, got {len(relay_down)}"
    assert relay_down[0].agent_name == "quant_researcher"
    assert len(ok_reads) == 8, f"Expected 8 ok reads, got {len(ok_reads)}"

    # Meeting should NOT be failed_budget — relay_down < 5
    assert result.status in ("completed", "failed_partial"), f"Unexpected status: {result.status}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 8 — kick_off_cio_meeting dry_run makes no DB write
# ════════════════════════════════════════════════════════════════════════════════

def test_kick_off_cio_meeting_dry_run_no_db_write(monkeypatch):
    """dry_run=True path must NOT insert into fund_meetings."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    monkeypatch.setattr(
        "app.services.cio_chair.compute_strategy_lab_aggregate",
        lambda user_id, db_: FAKE_SNAPSHOT,
    )

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        from app.services.agent_opening_read import OpeningReadResult
        return OpeningReadResult(
            agent_name=agent_name, meeting_id=meeting_id,
            what_im_seeing="ok", whats_working="ok", whats_broken="none",
            asks="nothing", metrics_i_track={}, confidence_in_book="8/10",
            cost_usd=0.0, response_time_ms=100, raw_text="{}",
            status="ok", error_text=None,
        )

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    monkeypatch.setattr(
        "app.services.cio_chair._call_chair_llm",
        lambda db, prompt, agent_name="cio", max_tokens=600, model="claude-haiku-4-5-20251001":
            (_fake_chair_json(), None),
    )
    monkeypatch.setattr(
        "app.services.cio_discord.post_cio_briefing",
        lambda **kw: None,
    )

    from app.agents.cio_orchestrator import kick_off_cio_meeting

    before = db.execute(text("SELECT COUNT(*) FROM fund_meetings")).scalar()
    result = kick_off_cio_meeting(db, dry_run=True)
    after = db.execute(text("SELECT COUNT(*) FROM fund_meetings")).scalar()

    assert after == before, f"dry_run inserted {after - before} row(s) into fund_meetings"
    assert result["markdown_body"] is not None, "dry_run should return markdown_body"
    db.close()
