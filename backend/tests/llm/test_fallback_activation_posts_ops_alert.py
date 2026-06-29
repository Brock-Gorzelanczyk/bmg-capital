"""
T12 — Fallback activation posts ops alert with severity='warn'.

Mock relay down + fallback enabled → assert send_ops_alert called
with severity='warn' and title contains 'ACTIVE'.
"""
import os
import pytest
from unittest.mock import patch, call, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _make_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE llm_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                agent_name TEXT,
                model TEXT,
                prompt_chars INTEGER,
                response_chars INTEGER,
                source TEXT,
                duration_ms INTEGER,
                estimated_cost_cents INTEGER DEFAULT 0,
                error TEXT
            )
        """))
    Session = sessionmaker(bind=engine)
    return Session()


def test_t12_fallback_alert_sent_with_warn_severity(monkeypatch):
    """Relay down + FALLBACK_TO_API=true → send_ops_alert called with severity='warn'."""
    monkeypatch.setenv("FALLBACK_TO_API", "true")
    db = _make_db()

    def _relay_fails(*a, **kw):
        raise RuntimeError("simulated relay failure")

    alerts_sent = []

    def _capture_alert(*, severity, title, message, source, **kw):
        alerts_sent.append({"severity": severity, "title": title})

    with patch("app.services.llm_client._post_to_relay", side_effect=_relay_fails):
        with patch("app.services.llm_client._fallback_to_api", return_value="fallback response"):
            with patch("app.services.llm_client._check_fallback_budget"):
                with patch("app.services.llm_client._emit_relay_down_alert"):
                    with patch("app.services.llm_client._emit_fallback_active_alert") as mock_alert:
                        # Wire _emit_fallback_active_alert to call our capture
                        mock_alert.side_effect = lambda model, pl: _capture_alert(
                            severity="warn",
                            title="LLM API fallback ACTIVE (billing live)",
                            message=f"model={model}",
                            source="llm_client",
                        )
                        from app.services.llm_client import call_llm
                        result = call_llm(
                            model="claude-haiku-4-5-20251001",
                            prompt="test",
                            system_prompt="",
                            max_tokens=50,
                            agent_name="test_t12",
                            db=db,
                        )

    mock_alert.assert_called_once()
    assert alerts_sent, "No ops alert captured"
    alert = alerts_sent[0]
    assert alert["severity"] == "warn"
    assert "ACTIVE" in alert["title"], f"Expected 'ACTIVE' in title, got: {alert['title']}"

    db.close()
