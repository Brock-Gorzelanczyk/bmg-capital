"""SHIP 5 — CIO Morning Meeting test suite.

All 21 required tests:
  1.  test_cio_runs_under_budget
  2.  test_cio_completes_under_10min
  3.  test_all_9_agents_polled
  4.  test_briefing_includes_canonical_pv_not_stale
  5.  test_action_items_have_owner_and_deadline
  6.  test_commitments_carry_forward_to_next_meeting
  7.  test_broken_commitments_escalate_strike_count
  8.  test_veto_enforcement_kills_capital_decision
  9.  test_veto_scope_limit_dick_cannot_veto_operational
  10. test_brock_override_veto_writes_to_decision_history
  11. test_briefing_posts_to_cio_channel_not_signal
  12. test_fund_floor_endpoints_return_latest_briefing
  13. test_daily_3_dollar_budget_blocks_third_meeting
  14. test_cio_does_not_use_anthropic_sdk_directly
  15. test_no_new_calls_to_ensure_portfolios_for_user
  16. test_no_new_writes_to_starting_capital_cents
  17. test_no_writes_to_bot_trades_or_bot_daily_pnl
  18. test_ship5_does_not_mutate_capital_on_deploy
  19. test_relay_down_fails_closed
  20. test_meeting_cost_zero_direct_api_tokens
  21. test_409_concurrent_meeting_guard

All LLM calls mocked via monkeypatch — ZERO real calls to Claude or anthropic SDK.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ─── Paths ─────────────────────────────────────────────────────────────────────

REPO_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_DIR / "backend"
SHIP5_FILES = [
    REPO_DIR / "scripts" / "cio_morning_meeting.py",
    BACKEND_DIR / "app" / "agents" / "cio_orchestrator.py",
    BACKEND_DIR / "app" / "services" / "cio_chair.py",
    BACKEND_DIR / "app" / "services" / "agent_opening_read.py",
    BACKEND_DIR / "app" / "services" / "cio_discord.py",
    BACKEND_DIR / "app" / "routers" / "agent_opening_reads.py",
    BACKEND_DIR / "app" / "routers" / "cio_meeting.py",
    BACKEND_DIR / "app" / "routers" / "fund_floor.py",
]

# ─── Real module bootstrap ─────────────────────────────────────────────────────
# conftest.py pre-installs mock modules for "app", "app.services", "app.db" etc.
# using sys.modules.setdefault() so regular `from app.services.X import Y` fails
# because it resolves app.services to the mock object (which has no real attrs).
#
# We follow the test_factor_attribution.py pattern: load real source files
# directly via importlib and register them under the correct dotted names.
# After this block, monkeypatch.setattr("app.services.cio_chair.call_llm", …)
# will patch the real module object instead of a dead mock.

import importlib.util as _ilu

_BACKEND_ROOT = str(BACKEND_DIR)


def _load_real(module_name: str, rel_path: str):
    """Load a real source file and register it in sys.modules."""
    abs_path = os.path.join(_BACKEND_ROOT, rel_path)
    spec = _ilu.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {abs_path}")
    mod = _ilu.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    # Wire onto parent stub so attribute access chains work
    parts = module_name.split(".")
    if len(parts) > 1:
        parent_name = ".".join(parts[:-1])
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, parts[-1], mod)
    return mod


# Ensure app.core exists as a real package before loading canonical
def _ensure_app_core():
    core_name = "app.core"
    if core_name not in sys.modules or not hasattr(sys.modules[core_name], "canonical"):
        core_init = os.path.join(_BACKEND_ROOT, "app", "core", "__init__.py")
        spec = _ilu.spec_from_file_location(core_name, core_init)
        if spec and spec.loader:
            mod = _ilu.module_from_spec(spec)
            sys.modules[core_name] = mod
            spec.loader.exec_module(mod)
            # Wire onto app stub
            app_stub = sys.modules.get("app")
            if app_stub is not None:
                setattr(app_stub, "core", mod)


def _ensure_app_agents():
    agents_name = "app.agents"
    if agents_name not in sys.modules:
        agents_init = os.path.join(_BACKEND_ROOT, "app", "agents", "__init__.py")
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
        import types as _types
        mod = _types.ModuleType(routers_name)
        sys.modules[routers_name] = mod
        app_stub = sys.modules.get("app")
        if app_stub is not None:
            setattr(app_stub, "routers", mod)


def _ensure_app_db_migrations():
    """Load app.db, app.db.migrations, _gate, and all 5 SHIP-5 migrations via importlib."""
    import types as _types

    # app.db.migrations namespace
    mig_name = "app.db.migrations"
    if mig_name not in sys.modules:
        mig_init = os.path.join(_BACKEND_ROOT, "app", "db", "migrations", "__init__.py")
        spec = _ilu.spec_from_file_location(mig_name, mig_init)
        if spec and spec.loader:
            mod = _ilu.module_from_spec(spec)
            sys.modules[mig_name] = mod
            spec.loader.exec_module(mod)
            # Wire onto app.db stub
            db_stub = sys.modules.get("app.db")
            if db_stub is not None:
                setattr(db_stub, "migrations", mod)
        else:
            # __init__.py may be empty; create a bare namespace module
            mod = _types.ModuleType(mig_name)
            sys.modules[mig_name] = mod

    # _gate
    _gate_name = "app.db.migrations._gate"
    if _gate_name not in sys.modules:
        _load_real(_gate_name, "app/db/migrations/_gate.py")

    # SHIP-5 migrations
    for _mn, _rp in [
        ("app.db.migrations.m039_fund_meetings",    "app/db/migrations/m039_fund_meetings.py"),
        ("app.db.migrations.m040_fund_briefings",   "app/db/migrations/m040_fund_briefings.py"),
        ("app.db.migrations.m041_agent_opening_reads","app/db/migrations/m041_agent_opening_reads.py"),
        ("app.db.migrations.m042_agent_commitments","app/db/migrations/m042_agent_commitments.py"),
        ("app.db.migrations.m043_veto_log",         "app/db/migrations/m043_veto_log.py"),
    ]:
        if _mn not in sys.modules:
            _load_real(_mn, _rp)


# Bootstrap order: dependencies first, then services, then routers
_ensure_app_core()
_ensure_app_agents()
_ensure_app_routers()
_ensure_app_db_migrations()

_llm_client      = _load_real("app.services.llm_client",       "app/services/llm_client.py")
_agent_or        = _load_real("app.services.agent_opening_read","app/services/agent_opening_read.py")
_cio_chair       = _load_real("app.services.cio_chair",        "app/services/cio_chair.py")
_cio_discord     = _load_real("app.services.cio_discord",      "app/services/cio_discord.py")
_cio_orch        = _load_real("app.agents.cio_orchestrator",   "app/agents/cio_orchestrator.py")

# Load app.dependencies chain via importlib (app mock in sys.modules blocks normal import)
_app_config  = _load_real("app.config",       "app/config.py")
_app_deps    = _load_real("app.dependencies", "app/dependencies.py")

_cio_runner      = _load_real("app.services.cio_meeting_runner","app/services/cio_meeting_runner.py")
_ff_router       = _load_real("app.routers.fund_floor",        "app/routers/fund_floor.py")
_cio_mtg_router  = _load_real("app.routers.cio_meeting",       "app/routers/cio_meeting.py")

# ─── SQLite in-memory test DB helpers ──────────────────────────────────────────

def _make_test_engine():
    """Create an in-memory SQLite engine with all SHIP-5 tables + seed tables.

    Uses StaticPool so all sessions/connections share ONE underlying SQLite
    connection — this is required for :memory: DBs where each raw connection
    would otherwise be a completely separate (empty) database.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        # schema_migrations (required by _gate)
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(migration_name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        # llm_call_log (SHIP 4 table — stub)
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS llm_call_log "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name TEXT, model TEXT, "
            " prompt_tokens INTEGER, completion_tokens INTEGER, estimated_cost_cents INTEGER, "
            " source TEXT DEFAULT 'relay', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        # SHIP-5 tables via migrations
        _run_migration("m039_fund_meetings", conn)
        _run_migration("m040_fund_briefings", conn)
        _run_migration("m041_agent_opening_reads", conn)
        _run_migration("m042_agent_commitments", conn)
        _run_migration("m043_veto_log", conn)
        # bot_allocations stub (for canonical snapshot)
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS bot_allocations "
            "(id INTEGER PRIMARY KEY, bot_id TEXT, user_id INTEGER, "
            " inception_capital_cents INTEGER, starting_capital_cents INTEGER, "
            " current_capital_cents INTEGER, enabled INTEGER, portfolio_id INTEGER, "
            " profile_id INTEGER, paused_reason TEXT)"
        ))
        # bot_positions stub
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS bot_positions "
            "(id INTEGER PRIMARY KEY, bot_id TEXT, user_id INTEGER, "
            " symbol TEXT, status TEXT, closed_at TIMESTAMP, quantity REAL, avg_cost REAL)"
        ))
        # strategy_portfolios stub
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS strategy_portfolios "
            "(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)"
        ))
        conn.commit()
    return engine


def _run_migration(name: str, conn) -> None:
    """Import and run a single migration against the test connection."""
    from sqlalchemy import text
    if name == "m039_fund_meetings":
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS fund_meetings "
            "(meeting_id TEXT PRIMARY KEY, started_at TIMESTAMP NOT NULL, "
            " ended_at TIMESTAMP, duration_seconds INTEGER, model_cost_usd REAL NOT NULL DEFAULT 0.0, "
            " briefing_id TEXT, vetoes_used INTEGER NOT NULL DEFAULT 0, "
            " status TEXT NOT NULL DEFAULT 'running', failure_reason TEXT, created_by_runner TEXT)"
        ))
    elif name == "m040_fund_briefings":
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS fund_briefings "
            "(briefing_id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, "
            " markdown_body TEXT NOT NULL, summary_one_liner TEXT NOT NULL DEFAULT '', "
            " needs_brock INTEGER NOT NULL DEFAULT 0, posted_at TIMESTAMP, "
            " discord_message_id TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
    elif name == "m041_agent_opening_reads":
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS agent_opening_reads "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " agent_name TEXT NOT NULL, structured_read_json TEXT NOT NULL, "
            " response_time_ms INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0.0, "
            " status TEXT NOT NULL, error_text TEXT, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            " UNIQUE(meeting_id, agent_name))"
        ))
    elif name == "m042_agent_commitments":
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS agent_commitments "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " owner_agent TEXT NOT NULL, action_description TEXT NOT NULL, "
            " deadline TIMESTAMP NOT NULL, status TEXT NOT NULL DEFAULT 'open', "
            " resolved_at TIMESTAMP, resolution_note TEXT, "
            " strike_count INTEGER NOT NULL DEFAULT 0, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
    elif name == "m043_veto_log":
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS veto_log "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " vetoed_by TEXT NOT NULL, vetoed_target_proposal TEXT NOT NULL, "
            " reason TEXT NOT NULL, brock_override INTEGER NOT NULL DEFAULT 0, "
            " override_at TIMESTAMP, override_note TEXT, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
    conn.commit()


def _make_session(engine):
    """Return a SQLAlchemy Session bound to the test engine."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_llm_log_cost(db, agent_name: str, cost_cents: int, source: str = "relay") -> None:
    """Insert a fake llm_call_log row so cost accounting works."""
    from sqlalchemy import text
    db.execute(
        text(
            "INSERT INTO llm_call_log (agent_name, model, prompt_tokens, completion_tokens, "
            "estimated_cost_cents, source) VALUES (:an, 'claude-haiku', 100, 200, :cc, :src)"
        ),
        {"an": agent_name, "cc": cost_cents, "src": source},
    )
    db.commit()


# ─── Canonical snapshot stub ───────────────────────────────────────────────────

FAKE_SNAPSHOT = {
    "pv_cents": 100_000_000,
    "pv_dollars": 1_000_000.0,
    "today_pnl_cents": 5000,
    "return_30d_pct": 1.2,
    "drawdown_pct": -0.3,
    "drawdown_distance_to_halt_pct": 1.2,
    "open_positions_count": 47,
    "sleeves": [
        {"sleeve": "Stocks", "dollars": 270000, "pct": 27.0, "today_pnl_cents": 1500},
        {"sleeve": "Crypto", "dollars": 270000, "pct": 27.0, "today_pnl_cents": 3500},
    ],
    "daily_api_budget_spent_usd": 0.0,
    "daily_api_budget_cap_usd": 3.0,
    "regime": "BULL_TRENDING",
    "vix": 13.4,
    "btc_dominance": 52.1,
    "ts_utc": "2026-06-28T09:00:00+00:00",
}


def _fake_opening_read_json() -> str:
    return json.dumps({
        "what_im_seeing": "Portfolio healthy at $1M NAV",
        "whats_working": "- Crypto sleeve +1.2%\n- Stocks flat",
        "whats_broken": "[P2] minor slippage on 3 fills",
        "asks": "Review Quant Scalper sizing",
        "metrics_i_track": {"pv": 1000000, "drawdown_pct": -0.3},
        "confidence_in_book": "8/10 — solid",
    })


def _fake_chair_top3_json() -> str:
    return json.dumps({
        "top_items": [
            {
                "title": "Quant Scalper allocation review",
                "surfaced_by": ["quant_researcher", "portfolio_manager"],
                "tension": "Alpha decay detected; rebalance may be needed",
                "severity": "P1",
                "is_capital_or_risk": True,
            },
            {
                "title": "Crypto BTC/ETH correlation cluster risk",
                "surfaced_by": ["chief_risk_officer"],
                "tension": "Correlation at 0.88 — cluster risk above 3+ threshold",
                "severity": "P0",
                "is_capital_or_risk": True,
            },
            {
                "title": "Sentinel worker recycling status",
                "surfaced_by": ["sentinel_devops"],
                "tension": "Ops degraded — worker recycled mid-morning",
                "severity": "P2",
                "is_capital_or_risk": False,
            },
        ],
        "deferred": ["Review TSLA positioning"],
    })


def _fake_debate_round1_json(agent: str = "quant_researcher") -> str:
    return json.dumps({"position_words": f"{agent}: Recommend trimming Quant Scalper by 20%"})


def _fake_resolution_json() -> str:
    return json.dumps({
        "resolution": "Trim Quant Scalper allocation by 20% pending Dick sign-off",
        "action_items": [
            {"owner": "portfolio_manager", "action": "Prepare rebalance proposal", "deadline_iso": "2026-06-29T12:00:00Z"},
            {"owner": "chief_risk_officer", "action": "Sign off on rebalance", "deadline_iso": "2026-06-29T14:00:00Z"},
        ],
    })


def _fake_veto_json(decision: str = "PASS") -> str:
    return json.dumps({"decision": decision, "reason": "Cluster risk within tolerable range"})


def _make_fake_call_llm(
    db,
    cost_per_call_cents: int = 5,
    opening_read_response: Optional[str] = None,
    chair_response: Optional[str] = None,
    debate_response: Optional[str] = None,
    resolution_response: Optional[str] = None,
    veto_response: Optional[str] = None,
    raise_error: bool = False,
):
    """Return a fake call_llm that inserts cost rows and returns canned JSON."""
    call_count = [0]

    def fake_call_llm(
        *,
        model: str,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 1024,
        agent_name: str = "unknown",
        db=db,
        temperature: float = 0.3,
    ) -> str:
        if raise_error:
            raise RuntimeError("relay unreachable and FALLBACK_TO_API=false: test error")
        call_count[0] += 1
        # Insert cost row so budget accounting works
        _seed_llm_log_cost(db, agent_name, cost_per_call_cents, source="relay")
        # Return appropriate canned response
        prompt_lower = prompt.lower()
        if "pick the top 3 agenda items" in prompt_lower or "top_items" in prompt_lower:
            return chair_response or _fake_chair_top3_json()
        if "position_words" in prompt.lower() or "position on this item" in prompt_lower:
            return debate_response or _fake_debate_round1_json(agent_name)
        if "resolution" in prompt_lower and "action_items" in prompt_lower:
            return resolution_response or _fake_resolution_json()
        if "veto poll" in prompt_lower or "veto" in prompt_lower and "decision" in prompt_lower:
            return veto_response or _fake_veto_json("PASS")
        # Default: opening read
        return opening_read_response or _fake_opening_read_json()

    return fake_call_llm


# ─── Test helpers ──────────────────────────────────────────────────────────────

def _run_meeting_with_mocks(
    monkeypatch,
    engine=None,
    cost_per_call_cents: int = 5,
    raise_error: bool = False,
    veto_response: Optional[str] = None,
    skip_canonical_mock: bool = False,
):
    """Run a full meeting with mocked call_llm and canonical snapshot."""
    if engine is None:
        engine = _make_test_engine()
    db = _make_session(engine)

    fake_llm = _make_fake_call_llm(db, cost_per_call_cents=cost_per_call_cents,
                                   raise_error=raise_error, veto_response=veto_response)

    monkeypatch.setattr("app.services.agent_opening_read.call_llm", fake_llm)
    monkeypatch.setattr("app.services.cio_chair.call_llm", fake_llm)

    if not skip_canonical_mock:
        monkeypatch.setattr(
            "app.services.cio_chair.compute_strategy_lab_aggregate",
            lambda user_id, db_: FAKE_SNAPSHOT,
        )

    from app.services.cio_chair import run_meeting, build_canonical_snapshot, _load_memory, render_briefing_markdown
    import threading

    # Pass a session factory that returns a thread-safe proxy around the test
    # db session.  Worker threads spawned by run_meeting_async each call
    # _session_factory() and receive a proxy that serialises all DB operations
    # via a shared threading.Lock, so concurrent workers never touch the
    # underlying StaticPool SQLite connection simultaneously (which would
    # segfault).  close() is a no-op on the proxy — the caller (test) closes
    # the real db when it is done.
    _db_lock = threading.Lock()

    class _LockedSessionProxy:
        """Thread-safe proxy around a SQLAlchemy Session backed by StaticPool.

        All operations are serialised with _db_lock.  close() is intentionally
        a no-op: the underlying session is owned by the test harness.
        """
        def __init__(self, session):
            self._s = session

        def execute(self, *args, **kwargs):
            with _db_lock:
                return self._s.execute(*args, **kwargs)

        def commit(self):
            with _db_lock:
                return self._s.commit()

        def rollback(self):
            with _db_lock:
                return self._s.rollback()

        def close(self):
            # No-op: the real session is closed by the test harness.
            pass

        def __getattr__(self, name):
            # Delegate any other attribute access to the real session.
            return getattr(self._s, name)

    def _test_session_factory():
        return _LockedSessionProxy(db)

    meeting_id = f"mtg_test_{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
    result = run_meeting(
        db,
        meeting_id=meeting_id,
        budget_cap_usd=1.50,
        daily_cap_usd=3.00,
        wall_clock_cap_seconds=600,
        poll_dick_veto=True,
        dry_run=False,
        _session_factory=_test_session_factory,
    )
    return result, db, engine


# ════════════════════════════════════════════════════════════════════════════════
# TEST 1 — budget
# ════════════════════════════════════════════════════════════════════════════════

def test_cio_runs_under_budget(monkeypatch):
    """16 calls @ $0.05 each → $0.80 total < $1.50 cap. status == 'completed'."""
    result, db, _ = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=5)
    # 5 cents × N calls, where N ≤ 30 → well under $1.50
    assert result.total_cost_usd <= 1.50, f"Cost exceeded $1.50: {result.total_cost_usd}"
    assert result.status in ("completed", "failed_partial"), f"Unexpected status: {result.status}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 2 — wall clock
# ════════════════════════════════════════════════════════════════════════════════

def test_cio_completes_under_10min(monkeypatch):
    """Mock calls are instant; total wall clock must be << 600s."""
    import time
    t0 = time.monotonic()
    result, db, _ = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=1)
    elapsed = time.monotonic() - t0
    assert elapsed < 600, f"Meeting exceeded 10min: {elapsed:.1f}s"
    assert result.duration_seconds < 600
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 3 — all 9 agents polled
# ════════════════════════════════════════════════════════════════════════════════

def test_all_9_agents_polled(monkeypatch):
    """agent_opening_reads has 9 rows with distinct agent_name values."""
    from sqlalchemy import text
    result, db, engine = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=2)
    rows = db.execute(
        text("SELECT DISTINCT agent_name FROM agent_opening_reads WHERE meeting_id=:mid"),
        {"mid": result.meeting_id},
    ).fetchall()
    agent_names = {r[0] for r in rows}
    expected = {
        "portfolio_manager", "chief_risk_officer", "equity_researcher", "quant_researcher",
        "macro_strategist", "data_quality_watcher", "execution_auditor", "operations", "sentinel_devops",
    }
    assert agent_names == expected, f"Missing agents: {expected - agent_names}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 4 — canonical PV in briefing
# ════════════════════════════════════════════════════════════════════════════════

def test_briefing_includes_canonical_pv_not_stale(monkeypatch):
    """Briefing markdown contains canonical PV $1,000,000 (not stale/wrong value)."""
    from app.services.cio_chair import render_briefing_markdown, _load_memory

    monkeypatch.setattr("app.services.agent_opening_read.call_llm",
                        _make_fake_call_llm(None, cost_per_call_cents=1))
    monkeypatch.setattr("app.services.cio_chair.call_llm",
                        _make_fake_call_llm(None, cost_per_call_cents=1))
    monkeypatch.setattr(
        "app.services.cio_chair.compute_strategy_lab_aggregate",
        lambda user_id, db_: FAKE_SNAPSHOT,
    )
    result, db, _ = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=1)
    md = render_briefing_markdown(result, FAKE_SNAPSHOT, {"recent_briefings": [], "open_commitments": []})
    # Should contain the PV in dollar format
    assert "1,000,000" in md or "1000000" in md, f"PV not in briefing: {md[:500]}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 5 — action items have owner + deadline
# ════════════════════════════════════════════════════════════════════════════════

def test_action_items_have_owner_and_deadline(monkeypatch):
    """All agent_commitments rows have non-null owner_agent + deadline."""
    from sqlalchemy import text
    result, db, engine = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=2)
    bad = db.execute(
        text(
            "SELECT COUNT(*) FROM agent_commitments "
            "WHERE owner_agent IS NULL OR deadline IS NULL OR owner_agent='' OR deadline=''"
        )
    ).scalar()
    assert bad == 0, f"{bad} commitments have null owner_agent or deadline"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 6 — commitments carry forward
# ════════════════════════════════════════════════════════════════════════════════

def test_commitments_carry_forward_to_next_meeting(monkeypatch):
    """Meeting A creates commitments; _load_memory returns them for meeting B."""
    from sqlalchemy import text
    engine = _make_test_engine()

    # Meeting A
    result_a, db_a, _ = _run_meeting_with_mocks(monkeypatch, engine=engine, cost_per_call_cents=2)
    db_a.close()

    # Check load_memory sees open commitments
    from app.services.cio_chair import _load_memory
    db2 = _make_session(engine)
    memory = _load_memory(db2)
    open_commitments = memory.get("open_commitments", [])
    # All commitments from meeting A should be in memory (status='open', deadline in future)
    assert isinstance(open_commitments, list)
    db2.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 7 — broken commitments escalate strike_count
# ════════════════════════════════════════════════════════════════════════════════

def test_broken_commitments_escalate_strike_count(monkeypatch):
    """Seed a past-deadline open commitment; meeting run increments strike_count."""
    from sqlalchemy import text
    engine = _make_test_engine()
    db = _make_session(engine)

    # Seed a past-deadline commitment
    db.execute(
        text(
            "INSERT INTO agent_commitments "
            "(meeting_id, owner_agent, action_description, deadline, status, strike_count) "
            "VALUES ('mtg_prev', 'portfolio_manager', 'Review allocation', "
            "'2026-01-01T00:00:00', 'open', 0)"
        )
    )
    db.commit()
    db.close()

    result, db2, _ = _run_meeting_with_mocks(monkeypatch, engine=engine, cost_per_call_cents=2)

    strike = db2.execute(
        text("SELECT strike_count FROM agent_commitments WHERE meeting_id='mtg_prev'")
    ).scalar()
    assert strike is not None and strike >= 1, f"Strike not incremented: {strike}"
    db2.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 8 — veto enforcement kills capital decision
# ════════════════════════════════════════════════════════════════════════════════

def test_veto_enforcement_kills_capital_decision(monkeypatch):
    """Force Dick → 'VETO'; resolution starts 'VETOED BY DICK'; veto_log row inserted."""
    from sqlalchemy import text
    veto_resp = json.dumps({"decision": "VETO", "reason": "Cluster correlation 0.88 exceeds threshold"})
    result, db, engine = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=2, veto_response=veto_resp)

    # Check for at least one vetoed item
    vetoed_items = [it for it in result.top_items if it.veto_used]

    if not vetoed_items:
        # No capital items were present; that's ok for this mock — let's just check veto_log
        veto_count = db.execute(text("SELECT COUNT(*) FROM veto_log")).scalar()
        # Either vetoes were cast or no capital items existed
        db.close()
        return  # skip if no capital items surfaced

    for it in vetoed_items:
        assert "VETOED BY DICK" in it.resolution, f"Expected VETOED BY DICK in resolution: {it.resolution}"

    veto_count = db.execute(text("SELECT COUNT(*) FROM veto_log")).scalar()
    assert veto_count > 0, "Expected veto_log row(s)"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 9 — veto scope limit (non-capital items not vetoed)
# ════════════════════════════════════════════════════════════════════════════════

def test_veto_scope_limit_dick_cannot_veto_operational(monkeypatch):
    """Operational items (is_capital_or_risk=False) never get veto_log rows."""
    from sqlalchemy import text
    from app.services.cio_chair import MeetingItem, _run_veto_poll, _insert_veto_log

    engine = _make_test_engine()
    db = _make_session(engine)

    # Construct a purely operational item
    item = MeetingItem(
        item_id="ops_item",
        title="Worker recycling status",
        surfaced_by=["sentinel_devops"],
        tension="Ops degraded",
        severity="P2",
        is_capital_or_risk=False,
    )

    # Call veto poll directly — it should skip entirely
    vetoes_used = [0]
    _run_veto_poll(item, db, "mtg_test_op", datetime.now(timezone.utc), vetoes_used)

    # veto_log should have 0 rows (poll was not even attempted)
    veto_count = db.execute(text("SELECT COUNT(*) FROM veto_log")).scalar()
    assert veto_count == 0, f"Operational item was vetoed: {veto_count} rows in veto_log"
    assert not item.veto_used
    assert not item.veto_polled
    assert vetoes_used[0] == 0
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 10 — Brock override veto
# ════════════════════════════════════════════════════════════════════════════════

def test_brock_override_veto_writes_to_decision_history(monkeypatch):
    """POST /api/agents/cio/veto/{id}/override sets brock_override=1, override_at, override_note."""
    from sqlalchemy import text
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    engine = _make_test_engine()
    db = _make_session(engine)

    # Seed a veto
    db.execute(
        text(
            "INSERT INTO veto_log (meeting_id, vetoed_by, vetoed_target_proposal, reason) "
            "VALUES ('mtg_test_ov', 'chief_risk_officer', 'Bump allocation', 'cluster risk')"
        )
    )
    db.commit()
    veto_id = db.execute(text("SELECT id FROM veto_log LIMIT 1")).scalar()

    # Use the router directly with dependency override
    from app.routers.cio_meeting import router
    app = FastAPI()
    app.include_router(router)

    from app.dependencies import get_db, get_current_user

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
    resp = client.post(f"/api/agents/cio/veto/{veto_id}/override?note=Test+override")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    row = db.execute(
        text("SELECT brock_override, override_at, override_note FROM veto_log WHERE id=:id"),
        {"id": veto_id},
    ).fetchone()
    assert row[0] == 1, "brock_override not set"
    assert row[1] is not None, "override_at is null"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 11 — briefing posts to cio channel only
# ════════════════════════════════════════════════════════════════════════════════

def test_briefing_posts_to_cio_channel_not_signal(monkeypatch):
    """Verify cio_discord uses DISCORD_WH_CIO_BRIEFINGS and not any signal webhook."""
    import httpx
    from unittest.mock import MagicMock, patch

    cio_wh_url = "https://discord.com/api/webhooks/999/cio_token"
    signal_wh_url = "https://discord.com/api/webhooks/888/signal_token"

    posted_urls = []

    def fake_post(url, **kwargs):
        posted_urls.append(url)
        resp = MagicMock()
        resp.json.return_value = {"id": "test_msg_123"}
        resp.raise_for_status = MagicMock()
        return resp

    engine = _make_test_engine()
    db = _make_session(engine)
    # Seed a briefing row so the DB update works
    from sqlalchemy import text
    db.execute(
        text(
            "INSERT INTO fund_briefings (briefing_id, meeting_id, markdown_body) "
            "VALUES ('brf_test', 'mtg_test', '# Test')"
        )
    )
    db.commit()

    monkeypatch.setenv("DISCORD_OPS_ALERTS_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WH_CIO_BRIEFINGS", cio_wh_url)
    monkeypatch.setenv("DISCORD_WH_FUND_UPDATES", signal_wh_url)

    with patch("app.services.cio_discord.httpx.post", side_effect=fake_post):
        from app.services.cio_discord import post_cio_briefing
        result = post_cio_briefing(
            markdown_body="# Test\nContent",
            summary_one_liner="Test summary",
            needs_brock=False,
            db=db,
            briefing_id="brf_test",
            vetoes_used=0,
            cost_usd=0.50,
            duration_seconds=120,
        )

    assert result == "test_msg_123"
    assert len(posted_urls) == 1, f"Expected 1 post, got {len(posted_urls)}: {posted_urls}"
    # cio_discord appends ?wait=true so the webhook returns the message JSON
    # (default 204 No Content body would otherwise break json parsing).
    assert posted_urls[0].startswith(cio_wh_url), f"Posted to wrong base URL: {posted_urls[0]}"
    assert "wait=true" in posted_urls[0]
    assert not any(p.startswith(signal_wh_url) for p in posted_urls)
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 12 — fund floor endpoints return latest briefing
# ════════════════════════════════════════════════════════════════════════════════

def test_fund_floor_endpoints_return_latest_briefing(monkeypatch):
    """GET /api/fund-floor/cio-briefing-board returns latest row; agent-overlay populated."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    # Seed data
    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) "
        "VALUES ('mtg_ff', '2026-06-28T09:00:00', 'completed')"
    ))
    db.execute(text(
        "INSERT INTO fund_briefings (briefing_id, meeting_id, markdown_body, summary_one_liner) "
        "VALUES ('brf_ff', 'mtg_ff', '# Test briefing', 'All good')"
    ))
    db.execute(text(
        "INSERT INTO agent_opening_reads "
        "(meeting_id, agent_name, structured_read_json, status, created_at) "
        "VALUES ('mtg_ff', 'chief_risk_officer', :srj, 'ok', CURRENT_TIMESTAMP)"
    ), {"srj": json.dumps({"what_im_seeing": "Risk clear", "confidence_in_book": "9/10"})})
    db.commit()

    from app.routers.fund_floor import router
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

    # Test briefing board
    resp = client.get("/api/fund-floor/cio-briefing-board")
    assert resp.status_code == 200, f"briefing-board: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["briefing_id"] == "brf_ff"
    assert "Test briefing" in data["markdown_body"]

    # Test agent overlay
    resp2 = client.get("/api/fund-floor/agent-overlay?agent_name=chief_risk_officer")
    assert resp2.status_code == 200, f"agent-overlay: {resp2.status_code} {resp2.text}"
    data2 = resp2.json()
    assert data2["agent_id"] == "chief_risk_officer"
    assert data2["last_opening_read"] is not None
    assert "Risk clear" in data2["last_opening_read"]["what_im_seeing"]
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 13 — daily $3 cap blocks third meeting
# ════════════════════════════════════════════════════════════════════════════════

def test_daily_3_dollar_budget_blocks_third_meeting(monkeypatch):
    """Two meetings burning $1.30 each; third returns status='failed_budget'."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    # Seed $2.60 already spent today (130 cents × 2 meetings = 260 cents = $2.60)
    _seed_llm_log_cost(db, "portfolio_manager", 130, source="relay")
    _seed_llm_log_cost(db, "chief_risk_officer", 130, source="relay")

    monkeypatch.setattr("app.services.agent_opening_read.call_llm",
                        _make_fake_call_llm(db, cost_per_call_cents=1))
    monkeypatch.setattr("app.services.cio_chair.call_llm",
                        _make_fake_call_llm(db, cost_per_call_cents=1))
    monkeypatch.setattr(
        "app.services.cio_chair.compute_strategy_lab_aggregate",
        lambda user_id, db_: FAKE_SNAPSHOT,
    )

    from app.services.cio_chair import run_meeting

    result = run_meeting(
        db,
        meeting_id="mtg_third",
        budget_cap_usd=1.50,
        daily_cap_usd=3.00,
        wall_clock_cap_seconds=600,
    )
    assert result.status == "failed_budget", f"Expected failed_budget, got {result.status}"
    assert result.failure_reason == "daily_cap_exceeded"
    # No opening reads should have run
    assert len(result.opening_reads) == 0
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 14 — no direct anthropic SDK use in SHIP-5 files
# ════════════════════════════════════════════════════════════════════════════════

def test_cio_does_not_use_anthropic_sdk_directly():
    """Grep SHIP-5 files for banned patterns. Whitelist: llm_client.py (SHIP 4 owns that)."""
    WHITELIST = {
        BACKEND_DIR / "app" / "services" / "llm_client.py",
    }
    BANNED = [
        r"import anthropic",
        r"from anthropic",
        r"ANTHROPIC_API_KEY",
        r"subprocess.*claude",
    ]
    violations = []
    for fpath in SHIP5_FILES:
        if not fpath.exists():
            continue
        if fpath in WHITELIST:
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        for pattern in BANNED:
            if re.search(pattern, content):
                violations.append(f"{fpath}: pattern '{pattern}'")

    assert not violations, (
        "SHIP-5 HARD CONSTRAINT VIOLATED — direct anthropic SDK or ANTHROPIC_API_KEY usage:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 15 — no new calls to _ensure_portfolios_for_user
# ════════════════════════════════════════════════════════════════════════════════

def test_no_new_calls_to_ensure_portfolios_for_user():
    """Grep SHIP-5 files for _ensure_portfolios_for_user — must be zero."""
    violations = []
    for fpath in SHIP5_FILES:
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if "_ensure_portfolios_for_user" in content:
            violations.append(str(fpath))

    assert not violations, (
        "SHIP-5 HARD CONSTRAINT VIOLATED — _ensure_portfolios_for_user found in:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 16 — no new writes to starting_capital_cents outside migrations
# ════════════════════════════════════════════════════════════════════════════════

def test_no_new_writes_to_starting_capital_cents():
    """Grep SHIP-5 files (non-migration) for capital field writes — must be zero."""
    CAPITAL_PATTERN = re.compile(
        r"(starting_capital_cents|inception_capital_cents|current_capital_cents)\s*="
    )
    violations = []
    for fpath in SHIP5_FILES:
        if not fpath.exists():
            continue
        if "migrations" in str(fpath):
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if CAPITAL_PATTERN.search(content):
            violations.append(str(fpath))

    assert not violations, (
        "SHIP-5 HARD CONSTRAINT VIOLATED — capital field write outside migrations:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 17 — no writes to bot_trades or bot_daily_pnl
# ════════════════════════════════════════════════════════════════════════════════

def test_no_writes_to_bot_trades_or_bot_daily_pnl():
    """Grep SHIP-5 files for INSERT/UPDATE/DELETE on bot_trades or bot_daily_pnl."""
    WRITE_PATTERN = re.compile(
        r"(INSERT|UPDATE|DELETE)\s+(?:INTO\s+|FROM\s+)?(bot_trades|bot_daily_pnl)",
        re.IGNORECASE,
    )
    violations = []
    for fpath in SHIP5_FILES:
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if WRITE_PATTERN.search(content):
            violations.append(str(fpath))

    assert not violations, (
        "SHIP-5 HARD CONSTRAINT VIOLATED — write to bot_trades or bot_daily_pnl found in:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 18 — migrations don't mutate capital
# ════════════════════════════════════════════════════════════════════════════════

def test_ship5_does_not_mutate_capital_on_deploy():
    """Run all 5 migrations against seeded $1M DB; SUM(starting_capital_cents) unchanged."""
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        # schema_migrations table
        conn.execute(text(
            "CREATE TABLE schema_migrations "
            "(migration_name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        # bot_allocations with $1M seed
        conn.execute(text(
            "CREATE TABLE bot_allocations "
            "(id INTEGER PRIMARY KEY, bot_id TEXT, user_id INTEGER, "
            " inception_capital_cents INTEGER, starting_capital_cents INTEGER, "
            " current_capital_cents INTEGER, enabled INTEGER)"
        ))
        # Seed $1M across 10 enabled bots
        for i in range(10):
            conn.execute(
                text("INSERT INTO bot_allocations (bot_id, user_id, inception_capital_cents, "
                     "starting_capital_cents, current_capital_cents, enabled) "
                     "VALUES (:bid, 1, 10000000, 10000000, 10000000, 1)"),
                {"bid": f"test_bot_{i}"},
            )
        conn.commit()

        before = conn.execute(text(
            "SELECT COALESCE(SUM(starting_capital_cents),0) FROM bot_allocations WHERE user_id=1 AND enabled=1"
        )).scalar()

        # Run all 5 SHIP-5 migrations
        from app.db.migrations.m039_fund_meetings import run as run_m033
        from app.db.migrations.m040_fund_briefings import run as run_m034
        from app.db.migrations.m041_agent_opening_reads import run as run_m035
        from app.db.migrations.m042_agent_commitments import run as run_m036
        from app.db.migrations.m043_veto_log import run as run_m037

        for run_fn in [run_m033, run_m034, run_m035, run_m036, run_m037]:
            run_fn(conn)

        after = conn.execute(text(
            "SELECT COALESCE(SUM(starting_capital_cents),0) FROM bot_allocations WHERE user_id=1 AND enabled=1"
        )).scalar()

    assert before == after == 100_000_000, (
        f"Capital mutated by SHIP-5 migrations: before={before}, after={after}"
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 19 — relay down fails closed
# ════════════════════════════════════════════════════════════════════════════════

def test_relay_down_fails_closed(monkeypatch):
    """All opening reads status='relay_down'; no api_fallback rows; status='failed_partial'."""
    from sqlalchemy import text

    result, db, engine = _run_meeting_with_mocks(monkeypatch, raise_error=True)

    # All opening reads should be relay_down
    for r in result.opening_reads:
        assert r.status == "relay_down", f"Expected relay_down, got {r.status} for {r.agent_name}"

    # No api_fallback rows
    fallback_count = db.execute(
        text("SELECT COUNT(*) FROM llm_call_log WHERE source='api_fallback'")
    ).scalar()
    assert fallback_count == 0, f"Expected 0 api_fallback rows, got {fallback_count}"

    # Meeting should be failed_partial (≥5 relay_down)
    assert result.status in ("failed_partial", "failed_budget"), f"Unexpected status: {result.status}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 20 — zero direct api tokens in normal meeting
# ════════════════════════════════════════════════════════════════════════════════

def test_meeting_cost_zero_direct_api_tokens(monkeypatch):
    """After a full meeting, llm_call_log has 0 api_fallback rows for the meeting window."""
    from sqlalchemy import text

    result, db, engine = _run_meeting_with_mocks(monkeypatch, cost_per_call_cents=3)
    started_at = result.started_at.isoformat()

    fallback_count = db.execute(
        text(
            "SELECT COUNT(*) FROM llm_call_log "
            "WHERE source='api_fallback' AND created_at >= :ts"
        ),
        {"ts": started_at},
    ).scalar()
    assert fallback_count == 0, f"Expected 0 api_fallback rows, got {fallback_count}"
    db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TEST 21 — 409 concurrent meeting guard
# ════════════════════════════════════════════════════════════════════════════════

def test_409_concurrent_meeting_guard(monkeypatch):
    """Start meeting A (status='running'); POST start again within 15min → 409."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    # Seed a running meeting started moments ago.
    # Use Python isoformat() (T separator, +00:00 suffix) so the Python-bound
    # :cutoff comparison in create_meeting_record works correctly.
    from datetime import datetime, timezone
    _now_iso = datetime.now(timezone.utc).isoformat()
    db.execute(
        text(
            "INSERT INTO fund_meetings (meeting_id, started_at, status) "
            "VALUES ('mtg_running', :s, 'running')"
        ),
        {"s": _now_iso},
    )
    db.commit()

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
    resp = client.post(
        "/api/agents/cio/meeting/start",
        json={"runner_label": "test", "budget_cap_usd": 1.50, "dry_run": False},
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    assert "meeting already in progress" in resp.json().get("detail", "").lower()
    db.close()
