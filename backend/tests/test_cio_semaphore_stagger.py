"""test_cio_semaphore_stagger — 6 tests for the Phase-3 semaphore + stagger feature.

Verifies:
  1. Semaphore limits concurrent in-flight agents to CIO_RELAY_CONCURRENCY (3).
  2. Stagger sleep introduces ~250ms gap between successive agent launches.
  3. Module constants CIO_RELAY_CONCURRENCY / CIO_RELAY_STAGGER_MS read from env.
  4. AST guard: asyncio.gather(...) inside run_meeting_async still uses return_exceptions=True.
  5. A single agent failure is persisted as relay_down; other 8 succeed; meeting completes.
  6. Total wall-clock with stagger is bounded (>= 2.0s due to stagger, < 3.5s total).

All tests are synchronous wrappers calling asyncio.run() — no pytest-asyncio dependency.
All LLM calls mocked — ZERO real calls to Claude.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import os
import sys
import threading
import time
import types
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest

# ─── Paths ─────────────────────────────────────────────────────────────────────

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(REPO_DIR, "backend")
CIO_CHAIR_PATH = os.path.join(BACKEND_DIR, "app", "services", "cio_chair.py")


# ─── Module bootstrap (mirrors test_cio_meeting_async.py) ─────────────────────

import importlib.util as _ilu


def _load_real(module_name: str, rel_path: str):
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


_users_stub = types.ModuleType("app.db.models.users")
_users_stub.User = MagicMock(name="User")
sys.modules.setdefault("app.db.models.users", _users_stub)
_app_db_models = sys.modules.get("app.db.models")
if _app_db_models is not None:
    setattr(_app_db_models, "users", _users_stub)

_ensure_app_core()
_ensure_app_agents()
_ensure_app_routers()

_llm_client = _load_real("app.services.llm_client", "app/services/llm_client.py")
_agent_or = _load_real("app.services.agent_opening_read", "app/services/agent_opening_read.py")
_cio_chair = _load_real("app.services.cio_chair", "app/services/cio_chair.py")


# ─── Shared test helpers ───────────────────────────────────────────────────────

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
    SessionFactory = sessionmaker(bind=engine)
    return SessionFactory()


def _make_session_factory(engine):
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=engine)


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


def _fake_chair_json() -> str:
    return json.dumps({"top_items": [], "deferred": []})


def _make_ok_opening_read(agent_name, meeting_id):
    from app.services.agent_opening_read import OpeningReadResult
    return OpeningReadResult(
        agent_name=agent_name, meeting_id=meeting_id,
        what_im_seeing="healthy", whats_working="ok", whats_broken="none",
        asks="nothing", metrics_i_track={}, confidence_in_book="8/10",
        cost_usd=0.01, response_time_ms=100, raw_text="{}",
        status="ok", error_text=None,
    )


def _patch_common(monkeypatch):
    """Patch snapshot and chair LLM calls; caller patches run_opening_read separately."""
    monkeypatch.setattr(
        "app.services.cio_chair.compute_strategy_lab_aggregate",
        lambda user_id, db_: FAKE_SNAPSHOT,
    )
    monkeypatch.setattr(
        "app.services.cio_chair._call_chair_llm",
        lambda db, prompt, agent_name="cio", max_tokens=600, model="claude-haiku-4-5-20251001":
            (_fake_chair_json(), None),
    )


def _force_reload_cio_chair_defaults(monkeypatch):
    """Set env vars to defaults and reload cio_chair via _load_real to avoid stub-parent issues."""
    monkeypatch.setenv("CIO_RELAY_CONCURRENCY", "3")
    monkeypatch.setenv("CIO_RELAY_STAGGER_MS", "250")
    return _load_real("app.services.cio_chair", "app/services/cio_chair.py")


# ════════════════════════════════════════════════════════════════════════════════
# TEST 1 — Semaphore limits concurrent in-flight agents to CIO_RELAY_CONCURRENCY
# ════════════════════════════════════════════════════════════════════════════════

def test_semaphore_limits_concurrent_to_3(monkeypatch):
    """At most CIO_RELAY_CONCURRENCY (3) agents should be in run_opening_read at once."""
    _force_reload_cio_chair_defaults(monkeypatch)

    engine = _make_test_engine()
    db = _make_session(engine)
    sf = _make_session_factory(engine)

    lock = threading.Lock()
    in_flight = [0]
    max_in_flight = [0]

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        with lock:
            in_flight[0] += 1
            if in_flight[0] > max_in_flight[0]:
                max_in_flight[0] = in_flight[0]
        time.sleep(0.1)  # simulate work
        with lock:
            in_flight[0] -= 1
        return _make_ok_opening_read(agent_name, meeting_id)

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    _patch_common(monkeypatch)

    from app.services.cio_chair import run_meeting_async, CIO_RELAY_CONCURRENCY

    asyncio.run(run_meeting_async(
        db, meeting_id="mtg_sem_test",
        budget_cap_usd=5.0, daily_cap_usd=10.0, wall_clock_cap_seconds=60,
        poll_dick_veto=False, dry_run=True,
        _session_factory=sf,
    ))

    assert max_in_flight[0] <= CIO_RELAY_CONCURRENCY, (
        f"max concurrent in-flight was {max_in_flight[0]}, expected <= {CIO_RELAY_CONCURRENCY}"
    )
    assert max_in_flight[0] > 0, "No agents ran at all"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 2 — Stagger introduces >= 200ms gap between successive agent launches
# ════════════════════════════════════════════════════════════════════════════════

def test_stagger_introduces_delay_between_launches(monkeypatch):
    """Successive agent launch timestamps should be separated by ~250ms (>=200ms tolerance)."""
    _force_reload_cio_chair_defaults(monkeypatch)

    engine = _make_test_engine()
    db = _make_session(engine)
    sf = _make_session_factory(engine)

    launch_lock = threading.Lock()
    launch_times: list = []

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        t = time.perf_counter()
        with launch_lock:
            launch_times.append(t)
        time.sleep(0.05)  # short work to not inflate total time
        return _make_ok_opening_read(agent_name, meeting_id)

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    _patch_common(monkeypatch)

    from app.services.cio_chair import run_meeting_async

    asyncio.run(run_meeting_async(
        db, meeting_id="mtg_stagger_test",
        budget_cap_usd=5.0, daily_cap_usd=10.0, wall_clock_cap_seconds=60,
        poll_dick_veto=False, dry_run=True,
        _session_factory=sf,
    ))

    assert len(launch_times) == 9, f"Expected 9 launch timestamps, got {len(launch_times)}"

    # Sort times — stagger is applied by idx before sem acquire, so sorted times
    # reflect the launch order (with 250ms gaps between each).
    sorted_times = sorted(launch_times)

    # Consecutive gaps should each be >= 200ms (250ms target minus 50ms tolerance).
    for i in range(8):
        gap = sorted_times[i + 1] - sorted_times[i]
        assert gap >= 0.20, (
            f"Gap between agent[{i}] and agent[{i+1}] was {gap:.3f}s — expected >= 0.20s"
        )

    # Total spread: agent[8] starts >= 1.8s after agent[0] (8 * 250ms - 200ms slack).
    total_spread = sorted_times[8] - sorted_times[0]
    assert total_spread >= 1.8, (
        f"Total launch spread was {total_spread:.3f}s — expected >= 1.8s for 9 agents * 250ms stagger"
    )

    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 3 — Module constants read from environment
# ════════════════════════════════════════════════════════════════════════════════

def test_module_constants_from_env(monkeypatch):
    """CIO_RELAY_CONCURRENCY and CIO_RELAY_STAGGER_MS must be read from env at module load."""
    monkeypatch.setenv("CIO_RELAY_CONCURRENCY", "5")
    monkeypatch.setenv("CIO_RELAY_STAGGER_MS", "100")
    m = _load_real("app.services.cio_chair", "app/services/cio_chair.py")

    try:
        assert m.CIO_RELAY_CONCURRENCY == 5, (
            f"Expected CIO_RELAY_CONCURRENCY == 5, got {m.CIO_RELAY_CONCURRENCY}"
        )
        assert m.CIO_RELAY_STAGGER_MS == 100, (
            f"Expected CIO_RELAY_STAGGER_MS == 100, got {m.CIO_RELAY_STAGGER_MS}"
        )
    finally:
        # Restore defaults so subsequent tests see standard values.
        monkeypatch.delenv("CIO_RELAY_CONCURRENCY", raising=False)
        monkeypatch.delenv("CIO_RELAY_STAGGER_MS", raising=False)
        m2 = _load_real("app.services.cio_chair", "app/services/cio_chair.py")
        assert m2.CIO_RELAY_CONCURRENCY == 3
        assert m2.CIO_RELAY_STAGGER_MS == 250


# ════════════════════════════════════════════════════════════════════════════════
# TEST 4 — AST guard: asyncio.gather inside run_meeting_async uses return_exceptions=True
# ════════════════════════════════════════════════════════════════════════════════

def test_return_exceptions_still_true():
    """AST guard: the asyncio.gather(...) call inside run_meeting_async must keep
    return_exceptions=True. If someone flips it to False, the downstream relay_down
    classification loop breaks (exceptions propagate instead of being classified per-agent).
    """
    with open(CIO_CHAIR_PATH, "r") as f:
        source = f.read()
    tree = ast.parse(source)

    # Find run_meeting_async function node.
    run_meeting_async_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "run_meeting_async":
                run_meeting_async_node = node
                break

    assert run_meeting_async_node is not None, "run_meeting_async not found in cio_chair.py"

    # Walk the function body for asyncio.gather calls.
    gather_calls_with_return_exceptions = []
    for node in ast.walk(run_meeting_async_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match asyncio.gather(...)
        is_gather = (
            isinstance(func, ast.Attribute)
            and func.attr == "gather"
            and isinstance(func.value, ast.Name)
            and func.value.id == "asyncio"
        )
        if not is_gather:
            continue
        # Check keywords for return_exceptions=True
        for kw in node.keywords:
            if kw.arg == "return_exceptions":
                val = kw.value
                # Python 3.8+: ast.Constant
                if isinstance(val, ast.Constant) and val.value is True:
                    gather_calls_with_return_exceptions.append(node)
                # Python 3.7: ast.NameConstant
                elif hasattr(ast, "NameConstant") and isinstance(val, ast.NameConstant) and val.value is True:
                    gather_calls_with_return_exceptions.append(node)

    assert len(gather_calls_with_return_exceptions) >= 1, (
        "gather must keep return_exceptions=True; downstream loop depends on per-agent "
        "exception classification as relay_down. Check the asyncio.gather(...) call "
        "inside run_meeting_async in cio_chair.py."
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 5 — Single agent failure classified as relay_down; meeting completes
# ════════════════════════════════════════════════════════════════════════════════

def test_agent_failure_still_classified_as_relay_down(monkeypatch):
    """chief_risk_officer raises httpx.ConnectError; other 8 succeed.
    After the meeting: CRO row has status='relay_down', others 'ok', meeting ended_at is non-NULL.
    """
    import httpx
    _force_reload_cio_chair_defaults(monkeypatch)

    engine = _make_test_engine()
    db = _make_session(engine)
    sf = _make_session_factory(engine)

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        if agent_name == "chief_risk_officer":
            raise httpx.ConnectError("boom")
        return _make_ok_opening_read(agent_name, meeting_id)

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    _patch_common(monkeypatch)

    from app.services.cio_chair import run_meeting_async
    from sqlalchemy import text

    meeting_id = "mtg_relay_down_test"
    asyncio.run(run_meeting_async(
        db, meeting_id=meeting_id,
        budget_cap_usd=5.0, daily_cap_usd=10.0, wall_clock_cap_seconds=60,
        poll_dick_veto=False, dry_run=False,
        _session_factory=sf,
    ))

    # Query the DB for agent_opening_reads rows.
    rows = db.execute(
        text("SELECT agent_name, status FROM agent_opening_reads WHERE meeting_id = :mid"),
        {"mid": meeting_id},
    ).fetchall()
    row_map = {r[0]: r[1] for r in rows}

    assert row_map.get("chief_risk_officer") == "relay_down", (
        f"Expected chief_risk_officer to be relay_down, got: {row_map.get('chief_risk_officer')}"
    )
    for agent_name, status in row_map.items():
        if agent_name != "chief_risk_officer":
            assert status == "ok", (
                f"Expected agent {agent_name} to be ok, got: {status}"
            )

    # Meeting row should have a non-NULL ended_at (meeting did not abort).
    meeting_row = db.execute(
        text("SELECT ended_at FROM fund_meetings WHERE meeting_id = :mid"),
        {"mid": meeting_id},
    ).fetchone()
    assert meeting_row is not None, f"No fund_meetings row found for {meeting_id}"
    assert meeting_row[0] is not None, "Meeting ended_at is NULL — meeting may have aborted"

    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 6 — Total wall-clock with stagger is bounded (>= 2.0s, < 3.5s)
# ════════════════════════════════════════════════════════════════════════════════

def test_total_time_with_stagger_is_bounded(monkeypatch):
    """With stagger=250ms and 9 agents, total elapsed must be >= 2.0s (stagger floor)
    and < 3.5s (semaphore=3 + stagger should not inflate to serial time).
    """
    _force_reload_cio_chair_defaults(monkeypatch)

    engine = _make_test_engine()
    db = _make_session(engine)
    sf = _make_session_factory(engine)

    def fake_run_opening_read(*, agent_name, meeting_id, canonical_snapshot,
                               recent_activity, open_commitments, db, started_at_iso):
        time.sleep(0.1)  # simulate work: fast enough for semaphore pipelining
        return _make_ok_opening_read(agent_name, meeting_id)

    monkeypatch.setattr("app.services.cio_chair.run_opening_read", fake_run_opening_read)
    _patch_common(monkeypatch)

    from app.services.cio_chair import run_meeting_async

    t0 = time.perf_counter()
    asyncio.run(run_meeting_async(
        db, meeting_id="mtg_bound_test",
        budget_cap_usd=5.0, daily_cap_usd=10.0, wall_clock_cap_seconds=60,
        poll_dick_veto=False, dry_run=True,
        _session_factory=sf,
    ))
    t1 = time.perf_counter()
    elapsed = t1 - t0

    assert elapsed >= 2.0, (
        f"Elapsed {elapsed:.3f}s is less than 2.0s — stagger (9 agents * 250ms = 2.0s) "
        "may not be applied correctly."
    )
    assert elapsed < 3.5, (
        f"Elapsed {elapsed:.3f}s exceeds 3.5s ceiling — semaphore+stagger combination "
        "is slower than expected (cap: stagger 2.0s + work 0.1s + headroom)."
    )

    db.close()
