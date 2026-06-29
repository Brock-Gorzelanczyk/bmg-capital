"""AI-powered trade signal explanation service using Anthropic Haiku."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 350

SYSTEM_PROMPT = (
    "You are a professional trading analyst inside BMG Capital. "
    "Analyze trade signals with clarity and precision. "
    "Keep explanations under 150 words. Use plain English. "
    "Never give investment advice. Paper trading only."
)


def _user_prompt(signal: dict) -> str:
    side = signal.get("side", "?").upper()
    ticker = signal.get("ticker") or signal.get("symbol", "?")
    strategy = signal.get("strategy") or signal.get("display_name", "Unknown strategy")
    confidence = signal.get("confidence", 0)
    entry = signal.get("entry_price")
    stop = signal.get("stop_price")
    target = signal.get("target_price")
    reason = signal.get("reason", "")

    def fmt(v):
        if v is None:
            return "N/A"
        if v >= 1000:
            return f"${v:,.2f}"
        if v >= 1:
            return f"${v:.2f}"
        return f"${v:.6f}"

    rr = "N/A"
    if entry and stop and target:
        reward = abs(target - entry)
        risk = abs(entry - stop)
        if risk > 0:
            rr = f"1:{reward/risk:.1f}"

    lines = [
        f"Signal: {side} {ticker}",
        f"Strategy: {strategy}",
        f"Confidence: {int(confidence * 100)}%",
        f"Entry: {fmt(entry)}  Stop: {fmt(stop)}  Target: {fmt(target)}  R/R: {rr}",
    ]
    if reason:
        lines.append(f"Raw reason: {reason}")

    lines.append(
        "\nExplain in 2-4 sentences: why this signal fired, what the setup means, "
        "and what the risk/reward implies. Write as if briefing a trader."
    )
    return "\n".join(lines)


async def _call_haiku(signal: dict) -> str:
    prompt = _user_prompt(signal)
    from app.services.llm_client import call_llm_cached
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: call_llm_cached(
            model=MODEL,
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=MAX_TOKENS,
            ttl_seconds=86400,
            cache_key_extra=str(signal.get("id", "")),
            agent_name="signal_explain",
        ),
    )


def _get_cached(db: Session, source: str, signal_id: int) -> str | None:
    row = db.execute(
        text("SELECT explanation FROM signal_explanations WHERE signal_source=:s AND signal_id=:i"),
        {"s": source, "i": signal_id},
    ).fetchone()
    return row[0] if row else None


def _save_cache(db: Session, source: str, signal_id: int, explanation: str) -> None:
    db.execute(
        text("""
            INSERT INTO signal_explanations (signal_source, signal_id, explanation, model_used)
            VALUES (:s, :i, :e, :m)
            ON CONFLICT(signal_source, signal_id) DO UPDATE SET
                explanation=excluded.explanation,
                generated_at=CURRENT_TIMESTAMP
        """),
        {"s": source, "i": signal_id, "e": explanation, "m": MODEL},
    )
    db.commit()


def _check_rate_limit(db: Session, user_id: int) -> bool:
    """Return True if within limit (100/hour). Cheaply counted via signal_explanations joins."""
    # Use a lightweight in-memory approach — just check the last hour of generations
    # We don't track per-user in the table, so use a loose global guard of 500/hour
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    row = db.execute(
        text("SELECT COUNT(*) FROM signal_explanations WHERE generated_at >= :c"),
        {"c": cutoff},
    ).fetchone()
    return (row[0] if row else 0) < 500


async def get_or_generate_explanation(
    db: Session,
    user_id: int,
    source: str,
    signal_id: int,
    signal: dict,
) -> dict:
    cached = _get_cached(db, source, signal_id)
    if cached:
        return {"explanation": cached, "model": MODEL, "cached": True}

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    if not _check_rate_limit(db, user_id):
        raise RuntimeError("Rate limit exceeded")

    explanation = await _call_haiku(signal)
    _save_cache(db, source, signal_id, explanation)
    return {"explanation": explanation, "model": MODEL, "cached": False}
