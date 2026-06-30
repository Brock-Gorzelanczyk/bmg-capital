"""
Tests for m030:
  1. AST regression: m030 boot wrapper is a separate try block from m028.
  2-6. Unit tests for _post_to_relay() retry-with-backoff.

The conftest.py at tests/ pre-installs a stub for "app.services" (as a bare
types.ModuleType), so patch("app.services.llm_client.X") won't resolve unless
we load the real llm_client via importlib and register it under the dotted name
first. We follow the same pattern used by test_cio_meeting.py and llm/conftest.py.
"""
import ast
import importlib.util as _ilu
import logging
import os
import pathlib
import sys
import types
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Bootstrap: load the real llm_client module into sys.modules so that
# patch("app.services.llm_client.*") resolves to the real module object.
# ---------------------------------------------------------------------------

_BACKEND = str(pathlib.Path(__file__).resolve().parents[1])
_LLM_CLIENT_PATH = os.path.join(_BACKEND, "app", "services", "llm_client.py")
_LLM_MOD_NAME = "app.services.llm_client"


def _load_real_llm_client():
    """Load the real llm_client module and register it under the correct dotted name."""
    if _LLM_MOD_NAME in sys.modules:
        mod = sys.modules[_LLM_MOD_NAME]
        # Re-register if it's a stub (no real attributes)
        if hasattr(mod, "_post_to_relay"):
            return mod

    # Ensure app.db.session and app.services.discord stubs exist so the module
    # can import without a live database or real Discord connection.
    for stub_name in ("app.db.session", "app.services.discord"):
        if stub_name not in sys.modules:
            stub = types.ModuleType(stub_name)
            stub.__spec__ = None
            sys.modules[stub_name] = stub

    discord_stub = sys.modules["app.services.discord"]
    if not hasattr(discord_stub, "send_ops_alert"):
        discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")

    db_session_stub = sys.modules["app.db.session"]
    if not hasattr(db_session_stub, "SessionLocal"):
        db_session_stub.SessionLocal = MagicMock(name="SessionLocal")

    spec = _ilu.spec_from_file_location(_LLM_MOD_NAME, _LLM_CLIENT_PATH)
    mod = _ilu.module_from_spec(spec)
    sys.modules[_LLM_MOD_NAME] = mod
    spec.loader.exec_module(mod)

    # Wire onto app.services stub so attribute traversal works
    app_services = sys.modules.get("app.services")
    if app_services is not None:
        setattr(app_services, "llm_client", mod)

    return mod


# Load at import time so the module is available for all tests
_llm_client_mod = _load_real_llm_client()


# ---------------------------------------------------------------------------
# Test 1 — AST regression guard
# ---------------------------------------------------------------------------

def test_m030_boot_wrapper_separate_from_m028():
    """
    Parse main.py and assert that the ast.Try node containing the m030 import
    does NOT also contain the m028 import in the same try body.
    """
    main_py = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py"
    )
    source = main_py.read_text()
    tree = ast.parse(source)

    def _imports_in_try_body(try_node):
        """Return set of module names for ImportFrom nodes in the try body (top level only)."""
        modules = set()
        for node in try_node.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    m030_try_nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            mods = _imports_in_try_body(node)
            if any(m.endswith("m030_inception_snapshot_on_daily_pnl") for m in mods):
                m030_try_nodes.append((node, mods))

    # Exactly one try block should contain the m030 import
    assert len(m030_try_nodes) == 1, (
        f"Expected exactly 1 Try node containing m030 import, found {len(m030_try_nodes)}"
    )

    _, mods = m030_try_nodes[0]
    # That same try body must NOT contain the m028 import
    assert not any(m.endswith("m028_quarantine_cross_sleeve") for m in mods), (
        "m030 import is still inside the same try block as m028 — indent bug not fixed"
    )


# ---------------------------------------------------------------------------
# Helpers for relay tests
# ---------------------------------------------------------------------------

def _make_mock_client(post_mock):
    """
    Build a mock that works as a context manager for httpx.Client(timeout=60).
    The inner .post is post_mock.
    """
    inner = MagicMock()
    inner.post = post_mock
    outer = MagicMock()
    outer.__enter__ = MagicMock(return_value=inner)
    outer.__exit__ = MagicMock(return_value=False)
    return outer


def _make_response(status_code, response_text=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if response_text is not None:
        resp.json.return_value = {"response_text": response_text}
    return resp


# ---------------------------------------------------------------------------
# Test 2 — success on first attempt
# ---------------------------------------------------------------------------

def test_relay_success_on_first_attempt(monkeypatch):
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    ok_resp = _make_response(200, response_text="hello")
    post_mock = MagicMock(return_value=ok_resp)
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time") as mock_time:
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError
        result = _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert result == "hello"
    mock_time.sleep.assert_not_called()
    post_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3 — retry on httpx error then success
# ---------------------------------------------------------------------------

def test_relay_retry_on_httpx_error_then_success(monkeypatch, caplog):
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    ok_resp = _make_response(200, response_text="ok_text")
    post_mock = MagicMock(
        side_effect=[
            httpx.ConnectError("conn refused"),
            httpx.ConnectError("conn refused"),
            ok_resp,
        ]
    )
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time") as mock_time, \
         caplog.at_level(logging.WARNING, logger="app.services.llm_client"):
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError
        result = _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert result == "ok_text"
    assert mock_time.sleep.call_count == 2
    assert mock_time.sleep.call_args_list == [call(0.5), call(1.5)]
    assert post_mock.call_count == 3

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert sum(
        1 for m in warning_msgs if "[llm_client] relay httpx attempt" in str(m)
    ) == 2


# ---------------------------------------------------------------------------
# Test 4 — gives up after 3 attempts
# ---------------------------------------------------------------------------

def test_relay_retry_gives_up_after_3_attempts(monkeypatch):
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    post_mock = MagicMock(side_effect=httpx.ConnectError("down"))
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time") as mock_time:
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError

        with pytest.raises(RuntimeError, match="after 3 attempts"):
            _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert post_mock.call_count == 3
    assert mock_time.sleep.call_count == 2


# ---------------------------------------------------------------------------
# Test 5 — retry on 5xx then success
# ---------------------------------------------------------------------------

def test_relay_retry_on_5xx_then_success(monkeypatch):
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    resp_503a = _make_response(503, text="Service Unavailable")
    resp_503b = _make_response(503, text="Service Unavailable")
    resp_200 = _make_response(200, response_text="good")

    post_mock = MagicMock(side_effect=[resp_503a, resp_503b, resp_200])
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time") as mock_time:
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError
        result = _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert result == "good"
    assert mock_time.sleep.call_count == 2
    assert mock_time.sleep.call_args_list == [call(0.5), call(1.5)]
    assert post_mock.call_count == 3


# ---------------------------------------------------------------------------
# Test 6 — no retry on 4xx
# ---------------------------------------------------------------------------

def test_relay_no_retry_on_4xx(monkeypatch):
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_AUTH_TOKEN", "tok")

    resp_401 = _make_response(401, text="unauthorized")
    post_mock = MagicMock(return_value=resp_401)
    client_mock = _make_mock_client(post_mock)

    with patch.object(_llm_client_mod, "httpx") as mock_httpx, \
         patch.object(_llm_client_mod, "time") as mock_time:
        mock_httpx.Client.return_value = client_mock
        mock_httpx.HTTPError = httpx.HTTPError

        with pytest.raises(RuntimeError, match="401"):
            _llm_client_mod._post_to_relay("m", "p", "s", 100, "agent")

    assert post_mock.call_count == 1
    mock_time.sleep.assert_not_called()
