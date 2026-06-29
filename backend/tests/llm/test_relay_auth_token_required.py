"""
T10 — Relay auth token required.

Start relay test client (FastAPI TestClient).
POST /infer no bearer → 401.
Wrong token → 401.
Correct token → 200 (with mocked subprocess).
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


def _get_relay_app():
    """Import relay app with RELAY_AUTH_TOKEN set."""
    relay_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../relay")
    )
    if relay_path not in sys.path:
        sys.path.insert(0, relay_path)
    # Set token before import
    os.environ.setdefault("RELAY_AUTH_TOKEN", "test-secret-token")
    # Remove cached module if already imported with different token
    if "claude_relay_server" in sys.modules:
        del sys.modules["claude_relay_server"]
    try:
        import importlib
        mod = importlib.import_module("claude_relay_server")
        return mod.app
    except ImportError:
        pytest.skip("relay/claude_relay_server.py not importable in test env")


def test_t10_no_bearer_returns_401():
    """No Authorization header → 401."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    with patch.dict(os.environ, {"RELAY_AUTH_TOKEN": "test-secret-token"}):
        app = _get_relay_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/infer",
            json={"model": "claude-haiku-4-5-20251001", "prompt": "hi",
                  "system_prompt": "", "max_tokens": 10},
        )
    assert resp.status_code == 401


def test_t10_wrong_token_returns_401():
    """Wrong token → 401."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    with patch.dict(os.environ, {"RELAY_AUTH_TOKEN": "test-secret-token"}):
        app = _get_relay_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/infer",
            json={"model": "claude-haiku-4-5-20251001", "prompt": "hi",
                  "system_prompt": "", "max_tokens": 10},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401


def test_t10_correct_token_returns_200():
    """Correct token + mocked subprocess → 200 with response_text."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "OK"
    mock_proc.stderr = ""

    with patch.dict(os.environ, {"RELAY_AUTH_TOKEN": "test-secret-token"}):
        app = _get_relay_app()
        with patch("subprocess.run", return_value=mock_proc):
            client = TestClient(app)
            resp = client.post(
                "/infer",
                json={"model": "claude-haiku-4-5-20251001", "prompt": "reply with OK",
                      "system_prompt": "", "max_tokens": 20},
                headers={"Authorization": "Bearer test-secret-token"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "response_text" in data
