"""
Plain English translation layer — adds human-readable summaries to all agent Discord embeds.
Translates financial jargon into plain language for Brock (limited investing background).
One Claude Haiku call per unique message; results cached in plain_english_cache table.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are translating financial jargon into plain English for someone with limited investing background. Your job:

(a) Explain what the technical message means in 1-3 sentences using ZERO finance jargon. If you must use a term, explain it briefly in parentheses.

(b) Give one "What it means for you:" sentence — should they care, should they act, can they ignore this?

CRITICAL — EXACT NUMBERS RULE: The message you receive contains exact figures pulled live from the database. You MUST copy these numbers verbatim. Never round, estimate, approximate, or invent a number. If the text says "12 bots", write "12 bots". If it says "$4,821.33", write "$4,821.33". If you cannot find a metric in the provided data, write "unknown" — never guess.

Tone: a smart friend explaining something over coffee, not a textbook. No condescension. No corporate speak.

Jargon guide:
- IC/information coefficient → "how well this bot picks winners"
- drawdown → "how much it lost from its peak"
- regime → "current market conditions"
- alpha → "extra returns beyond what the market gives naturally"
- vol/volatility → "how much prices are bouncing around"
- IVR → "how expensive options premiums are right now"
- DTE → "days until the option expires"
- delta → "how much the option moves when the stock moves"
- Sharpe ratio → "risk-adjusted returns"
- allocation → "how much money is assigned to this bot"
- P&L → "profit and loss"
- bps → "hundredths of a percent"
- slippage → "the gap between expected and actual trade price"

Output format — return ONLY this, no extra text:
SUMMARY: [1-3 sentences]
ACTION: [1 sentence starting with what Brock should do or feel about this]"""


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _check_cache(db, text_hash: str) -> dict | None:
    try:
        from sqlalchemy import text as sql_text
        row = db.execute(
            sql_text("SELECT summary, action FROM plain_english_cache WHERE text_hash = :h"),
            {"h": text_hash},
        ).fetchone()
        return {"summary": row[0], "action": row[1]} if row else None
    except Exception:
        return None


def _write_cache(db, text_hash: str, summary: str, action: str) -> None:
    try:
        from sqlalchemy import text as sql_text
        db.execute(
            sql_text("""
                INSERT INTO plain_english_cache (text_hash, summary, action, created_at)
                VALUES (:h, :s, :a, :ts)
                ON CONFLICT (text_hash) DO NOTHING
            """),
            {"h": text_hash, "s": summary, "a": action, "ts": datetime.now(timezone.utc).isoformat()},
        )
        db.commit()
    except Exception as exc:
        logger.debug("[plain_english] cache write failed: %s", exc)


def _is_channel_enabled(db, channel_id: str) -> bool:
    """Return True (default) unless channel has been explicitly disabled."""
    if not channel_id:
        return True
    try:
        from sqlalchemy import text as sql_text
        row = db.execute(
            sql_text("SELECT enabled FROM plain_english_channels_enabled WHERE channel_id = :c"),
            {"c": channel_id},
        ).fetchone()
        return (row[0] == 1 if row is not None else True)
    except Exception:
        return True


def _call_haiku(technical_text: str) -> dict | None:
    """Call LLM via relay to generate plain-English translation. Returns {summary, action} or None."""
    import hashlib
    try:
        from app.services.llm_client import call_llm_cached
        content_hash = hashlib.sha256(technical_text.encode()).hexdigest()[:16]
        raw = call_llm_cached(
            model="claude-haiku-4-5-20251001",
            prompt=f"Translate this agent message:\n\n{technical_text[:1500]}",
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=200,
            ttl_seconds=86400,
            cache_key_extra=content_hash,
            agent_name="plain_english",
        ).strip()
        # Parse SUMMARY: ... ACTION: ...
        summary, action = "", ""
        for line in raw.splitlines():
            if line.startswith("SUMMARY:"):
                summary = line[len("SUMMARY:"):].strip()
            elif line.startswith("ACTION:"):
                action = line[len("ACTION:"):].strip()
        if not summary:
            # fallback: first line is summary, last is action
            lines = [l for l in raw.splitlines() if l.strip()]
            summary = lines[0] if lines else raw[:200]
            action = lines[-1] if len(lines) > 1 else ""
        return {"summary": summary, "action": action}
    except Exception as exc:
        logger.debug("[plain_english] Haiku call failed: %s", exc)
        return None


def translate_for_brock(
    technical_text: str,
    db=None,
    channel_id: str = "",
    charge_agent: str = "plain_english",
) -> dict | None:
    """
    Main entry point. Returns {"summary": str, "action": str} or None if skipped/failed.

    Skip conditions:
    - text < 50 chars
    - channel explicitly disabled
    - budget cap hit
    - API key missing
    """
    if not technical_text or len(technical_text.strip()) < 50:
        return None

    if db is not None and not _is_channel_enabled(db, channel_id):
        return None

    # Check budget cap
    try:
        from agents.bus import is_budget_capped as _capped
        if db is not None and _capped(db):
            logger.debug("[plain_english] budget cap — skipping translation")
            return None
    except Exception:
        pass

    text_hash = _text_hash(technical_text.strip()[:1500])

    # Cache hit
    if db is not None:
        cached = _check_cache(db, text_hash)
        if cached:
            return cached

    result = _call_haiku(technical_text)
    if not result:
        return None

    # Charge budget (~$0.0003 per call)
    try:
        from agents.bus import charge_api_usage as _charge
        if db is not None:
            _charge(db, charge_agent, 0.0003)
    except Exception:
        pass

    # Cache result
    if db is not None:
        _write_cache(db, text_hash, result["summary"], result["action"])

    return result


def make_plain_english_field(result: dict) -> dict:
    """Convert translate_for_brock() result into a Discord embed field."""
    value = result["summary"]
    if result.get("action"):
        value += f"\n\n**What it means for you:** {result['action']}"
    return {
        "name": "💬 In Plain English",
        "value": value[:1024],  # Discord field value limit
        "inline": False,
    }
