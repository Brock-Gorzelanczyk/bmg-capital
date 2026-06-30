"""
T7 — call_llm raises RuntimeError when relay down and FALLBACK_TO_API=false.

Mock relay to raise → FALLBACK_TO_API=false → RuntimeError raised,
anthropic SDK never called.
"""
import os
import sys
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


def test_t7_raises_when_relay_down_fallback_disabled(monkeypatch):
    """Mock relay 500, FALLBACK_TO_API=false → RuntimeError raised."""
    monkeypatch.setenv("FALLBACK_TO_API", "false")
    db = _make_db()

    def _relay_fails(*a, **kw):
        raise RuntimeError("simulated relay failure (503)")

    with patch("app.services.llm_client._post_to_relay", side_effect=_relay_fails):
        with patch("app.services.llm_client._emit_relay_down_alert"):
            with patch("app.services.llm_client._fallback_to_api") as mock_fallback:
                from app.services.llm_client import call_llm
                with pytest.raises(RuntimeError, match="relay unreachable"):
                    call_llm(
                        model="claude-haiku-4-5-20251001",
                        prompt="hi",
                        system_prompt="",
                        max_tokens=50,
                        agent_name="test_t7",
                        db=db,
                    )

    # Anthropic fallback must NOT have been called
    mock_fallback.assert_not_called()

    db.close()
