from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user
from app.db.session import get_db
from app.db.models.users import User
from app.services.glossary_data import lookup, all_terms

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/explain", tags=["explain"])

SYSTEM_PROMPT = (
    "You are a financial tutor inside BMG Capital, a trading app. "
    "Explain financial concepts clearly and accurately. "
    "Never give investment advice or specific stock recommendations. "
    "Use plain English first, then add technical detail if the mode is 'detailed'."
)


def _simple_prompt(term: str, context: str) -> str:
    ctx = f" The user is currently viewing: {context}." if context else ""
    return (
        f"Explain '{term}' to a beginner investor in 2-3 sentences.{ctx} "
        "Use plain English with zero jargon. If you must use a technical word, define it inline."
    )


def _detailed_prompt(term: str, context: str) -> str:
    ctx = f" The user is currently viewing: {context}." if context else ""
    return (
        f"Explain '{term}' to an intermediate investor.{ctx} "
        "Include: what it measures, how it's calculated (briefly), how traders/investors use it, "
        "and 1-2 important caveats or common misconceptions. "
        "Keep it under 180 words. Use markdown bold for key terms."
    )


async def _call_anthropic(prompt: str, term: str) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def _call_openai(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class ExplainBody(BaseModel):
    term: str
    context: Optional[str] = None
    mode: str = "simple"  # "simple" | "detailed"


@router.post("")
async def explain(
    body: ExplainBody,
    _: User = Depends(get_current_user),
):
    term = body.term.strip()
    mode = body.mode if body.mode in ("simple", "detailed") else "simple"
    context = (body.context or "").strip()

    # Try AI first
    if settings.anthropic_api_key:
        prompt = _simple_prompt(term, context) if mode == "simple" else _detailed_prompt(term, context)
        try:
            text = await _call_anthropic(prompt, term)
            return {"term": term, "explanation": text, "source": "ai", "mode": mode, "related": []}
        except Exception as e:
            logger.warning(f"Anthropic API failed for '{term}': {e}", exc_info=True)

    if settings.openai_api_key:
        prompt = _simple_prompt(term, context) if mode == "simple" else _detailed_prompt(term, context)
        try:
            text = await _call_openai(prompt)
            return {"term": term, "explanation": text, "source": "ai", "mode": mode, "related": []}
        except Exception as e:
            logger.warning(f"OpenAI API failed for '{term}': {e}", exc_info=True)

    # Fallback: curated glossary
    entry = lookup(term)
    if entry:
        text = entry["brief"] if mode == "simple" else entry["full"]
        return {
            "term": entry["term"],
            "explanation": text,
            "source": "glossary",
            "mode": mode,
            "related": entry.get("related", []),
        }

    # Unknown term — construct a minimal response
    return {
        "term": term,
        "explanation": f"'{term}' is a financial term. Add an Anthropic or OpenAI API key to ANTHROPIC_API_KEY or OPENAI_API_KEY to get AI-powered explanations for any term.",
        "source": "fallback",
        "mode": mode,
        "related": [],
    }


@router.get("/terms")
async def get_terms(_: User = Depends(get_current_user)):
    """All glossary terms + aliases, for autocomplete."""
    return all_terms()


# ── Signal explanation endpoint ────────────────────────────────────────────────

def _explain_enabled():
    if os.getenv("ENABLE_TRADE_EXPLAIN", "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="Trade explanations not enabled")


def _fetch_bot_signal(db: Session, signal_id: int) -> dict:
    from sqlalchemy import text
    row = db.execute(
        text("""
            SELECT bs.id, ba.symbol, bs.side, bs.confidence, bs.entry_price,
                   bs.stop_price, bs.target_price, bs.reason, bs.strategy
            FROM bot_signals bs
            JOIN bot_allocations ba ON ba.id = bs.allocation_id
            WHERE bs.id = :id
        """),
        {"id": signal_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {
        "ticker": row[1], "side": row[2], "confidence": row[3],
        "entry_price": row[4], "stop_price": row[5], "target_price": row[6],
        "reason": row[7], "strategy": row[8],
    }


def _fetch_scout_signal(db: Session, signal_id: int) -> dict:
    from sqlalchemy import text
    from app.db.models.scout import UserScoutSignal
    row = db.query(UserScoutSignal).filter(UserScoutSignal.id == signal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {
        "ticker": row.ticker, "side": row.side, "confidence": row.confidence,
        "entry_price": row.entry_price, "stop_price": row.stop_price,
        "target_price": row.target_price, "reason": row.reason,
        "strategy": row.display_name,
    }


def _fetch_forge_signal(db: Session, signal_id: int) -> dict:
    from app.db.models.forge import UserForgeSignal
    row = db.query(UserForgeSignal).filter(UserForgeSignal.id == signal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {
        "ticker": row.ticker, "side": row.side, "confidence": row.confidence,
        "entry_price": row.entry_price, "stop_price": row.stop_price,
        "target_price": row.target_price, "reason": row.reason,
        "strategy": row.strategy_id,
    }


@router.post("/signal/{signal_id}")
async def explain_signal(
    signal_id: int,
    source: str = Query(..., regex="^(bot|scout|forge)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _flag: None = Depends(_explain_enabled),
):
    from app.services.signal_explain import get_or_generate_explanation

    if source == "bot":
        signal = _fetch_bot_signal(db, signal_id)
    elif source == "scout":
        signal = _fetch_scout_signal(db, signal_id)
    else:
        signal = _fetch_forge_signal(db, signal_id)

    try:
        result = await get_or_generate_explanation(
            db=db,
            user_id=current_user.id,
            source=source,
            signal_id=signal_id,
            signal=signal,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    return {"signal_id": signal_id, "source": source, **result}
