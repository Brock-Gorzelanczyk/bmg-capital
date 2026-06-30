"""CIO Observability tests (8 tests).

Covers:
  1. test_relay_error_message_includes_exception_type
  2. test_relay_error_includes_readtimeout_type
  3. test_relay_error_includes_remoteprotocolerror_type
  4. test_last_meeting_agents_endpoint_returns_latest
  5. test_last_meeting_agents_endpoint_with_meeting_id
  6. test_last_meeting_agents_endpoint_failure_types_parsed
  7. test_meeting_alert_fires_on_failed_partial
  8. test_meeting_alert_never_raises
"""
from __future__ import annotations

import importlib.util as _ilu
import logging
import os
import pathlib
import sys
import types
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BACKEND = str(pathlib.Path(__file__).resolve().parents[1])
_LLM_CLIENT_PATH = os.path.join(_BACKEND, "app", "services", "llm_client.py")
_RUNNER_PATH = os.path.join(_BACKEND, "app", "services", "cio_meeting_runner.py")
_ADMIN_ROUTER_PATH = os.path.join(_BACKEND, "app", "routers", "admin.py")

_LLM_MOD_NAME = "app.services.llm_client"
_RUNNER_MOD_NAME = "app.services.cio_meeting_runner"
_ADMIN_MOD_NAME = "app.routers.admin"


# ---------------------------------------------------------------------------
# Bootstrap utilities
# ---------------------------------------------------------------------------

def _ensure_stub(name: str):
    """Ensure a bare stub module exists in sys.modules under `name`."""
    if name not in sys.modules:
        stub = types.ModuleType(name)
        stub.__spec__ = None
        sys.modules[name] = stub
    return sys.modules[name]


def _load_real(module_name: str, abs_path: str):
    """Load a source file and register it in sys.modules."""
    if module_name in sys.modules and hasattr(sys.modules[module_name], "__file__"):
        mod = sys.modules[module_name]
        # Check for a sentinel that the real module has
        return mod

    spec = _ilu.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {abs_path}")
    mod = _ilu.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    # Wire onto parent stub
    parts = module_name.split(".")
    if len(parts) > 1:
        parent_name = ".".join(parts[:-1])
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, parts[-1], mod)
    return mod


# ---------------------------------------------------------------------------
# Bootstrap: stubs for service dependencies (run once at import time)
# ---------------------------------------------------------------------------

# Ensure app.services stub
_ensure_stub("app")
_ensure_stub("app.services")

# discord stub
_discord_stub = _ensure_stub("app.services.discord")
if not hasattr(_discord_stub, "send_ops_alert"):
    _discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")
setattr(sys.modules["app.services"], "discord", _discord_stub)

# app.db.session stub — needs get_db and SessionLocal
_db_session_stub = _ensure_stub("app.db.session")
if not hasattr(_db_session_stub, "SessionLocal"):
    _db_session_stub.SessionLocal = MagicMock(name="SessionLocal")
if not hasattr(_db_session_stub, "get_db"):
    _db_session_stub.get_db = MagicMock(name="get_db")

# app.db.models.users stub — needs User
_ensure_stub("app.db")
_ensure_stub("app.db.models")
_users_stub = _ensure_stub("app.db.models.users")
if not hasattr(_users_stub, "User"):
    class _User:
        def __init__(self, id=1, is_active=True):
            self.id = id
            self.is_active = is_active
    _users_stub.User = _User

# app.dependencies stub — needs get_current_user and require_admin
_deps_stub = _ensure_stub("app.dependencies")
if not hasattr(_deps_stub, "get_current_user"):
    _deps_stub.get_current_user = MagicMock(name="get_current_user")
if not hasattr(_deps_stub, "require_admin"):
    _deps_stub.require_admin = MagicMock(name="require_admin")

# app.routers stub
_ensure_stub("app.routers")


# ---------------------------------------------------------------------------
# Load real llm_client
# ---------------------------------------------------------------------------

def _load_real_llm_client():
    if _LLM_MOD_NAME in sys.modules and hasattr(sys.modules[_LLM_MOD_NAME], "_post_to_relay"):
        return sys.modules[_LLM_MOD_NAME]
    return _load_real(_LLM_MOD_NAME, _LLM_CLIENT_PATH)


_llm_client_mod = _load_real_llm_client()


# ---------------------------------------------------------------------------
# Load real cio_meeting_runner
# ---------------------------------------------------------------------------

def _load_real_runner():
    if _RUNNER_MOD_NAME in sys.modules and hasattr(sys.modules[_RUNNER_MOD_NAME], "_send_meeting_alert"):
        return sys.modules[_RUNNER_MOD_NAME]
    return _load_real(_RUNNER_MOD_NAME, _RUNNER_PATH)


_runner_mod = _load_real_runner()


# ---------------------------------------------------------------------------
# Load real admin router
# ---------------------------------------------------------------------------

def _load_admin_router():
    if _ADMIN_MOD_NAME in sys.modules and hasattr(sys.modules[_ADMIN_MOD_NAME], "cio_last_meeting_agents"):
        return sys.modules[_ADMIN_MOD_NAME]
    return _load_real(_ADMIN_MOD_NAME, _ADMIN_ROUTER_PATH)


_admin_mod = _load_admin_router()


# ---------------------------------------------------------------------------
# Helpers shared across relay tests
# ---------------------------------------------------------------------------

def _make_mock_client(post_mock):
    """Build a mock that works as a context manager for httpx.Client(timeout=60)."""
    inner = MagicMock()
    inner.post = post_mock
    outer = MagicMock()
    outer.__enter__ = MagicMock(return_value=inner)
    outer.__exit__ = MagicMock(return_value=False)
    return outer


# ---------------------------------------------------------------------------
# Helpers for admin endpoint tests
# ---------------------------------------------------------------------------

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
            "CREATE TABLE IF NOT EXISTS fund_meetings "
            "(meeting_id TEXT PRIMARY KEY, started_at TIMESTAMP NOT NULL, "
            " ended_at TIMESTAMP, duration_seconds INTEGER, model_cost_usd REAL NOT NULL DEFAULT 0.0, "
            " briefing_id TEXT, vetoes_used INTEGER NOT NULL DEFAULT 0, "
            " status TEXT NOT NULL DEFAULT 'running', failure_reason TEXT, created_by_runner TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS agent_opening_reads "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL, "
            " agent_name TEXT NOT NULL, structured_read_json TEXT NOT NULL DEFAULT '{}', "
            " response_time_ms INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0.0, "
            " status TEXT NOT NULL, error_text TEXT, "
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            " UNIQUE(meeting_id, agent_name))"
        ))
        conn.commit()
    return engine


def _make_session(engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    return Session()


def _make_test_client(db):
    """Build a TestClient with admin router, overriding db and current_user."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # We need to import get_db and get_current_user from the stubs so
    # dependency_overrides targets the right callable objects.
    from app.db.session import get_db
    from app.dependencies import get_current_user

    app = FastAPI()
    app.include_router(_admin_mod.router)

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


# ---------------------------------------------------------------------------
# Tests 1-3 — relay error message includes exception type
# ---------------------------------------------------------------------------

def test_relay_error_message_includes_exception_type(monkeypatch):
    """RuntimeError message must include 'ConnectError:' after 3 failed attempts."""
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    post_mock = MagicMock(side_effect=httpx.ConnectError("Connection refused"))
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time"):
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError

        with pytest.raises(RuntimeError, match="ConnectError:"):
            _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert post_mock.call_count == 3


def test_relay_error_includes_readtimeout_type(monkeypatch):
    """RuntimeError message must include 'ReadTimeout:' after 3 failed attempts."""
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    post_mock = MagicMock(side_effect=httpx.ReadTimeout("timed out"))
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time"):
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError

        with pytest.raises(RuntimeError, match="ReadTimeout:"):
            _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert post_mock.call_count == 3


def test_relay_error_includes_remoteprotocolerror_type(monkeypatch):
    """RuntimeError message must include 'RemoteProtocolError:' after 3 failed attempts."""
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    post_mock = MagicMock(
        side_effect=httpx.RemoteProtocolError("Server disconnected without sending a response.")
    )
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time"):
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError

        with pytest.raises(RuntimeError, match="RemoteProtocolError:"):
            _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert post_mock.call_count == 3


# ---------------------------------------------------------------------------
# Tests 4-6 — admin endpoint /api/admin/cio/last-meeting-agents
# ---------------------------------------------------------------------------

def test_last_meeting_agents_endpoint_returns_latest():
    """GET /api/admin/cio/last-meeting-agents returns the most recent meeting."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    earlier_id = "mtg_earlier_001"
    later_id = "mtg_later_002"

    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) VALUES (:m, :s, 'completed')"
    ), {"m": earlier_id, "s": "2026-06-29T05:00:00+00:00"})
    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) VALUES (:m, :s, 'completed')"
    ), {"m": later_id, "s": "2026-06-29T06:00:00+00:00"})
    db.execute(text(
        "INSERT INTO agent_opening_reads (meeting_id, agent_name, status, response_time_ms, cost_usd) "
        "VALUES (:m, 'chief_risk_officer', 'ok', 500, 0.01)"
    ), {"m": earlier_id})
    db.execute(text(
        "INSERT INTO agent_opening_reads (meeting_id, agent_name, status, response_time_ms, cost_usd) "
        "VALUES (:m, 'chief_risk_officer', 'ok', 600, 0.01)"
    ), {"m": later_id})
    db.commit()

    client = _make_test_client(db)
    resp = client.get("/api/admin/cio/last-meeting-agents")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["meeting_id"] == later_id, f"Expected {later_id}, got {data['meeting_id']}"
    db.close()


def test_last_meeting_agents_endpoint_with_meeting_id():
    """GET /api/admin/cio/last-meeting-agents?meeting_id=<earlier> returns the earlier meeting."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    earlier_id = "mtg_earlier_003"
    later_id = "mtg_later_004"

    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) VALUES (:m, :s, 'completed')"
    ), {"m": earlier_id, "s": "2026-06-29T05:00:00+00:00"})
    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) VALUES (:m, :s, 'completed')"
    ), {"m": later_id, "s": "2026-06-29T06:00:00+00:00"})
    db.commit()

    client = _make_test_client(db)
    resp = client.get(f"/api/admin/cio/last-meeting-agents?meeting_id={earlier_id}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["meeting_id"] == earlier_id, f"Expected {earlier_id}, got {data['meeting_id']}"
    db.close()


def test_last_meeting_agents_endpoint_failure_types_parsed():
    """failure_types histogram correctly parsed from error_text fields."""
    from sqlalchemy import text

    engine = _make_test_engine()
    db = _make_session(engine)

    mtg_id = "mtg_failure_types_005"
    db.execute(text(
        "INSERT INTO fund_meetings (meeting_id, started_at, status) "
        "VALUES (:m, '2026-06-29T07:00:00+00:00', 'failed_partial')"
    ), {"m": mtg_id})
    db.execute(text(
        "INSERT INTO agent_opening_reads "
        "(meeting_id, agent_name, status, response_time_ms, cost_usd, error_text) "
        "VALUES (:m, 'agent_a', 'relay_down', 1500, 0.0, "
        "'relay unreachable after 3 attempts: ConnectError: refused')"
    ), {"m": mtg_id})
    db.execute(text(
        "INSERT INTO agent_opening_reads "
        "(meeting_id, agent_name, status, response_time_ms, cost_usd, error_text) "
        "VALUES (:m, 'agent_b', 'relay_down', 1600, 0.0, "
        "'relay unreachable after 3 attempts: ReadTimeout: timed out')"
    ), {"m": mtg_id})
    db.execute(text(
        "INSERT INTO agent_opening_reads "
        "(meeting_id, agent_name, status, response_time_ms, cost_usd, error_text) "
        "VALUES (:m, 'agent_c', 'relay_down', 1700, 0.0, "
        "'relay unreachable after 3 attempts: ConnectError: refused')"
    ), {"m": mtg_id})
    db.execute(text(
        "INSERT INTO agent_opening_reads "
        "(meeting_id, agent_name, status, response_time_ms, cost_usd, error_text) "
        "VALUES (:m, 'agent_d', 'ok', 800, 0.01, NULL)"
    ), {"m": mtg_id})
    db.commit()

    client = _make_test_client(db)
    resp = client.get(f"/api/admin/cio/last-meeting-agents?meeting_id={mtg_id}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["failure_types"] == {"ConnectError": 2, "ReadTimeout": 1}, (
        f"Expected {{ConnectError: 2, ReadTimeout: 1}}, got {data['failure_types']}"
    )
    assert data["agents_ok_count"] == 1, f"Expected 1 ok agent, got {data['agents_ok_count']}"
    assert data["agents_failed_count"] == 3, f"Expected 3 failed agents, got {data['agents_failed_count']}"
    db.close()


# ---------------------------------------------------------------------------
# Tests 7-8 — _send_meeting_alert helper
# ---------------------------------------------------------------------------

def test_meeting_alert_fires_on_failed_partial():
    """_send_meeting_alert calls send_ops_alert with correct kwargs."""
    # The runner imports discord lazily: `from app.services.discord import send_ops_alert`
    # Patch the discord stub's attribute directly so the lazy import inside _send_meeting_alert
    # picks up the mock.
    mock_alert = MagicMock(name="send_ops_alert")
    _discord_stub.send_ops_alert = mock_alert

    try:
        _runner_mod._send_meeting_alert("mtg_test", severity="warn", title="t", reason="r")
    finally:
        # Restore stub to original MagicMock so other tests aren't affected
        _discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")

    assert mock_alert.called, "send_ops_alert was not called"
    assert mock_alert.call_args.kwargs["severity"] == "warn"
    assert mock_alert.call_args.kwargs["title"] == "t"
    assert "mtg_test" in mock_alert.call_args.kwargs["message"]


def test_meeting_alert_never_raises():
    """_send_meeting_alert must swallow all exceptions from send_ops_alert."""
    error_mock = MagicMock(side_effect=Exception("kaboom"))
    _discord_stub.send_ops_alert = error_mock

    try:
        result = _runner_mod._send_meeting_alert(
            "mtg_test", severity="critical", title="t", reason="r"
        )
    finally:
        _discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")

    # Should return None and NOT raise
    assert result is None
