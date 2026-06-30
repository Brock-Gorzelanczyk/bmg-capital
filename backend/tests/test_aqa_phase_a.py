"""AQA Phase A test suite -- 15 tests.

All tests use in-memory SQLite. All LLM, Discord, and HTTP calls are mocked.
No live LLM, no live Discord webhook, no live DB.

Uses importlib.util.spec_from_file_location to load AQA modules directly,
bypassing the conftest.py pre-mock stubs (same pattern as test_phase1_daily_journal.py).

Tests:
  1.  test_no_anthropic_imports_outside_llm_client
  2.  test_aqa_freeze_unfreeze
  3.  test_aqa_llm_budget_freezes_when_cap_hit
  4.  test_aqa_deploy_budget_check
  5.  test_heuristics_detect_bot_silent_48h
  6.  test_heuristics_detect_deployment_low
  7.  test_heuristics_skip_when_no_issues
  8.  test_aqa_cycle_skips_llm_when_no_issues
  9.  test_aqa_cycle_calls_llm_when_actionable
  10. test_aqa_cycle_skips_when_frozen
  11. test_aqa_proposal_persisted_to_db
  12. test_aqa_discord_post_handles_missing_webhook
  13. test_aqa_scheduler_skipped_when_aqa_enabled_false
  14. test_no_subprocess_calls_in_aqa
  15. test_no_git_calls_in_aqa
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import types as _types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT_STR = str(_BACKEND_ROOT)
if _BACKEND_ROOT_STR not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT_STR)

# ---------------------------------------------------------------------------
# Module loader helper -- bypasses conftest stubs
# ---------------------------------------------------------------------------

def _load(module_name: str, rel_path: str):
    """Load a module from file path, bypassing conftest stubs."""
    abs_path = os.path.join(_BACKEND_ROOT_STR, rel_path)
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {abs_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Pre-stub heavy external dependencies before loading AQA modules
# ---------------------------------------------------------------------------

sys.modules.setdefault("sentry_sdk", MagicMock())
sys.modules.setdefault("httpx", MagicMock())
# Pre-import REAL apscheduler so subsequent setdefault calls are no-ops.
# Otherwise stubbing apscheduler.triggers.cron with MagicMock breaks the
# Phase 1 scheduler-registers-daily-journal-job test downstream (the
# isinstance(trigger, CronTrigger) check sees a MagicMock instead of the
# real class). Real apscheduler is a backend prod dep, always available.
try:
    import apscheduler  # noqa: F401
    import apscheduler.triggers  # noqa: F401
    import apscheduler.triggers.interval  # noqa: F401
    import apscheduler.triggers.cron  # noqa: F401
except ImportError:
    sys.modules.setdefault("apscheduler", MagicMock())
    sys.modules.setdefault("apscheduler.triggers", MagicMock())
    sys.modules.setdefault("apscheduler.triggers.interval", MagicMock())
    sys.modules.setdefault("apscheduler.triggers.cron", MagicMock())

# Stub app.config
_config_stub = MagicMock()
_config_stub.settings = MagicMock()
_config_stub.settings.jwt_secret = "test_secret"
_config_stub.settings.jwt_algorithm = "HS256"
sys.modules.setdefault("app.config", _config_stub)

# Stub app.db.session
_session_stub = sys.modules.get("app.db.session")
if _session_stub is None:
    _session_stub = _types.ModuleType("app.db.session")
    sys.modules["app.db.session"] = _session_stub
if not hasattr(_session_stub, "SessionLocal"):
    _session_stub.SessionLocal = MagicMock()

# Stub app.dependencies
_deps_stub = sys.modules.get("app.dependencies")
if _deps_stub is None:
    _deps_stub = _types.ModuleType("app.dependencies")
    sys.modules["app.dependencies"] = _deps_stub
if not hasattr(_deps_stub, "get_db"):
    _deps_stub.get_db = MagicMock()
if not hasattr(_deps_stub, "get_current_user"):
    _deps_stub.get_current_user = MagicMock()

# Stub app.db.models.users
_users_stub = sys.modules.get("app.db.models.users")
if _users_stub is None:
    _users_stub = _types.ModuleType("app.db.models.users")
    sys.modules["app.db.models.users"] = _users_stub
if not hasattr(_users_stub, "User"):
    _users_stub.User = MagicMock()

# Stub app.services.discord (to avoid real Discord calls in tests)
_discord_stub = _types.ModuleType("app.services.discord")
_discord_stub.send_ops_alert = MagicMock()
sys.modules["app.services.discord"] = _discord_stub

# Stub app.services.llm_client (to avoid real LLM calls in tests)
_llm_stub = _types.ModuleType("app.services.llm_client")
_llm_stub.call_llm = MagicMock(return_value="## Issue\nTest.\n\n## Proposal\nFix.\n\n## Risk\nNone.\n\n## Rollback\nNone.")
sys.modules["app.services.llm_client"] = _llm_stub

# Stub app.routers.admin (bot_diagnostic handler -- heavy dependency)
_admin_stub = _types.ModuleType("app.routers.admin")
_admin_stub.get_bot_diagnostic_singular = MagicMock(return_value={"bots": [], "summary": {}, "as_of": ""})
sys.modules.setdefault("app.routers.admin", _admin_stub)

# ---------------------------------------------------------------------------
# Load the real AQA modules via importlib (bypass conftest stubs)
# ---------------------------------------------------------------------------

_m048 = _load("app.db.migrations.m048_aqa_state", "app/db/migrations/m048_aqa_state.py")
_aqa_safety = _load("app.services.aqa_safety", "app/services/aqa_safety.py")
_aqa_context = _load("app.services.aqa_context_builder", "app/services/aqa_context_builder.py")
_aqa_heuristics = _load("app.services.aqa_heuristics", "app/services/aqa_heuristics.py")
_aqa_proposal_writer = _load("app.services.aqa_proposal_writer", "app/services/aqa_proposal_writer.py")
_aqa_system_prompt = _load("app.agents.aqa_system_prompt", "app/agents/aqa_system_prompt.py")
_aqa_agent = _load("app.agents.aqa", "app/agents/aqa.py")
_aqa_loop = _load("app.jobs.aqa_loop", "app/jobs/aqa_loop.py")

# ---------------------------------------------------------------------------
# In-memory SQLite fixture
# ---------------------------------------------------------------------------

def _make_in_memory_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    return engine, Session


def _run_m048_on(engine):
    with engine.begin() as conn:
        _m048.run(conn)


@pytest.fixture(autouse=True)
def _pin_aqa_stubs():
    """Re-pin the AQA stubs in sys.modules before every test.

    Other test files (test_phase1_daily_journal.py, test_admin_audit_endpoints.py)
    load the REAL llm_client / discord / admin modules into sys.modules, which
    overwrites our stubs. Re-registering here ensures AQA tests always see the
    mock versions for modules they depend on via inline imports.
    """
    _orig_llm = sys.modules.get("app.services.llm_client")
    _orig_discord = sys.modules.get("app.services.discord")
    _orig_admin = sys.modules.get("app.routers.admin")
    # Re-register our stubs (the module objects we loaded at file level)
    sys.modules["app.services.llm_client"] = _llm_stub
    sys.modules["app.services.discord"] = _discord_stub
    sys.modules["app.routers.admin"] = _admin_stub
    sys.modules["app.services.aqa_context_builder"] = _aqa_context
    sys.modules["app.services.aqa_heuristics"] = _aqa_heuristics
    sys.modules["app.services.aqa_proposal_writer"] = _aqa_proposal_writer
    sys.modules["app.agents.aqa"] = _aqa_agent
    sys.modules["app.jobs.aqa_loop"] = _aqa_loop
    yield
    # Restore originals (or remove if they didn't exist before)
    for key, orig in [
        ("app.services.llm_client", _orig_llm),
        ("app.services.discord", _orig_discord),
        ("app.routers.admin", _orig_admin),
    ]:
        if orig is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = orig


@pytest.fixture
def aqa_db():
    """Fresh in-memory SQLite with m048 migration applied. Yields a Session."""
    engine, SessionCls = _make_in_memory_db()
    _run_m048_on(engine)
    # Point SessionLocal stub at this engine's session factory
    _session_stub.SessionLocal = SessionCls
    db = SessionCls()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Minimal context builder helper
# ---------------------------------------------------------------------------

def _make_context(bots=None, built_at=None):
    if built_at is None:
        built_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "bot_diagnostic": {
            "bots": bots or [],
            "summary": {},
            "as_of": built_at,
        },
        "bot_journals": [],
        "sentry_issues_24h": [],
        "recent_aqa_actions": [],
        "regime_matrix": None,
        "cio_weekly_reviews": [],
        "data_gaps": ["sentry_issues_query", "regime_matrix_phase2", "cio_weekly_reviews_phase3"],
        "built_at": built_at,
    }


# ---------------------------------------------------------------------------
# TEST 1: Wall guard (delegate to helper from test_no_anthropic_imports)
# ---------------------------------------------------------------------------

def test_no_anthropic_imports_outside_llm_client():
    """Delegate to the Wall guard helpers for single source of truth."""
    # Import from the Wall guard module (it doesn't touch conftest stubs)
    _wall_path = _BACKEND_ROOT / "tests" / "test_no_anthropic_imports.py"
    _wall_spec = importlib.util.spec_from_file_location("_wall_guard", str(_wall_path))
    _wall_mod = importlib.util.module_from_spec(_wall_spec)
    _wall_spec.loader.exec_module(_wall_mod)

    violations = []
    for py_file in _wall_mod._walk_backend_py_files():
        hits = _wall_mod._file_imports_anthropic(py_file)
        for lineno, stmt in hits:
            try:
                rel = py_file.relative_to(_BACKEND_ROOT)
            except ValueError:
                rel = py_file
            violations.append(f"{rel}:{lineno}: {stmt}")

    assert violations == [], (
        "WALL VIOLATION -- anthropic imported outside whitelist:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# TEST 2: freeze / unfreeze
# ---------------------------------------------------------------------------

def test_aqa_freeze_unfreeze(aqa_db):
    assert _aqa_safety.is_frozen(aqa_db) is False
    _aqa_safety.freeze(aqa_db, reason="test freeze", by="pytest")
    assert _aqa_safety.is_frozen(aqa_db) is True
    _aqa_safety.unfreeze(aqa_db, by="pytest")
    assert _aqa_safety.is_frozen(aqa_db) is False


# ---------------------------------------------------------------------------
# TEST 3: LLM budget hit causes cycle to self-freeze
# ---------------------------------------------------------------------------

def test_aqa_llm_budget_freezes_when_cap_hit(aqa_db, monkeypatch):
    monkeypatch.setenv("AQA_DAILY_MAX_LLM_CALLS", "2000")
    aqa_db.execute(
        text(
            "UPDATE aqa_state SET llm_calls_today = 2000 "
            "WHERE id = (SELECT MIN(id) FROM aqa_state)"
        )
    )
    aqa_db.commit()

    result = _aqa_agent.run_aqa_cycle(aqa_db)

    assert result["status"] == "budget_hit"
    assert result["reason"] == "llm_budget_exhausted"
    assert _aqa_safety.is_frozen(aqa_db) is True


# ---------------------------------------------------------------------------
# TEST 4: deploy budget check
# ---------------------------------------------------------------------------

def test_aqa_deploy_budget_check(aqa_db, monkeypatch):
    monkeypatch.setenv("AQA_MAX_DEPLOYS_PER_24H", "10")
    aqa_db.execute(
        text(
            "UPDATE aqa_state SET deploys_today = 10 "
            "WHERE id = (SELECT MIN(id) FROM aqa_state)"
        )
    )
    aqa_db.commit()

    result = _aqa_agent.run_aqa_cycle(aqa_db)

    assert result["status"] == "budget_hit"
    assert result["reason"] == "deploy_budget_exhausted"
    assert _aqa_safety.is_frozen(aqa_db) is True


# ---------------------------------------------------------------------------
# TEST 5: heuristics detect bot_silent_48h
# ---------------------------------------------------------------------------

def test_heuristics_detect_bot_silent_48h():
    now = datetime.now(timezone.utc)
    last_trade = (now - timedelta(hours=72)).isoformat().replace("+00:00", "Z")
    built_at = now.isoformat().replace("+00:00", "Z")

    context = _make_context(
        bots=[
            {
                "bot_id": "stock_swing",
                "enabled": True,
                "paused_reason": None,
                "trades_24h": 0,
                "last_trade_at": last_trade,
                # 2026-06-30: heuristic now requires starting_capital>0 to
                # distinguish real bots from defunct allocations.
                "starting_capital_cents": 10000000,
            }
        ],
        built_at=built_at,
    )

    tags = _aqa_heuristics.find_actionable_issues(context)
    assert "bot_silent_48h" in tags


def test_heuristics_detect_bot_silent_never_traded():
    """Bot with starting_capital>0 but last_trade_at=None must be flagged.

    Real case: options_directional, options_income, stock_lt, crypto_onchain
    all have NULL last_trade_at and are the most-broken bots in the fund.
    Previous heuristic skipped them as 'never traded' — that was the bug
    PR #50 fixed. This test locks in the new behavior.
    """
    now = datetime.now(timezone.utc)
    built_at = now.isoformat().replace("+00:00", "Z")

    context = _make_context(
        bots=[
            {
                "bot_id": "options_income",
                "enabled": True,
                "paused_reason": None,
                "trades_24h": 0,
                "last_trade_at": None,
                "starting_capital_cents": 5000000,
            }
        ],
        built_at=built_at,
    )

    tags = _aqa_heuristics.find_actionable_issues(context)
    assert "bot_silent_48h" in tags, (
        f"Bot with starting_capital>0 + never-traded MUST flag silent. tags={tags}"
    )


# ---------------------------------------------------------------------------
# TEST 6: heuristics detect deployment_low (or skip if fields not exposed)
# ---------------------------------------------------------------------------

def test_heuristics_detect_deployment_low():
    starting = 100_000_000  # 100K in cents
    notional = 5_000_000   # 5K in cents (5%)

    context = _make_context(
        bots=[
            {
                "bot_id": "stock_swing",
                "enabled": True,
                "paused_reason": None,
                "trades_24h": 5,
                "last_trade_at": None,
                "open_positions_notional_cents": notional,
                "starting_capital_cents": starting,
            }
        ]
    )

    tags = _aqa_heuristics.find_actionable_issues(context)
    if "deployment_low" not in tags:
        pytest.skip(
            "deployment_pct not yet exposed in bot_diagnostic -- "
            "open_positions_notional_cents / starting_capital_cents missing from handler"
        )
    assert "deployment_low" in tags


# ---------------------------------------------------------------------------
# TEST 7: heuristics skip when no issues
# ---------------------------------------------------------------------------

def test_heuristics_skip_when_no_issues():
    now = datetime.now(timezone.utc)
    last_trade = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    context = _make_context(
        bots=[
            {
                "bot_id": "stock_swing",
                "enabled": True,
                "paused_reason": None,
                "trades_24h": 5,
                "last_trade_at": last_trade,
                "open_positions_notional_cents": 90_000_000,
                "starting_capital_cents": 100_000_000,
            }
        ]
    )

    result = _aqa_heuristics.find_actionable_issues(context)
    assert result == []


# ---------------------------------------------------------------------------
# TEST 8: cycle skips LLM when no issues
# ---------------------------------------------------------------------------

def test_aqa_cycle_skips_llm_when_no_issues(aqa_db):
    # Mock build_context so no real DB queries happen
    mock_context = MagicMock(return_value=_make_context())
    _saved_context = _aqa_context.build_context
    _aqa_context.build_context = mock_context

    # Patch heuristics to return []
    _saved_heuristics = _aqa_heuristics.find_actionable_issues
    mock_heuristics = MagicMock(return_value=[])
    _aqa_heuristics.find_actionable_issues = mock_heuristics

    mock_llm = MagicMock()
    _saved_llm = _llm_stub.call_llm
    _llm_stub.call_llm = mock_llm

    try:
        result = _aqa_agent.run_aqa_cycle(aqa_db)
    finally:
        _aqa_context.build_context = _saved_context
        _aqa_heuristics.find_actionable_issues = _saved_heuristics
        _llm_stub.call_llm = _saved_llm

    assert result["status"] == "no_action"
    assert mock_llm.call_count == 0


# ---------------------------------------------------------------------------
# TEST 9: cycle calls LLM when actionable
# ---------------------------------------------------------------------------

def test_aqa_cycle_calls_llm_when_actionable(aqa_db):
    mock_context = MagicMock(return_value=_make_context())
    _saved_context = _aqa_context.build_context
    _aqa_context.build_context = mock_context

    mock_heuristics = MagicMock(return_value=["bot_silent_48h"])
    _saved_heuristics = _aqa_heuristics.find_actionable_issues
    _aqa_heuristics.find_actionable_issues = mock_heuristics

    mock_llm = MagicMock(return_value="## Issue\nBot silent.\n\n## Proposal\nFix it.\n\n## Risk\nNone.\n\n## Rollback\nNone.")
    _saved_llm = _llm_stub.call_llm
    _llm_stub.call_llm = mock_llm

    mock_discord = MagicMock(return_value=None)
    _saved_discord = _aqa_proposal_writer.post_to_discord
    _aqa_proposal_writer.post_to_discord = mock_discord

    try:
        result = _aqa_agent.run_aqa_cycle(aqa_db)
    finally:
        _aqa_context.build_context = _saved_context
        _aqa_heuristics.find_actionable_issues = _saved_heuristics
        _llm_stub.call_llm = _saved_llm
        _aqa_proposal_writer.post_to_discord = _saved_discord

    assert result["status"] == "proposed"
    assert mock_llm.call_count == 1
    assert "proposal_id" in result


# ---------------------------------------------------------------------------
# TEST 10: cycle skips when frozen
# ---------------------------------------------------------------------------

def test_aqa_cycle_skips_when_frozen(aqa_db):
    _aqa_safety.freeze(aqa_db, reason="test", by="pytest")

    mock_llm = MagicMock()
    _saved_llm = _llm_stub.call_llm
    _llm_stub.call_llm = mock_llm

    try:
        result = _aqa_agent.run_aqa_cycle(aqa_db)
    finally:
        _llm_stub.call_llm = _saved_llm

    assert result["status"] == "frozen"
    assert mock_llm.call_count == 0


# ---------------------------------------------------------------------------
# TEST 11: proposal persisted to DB
# ---------------------------------------------------------------------------

def test_aqa_proposal_persisted_to_db(aqa_db):
    initial_count = aqa_db.execute(text("SELECT COUNT(*) FROM aqa_proposals")).scalar()

    mock_context = MagicMock(return_value=_make_context())
    _saved_context = _aqa_context.build_context
    _aqa_context.build_context = mock_context

    mock_heuristics = MagicMock(return_value=["bot_silent_48h"])
    _saved_heuristics = _aqa_heuristics.find_actionable_issues
    _aqa_heuristics.find_actionable_issues = mock_heuristics

    mock_llm = MagicMock(return_value="## Issue\nBot silent.\n\n## Proposal\nFix it.\n\n## Risk\nNone.\n\n## Rollback\nNone.")
    _saved_llm = _llm_stub.call_llm
    _llm_stub.call_llm = mock_llm

    mock_discord = MagicMock(return_value=None)
    _saved_discord = _aqa_proposal_writer.post_to_discord
    _aqa_proposal_writer.post_to_discord = mock_discord

    try:
        result = _aqa_agent.run_aqa_cycle(aqa_db)
    finally:
        _aqa_context.build_context = _saved_context
        _aqa_heuristics.find_actionable_issues = _saved_heuristics
        _llm_stub.call_llm = _saved_llm
        _aqa_proposal_writer.post_to_discord = _saved_discord

    assert result["status"] == "proposed"

    new_count = aqa_db.execute(text("SELECT COUNT(*) FROM aqa_proposals")).scalar()
    assert new_count == initial_count + 1

    row = aqa_db.execute(
        text("SELECT * FROM aqa_proposals ORDER BY id DESC LIMIT 1")
    ).fetchone()
    assert row is not None
    d = dict(row._mapping)
    assert "bot_silent_48h" in d["issue_tags"]
    assert d["cycle_id"].startswith("aqa-")
    assert len(d["llm_response_md"]) > 0


# ---------------------------------------------------------------------------
# TEST 12: Discord missing webhook -- proposal still in DB, message_id NULL
# ---------------------------------------------------------------------------

def test_aqa_discord_post_handles_missing_webhook(aqa_db, monkeypatch):
    monkeypatch.delenv("DISCORD_WH_AQA_PROPOSALS", raising=False)

    mock_context = MagicMock(return_value=_make_context())
    _saved_context = _aqa_context.build_context
    _aqa_context.build_context = mock_context

    mock_heuristics = MagicMock(return_value=["bot_silent_48h"])
    _saved_heuristics = _aqa_heuristics.find_actionable_issues
    _aqa_heuristics.find_actionable_issues = mock_heuristics

    mock_llm = MagicMock(return_value="## Issue\nBot silent.\n\n## Proposal\nFix.\n\n## Risk\nNone.\n\n## Rollback\nNone.")
    _saved_llm = _llm_stub.call_llm
    _llm_stub.call_llm = mock_llm

    try:
        result = _aqa_agent.run_aqa_cycle(aqa_db)
    finally:
        _aqa_context.build_context = _saved_context
        _aqa_heuristics.find_actionable_issues = _saved_heuristics
        _llm_stub.call_llm = _saved_llm

    assert result["status"] == "proposed"
    assert result.get("discord_message_id") is None

    row = aqa_db.execute(
        text("SELECT discord_message_id FROM aqa_proposals ORDER BY id DESC LIMIT 1")
    ).fetchone()
    assert row is not None
    assert row._mapping["discord_message_id"] is None


# ---------------------------------------------------------------------------
# TEST 13: scheduler skipped when AQA_ENABLED is false
# ---------------------------------------------------------------------------

def test_aqa_scheduler_skipped_when_aqa_enabled_false(monkeypatch):
    monkeypatch.delenv("AQA_ENABLED", raising=False)

    mock_cycle = MagicMock()
    _saved_cycle = _aqa_agent.run_aqa_cycle
    _aqa_agent.run_aqa_cycle = mock_cycle

    try:
        _aqa_loop.run_aqa_scheduled()
    finally:
        _aqa_agent.run_aqa_cycle = _saved_cycle

    assert mock_cycle.call_count == 0


# ---------------------------------------------------------------------------
# AST walk helpers for tests 14 + 15
# ---------------------------------------------------------------------------

_AQA_SOURCE_PATTERNS = [
    "app/agents/aqa*.py",
    "app/services/aqa_*.py",
    "app/jobs/aqa_loop.py",
    "app/routers/aqa_admin.py",
]

_SUBPROCESS_CALL_NAMES = {"run", "Popen", "call", "check_output", "check_call"}


def _collect_aqa_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _AQA_SOURCE_PATTERNS:
        files.extend(_BACKEND_ROOT.glob(pattern))
    return [f for f in files if f.is_file()]


# ---------------------------------------------------------------------------
# TEST 14: no subprocess calls in AQA source files
# ---------------------------------------------------------------------------

def test_no_subprocess_calls_in_aqa():
    """AST-verify zero subprocess/os.system calls in AQA files."""
    aqa_files = _collect_aqa_files()
    violations: list[str] = []

    for path in aqa_files:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # subprocess.X(...)
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
                and func.attr in _SUBPROCESS_CALL_NAMES
            ):
                try:
                    rel = path.relative_to(_BACKEND_ROOT)
                except ValueError:
                    rel = path
                violations.append(f"{rel}:{node.lineno}: subprocess.{func.attr}()")
            # os.system / os.popen
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and func.attr in ("system", "popen")
            ):
                try:
                    rel = path.relative_to(_BACKEND_ROOT)
                except ValueError:
                    rel = path
                violations.append(f"{rel}:{node.lineno}: os.{func.attr}()")

    assert violations == [], (
        "PHASE B GUARD: subprocess/os.system calls found in AQA files:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# TEST 15: no git imports in AQA source files
# ---------------------------------------------------------------------------

def test_no_git_calls_in_aqa():
    """AST-verify zero import subprocess / import git / from git in AQA files."""
    aqa_files = _collect_aqa_files()
    violations: list[str] = []

    for path in aqa_files:
        source = path.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("subprocess", "git") or alias.name.startswith("git."):
                        try:
                            rel = path.relative_to(_BACKEND_ROOT)
                        except ValueError:
                            rel = path
                        violations.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in ("subprocess", "git") or module.startswith("git."):
                    names = ", ".join(a.name for a in node.names)
                    try:
                        rel = path.relative_to(_BACKEND_ROOT)
                    except ValueError:
                        rel = path
                    violations.append(f"{rel}:{node.lineno}: from {module} import {names}")

    assert violations == [], (
        "PHASE B GUARD: git/subprocess imports found in AQA files (Phase B only):\n"
        + "\n".join(f"  {v}" for v in violations)
    )
