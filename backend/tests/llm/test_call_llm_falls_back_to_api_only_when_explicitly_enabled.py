"""
T8 — call_llm falls back to API only when FALLBACK_TO_API=true.

Relay fails + FALLBACK_TO_API=true → _fallback_to_api called once,
source='api_fallback' log row written.
"""
import os
import pytest
from unittest.mock import patch, MagicMock
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
                estimated_cost_cents INTEGER,
                error TEXT
            )
        """))
    Session = sessionmaker(bind=engine)
    return Session()


def test_t8_fallback_used_when_enabled(monkeypatch):
    """Relay 500 + FALLBACK_TO_API=true → _fallback_to_api called once."""
    monkeypatch.setenv("FALLBACK_TO_API", "true")
    db = _make_db()

    api_response = "API fallback response."

    def _relay_fails(*a, **kw):
        raise RuntimeError("simulated relay failure")

    with patch("app.services.llm_client._post_to_relay", side_effect=_relay_fails):
        with patch("app.services.llm_client._fallback_to_api", return_value=api_response) as mock_fb:
            with patch("app.services.llm_client._emit_fallback_active_alert"):
                with patch("app.services.llm_client._check_fallback_budget"):
                    from app.services.llm_client import call_llm
                    result = call_llm(
                        model="claude-haiku-4-5-20251001",
                        prompt="Hello fallback",
                        system_prompt="",
                        max_tokens=50,
                        agent_name="test_t8",
                        db=db,
                    )

    mock_fb.assert_called_once()
    assert result == api_response

    row = db.execute(text("SELECT source FROM llm_call_log WHERE agent_name='test_t8'")).fetchone()
    assert row is not None
    assert row[0] == "api_fallback"

    db.close()
