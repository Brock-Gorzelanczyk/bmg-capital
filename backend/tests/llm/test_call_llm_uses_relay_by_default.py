"""
T6 — call_llm uses relay by default.

FALLBACK_TO_API unset (defaults to 'false') → relay POST issued.
"""
import os
import pytest
from unittest.mock import patch
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


def test_t6_relay_used_when_fallback_unset(monkeypatch):
    """FALLBACK_TO_API not set → relay POST issued."""
    monkeypatch.delenv("FALLBACK_TO_API", raising=False)
    db = _make_db()

    relay_response = "Hello from relay."
    with patch("app.services.llm_client._post_to_relay", return_value=relay_response) as mock_relay:
        from app.services.llm_client import call_llm
        result = call_llm(
            model="claude-haiku-4-5-20251001",
            prompt="Hello",
            system_prompt="",
            max_tokens=50,
            agent_name="test_t6",
            db=db,
        )

    mock_relay.assert_called_once()
    assert result == relay_response

    row = db.execute(text("SELECT source FROM llm_call_log WHERE agent_name='test_t6'")).fetchone()
    assert row is not None
    assert row[0] == "relay"

    db.close()
