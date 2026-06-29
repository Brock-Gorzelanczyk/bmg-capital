"""
T4 — Cache returns stored response within TTL.

Insert a cache row manually, call call_llm_cached(), assert:
  - No relay POST made
  - source='cache' log row written
"""
import hashlib
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _make_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE anthropic_call_cache (
                cache_key TEXT PRIMARY KEY,
                model TEXT,
                prompt_hash TEXT,
                response_json TEXT,
                response_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                hit_count INTEGER DEFAULT 0,
                last_hit_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE llm_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                agent_name TEXT,
                model TEXT,
                prompt_chars INTEGER,
                response_chars INTEGER,
                source TEXT CHECK(source IN ('relay','api_fallback','cache')),
                duration_ms INTEGER,
                estimated_cost_cents INTEGER,
                error TEXT
            )
        """))
    Session = sessionmaker(bind=engine)
    return Session()


def _insert_cache_row(db, key, response_text, ttl_seconds=3600):
    db.execute(text("""
        INSERT INTO anthropic_call_cache
            (cache_key, model, prompt_hash, response_json, response_text,
             expires_at, hit_count)
        VALUES
            (:k, 'claude-haiku-4-5-20251001', 'testhash',
             :rj, :rt,
             datetime('now', :ttl),
             0)
    """), {
        "k": key,
        "rj": json.dumps({"text": response_text}),
        "rt": response_text,
        "ttl": f"+{ttl_seconds} seconds",
    })
    db.commit()


def _make_cache_key(model, system_prompt, prompt, extra=""):
    return hashlib.sha256(
        f"{model}|{system_prompt}|{prompt}|{extra}".encode()
    ).hexdigest()


def test_t4_cache_hit_skips_relay():
    """Insert row, call wrapper, assert no relay POST and source='cache' log row."""
    db = _make_db()
    model = "claude-haiku-4-5-20251001"
    prompt = "What is 2+2?"
    system_prompt = ""
    stored_text = "The answer is 4."

    key = _make_cache_key(model, system_prompt, prompt)
    _insert_cache_row(db, key, stored_text)

    with patch("app.services.llm_client._post_to_relay") as mock_relay:
        from app.services.llm_client import call_llm_cached
        result = call_llm_cached(
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=100,
            ttl_seconds=3600,
            cache_key_extra="",
            agent_name="test_t4",
            db=db,
        )

    # Relay was not called
    mock_relay.assert_not_called()
    assert result == stored_text

    # source='cache' row exists in log
    row = db.execute(text(
        "SELECT source FROM llm_call_log WHERE agent_name='test_t4'"
    )).fetchone()
    assert row is not None, "Expected a log row for cache hit"
    assert row[0] == "cache"

    db.close()
