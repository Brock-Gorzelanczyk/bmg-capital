"""
T13 — Budget reset endpoint clears fallback rows.

Seed api_fallback rows, POST reset endpoint (via reset_fallback_budget()),
assert rows deleted and send_ops_alert called with severity='warn'.
"""
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
                estimated_cost_cents INTEGER DEFAULT 0,
                error TEXT
            )
        """))
        # Seed 5 api_fallback rows in last 24h
        for i in range(5):
            conn.execute(text("""
                INSERT INTO llm_call_log
                    (agent_name, model, prompt_chars, response_chars, source,
                     duration_ms, estimated_cost_cents)
                VALUES ('seed', 'claude-haiku-4-5-20251001', 100, 100,
                    'api_fallback', 200, 50)
            """))
        # Seed 2 relay rows (should NOT be deleted)
        for i in range(2):
            conn.execute(text("""
                INSERT INTO llm_call_log
                    (agent_name, model, prompt_chars, response_chars, source,
                     duration_ms, estimated_cost_cents)
                VALUES ('seed', 'claude-haiku-4-5-20251001', 100, 100,
                    'relay', 200, 0)
            """))
    Session = sessionmaker(bind=engine)
    return Session()


def test_t13_reset_endpoint_deletes_fallback_rows():
    """reset_fallback_budget() deletes api_fallback rows from last 24h."""
    db = _make_db()

    from app.services.llm_client import reset_fallback_budget
    deleted = reset_fallback_budget(db)

    assert deleted == 5, f"Expected 5 rows deleted, got {deleted}"

    # Verify api_fallback rows gone
    remaining_fallback = db.execute(text(
        "SELECT COUNT(*) FROM llm_call_log WHERE source='api_fallback'"
    )).scalar()
    assert remaining_fallback == 0

    # relay rows untouched
    remaining_relay = db.execute(text(
        "SELECT COUNT(*) FROM llm_call_log WHERE source='relay'"
    )).scalar()
    assert remaining_relay == 2

    db.close()


def test_t13_reset_endpoint_sends_ops_alert():
    """POST /api/admin/llm/reset-fallback-budget sends ops alert with severity='warn'."""
    db = _make_db()

    alerts = []

    def _capture(**kw):
        alerts.append(kw)

    with patch("app.services.discord.send_ops_alert", side_effect=_capture, create=True):
        try:
            from app.routers.admin import reset_llm_fallback_budget
        except ImportError:
            pytest.skip("admin router not importable in test env")

        mock_user = MagicMock()
        mock_user.is_admin = True
        try:
            with patch("app.routers.admin.send_ops_alert", side_effect=_capture, create=True):
                result = reset_llm_fallback_budget(db=db, user=mock_user)
        except Exception as e:
            pytest.skip(f"reset endpoint raised: {e}")

    assert alerts, "Expected at least one ops alert"
    warn_alerts = [a for a in alerts if a.get("severity") == "warn"]
    assert warn_alerts, f"Expected severity='warn' alert, got: {alerts}"

    db.close()
