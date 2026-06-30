"""
T9 — Daily API fallback budget hard caps at $5.

Insert 501 cents of api_fallback rows in last 24h →
next call_llm raises RuntimeError containing "budget exceeded".
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
        # Seed 501 cents of api_fallback spend in last 24h
        conn.execute(text("""
            INSERT INTO llm_call_log
                (agent_name, model, prompt_chars, response_chars, source,
                 duration_ms, estimated_cost_cents)
            VALUES
                ('seed', 'claude-haiku-4-5-20251001', 100, 100, 'api_fallback', 500, 501)
        """))
    Session = sessionmaker(bind=engine)
    return Session()


def test_t9_budget_cap_raises_runtime_error(monkeypatch):
    """501 cents of api_fallback rows → RuntimeError 'budget exceeded'."""
    monkeypatch.setenv("FALLBACK_TO_API", "true")
    monkeypatch.setenv("LLM_DAILY_FALLBACK_BUDGET_USD", "5")
    db = _make_db()

    def _relay_fails(*a, **kw):
        raise RuntimeError("relay down")

    with patch("app.services.llm_client._post_to_relay", side_effect=_relay_fails):
        with patch("app.services.llm_client._fallback_to_api") as mock_fb:
            with patch("app.services.llm_client._emit_relay_down_alert"):
                with patch("app.services.llm_client.send_ops_alert", create=True):
                    from app.services.llm_client import call_llm
                    with pytest.raises(RuntimeError, match="budget exceeded"):
                        call_llm(
                            model="claude-haiku-4-5-20251001",
                            prompt="Over budget call",
                            system_prompt="",
                            max_tokens=50,
                            agent_name="test_t9",
                            db=db,
                        )

    # _fallback_to_api must not have been called (budget check happens first)
    mock_fb.assert_not_called()

    db.close()
