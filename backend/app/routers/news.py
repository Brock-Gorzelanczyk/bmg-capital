from __future__ import annotations

import json
import logging
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_current_user
from app.db.models.users import User
from app.services.news import get_news

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
async def news(
    symbols: Optional[str] = Query(None, description="Comma-separated tickers"),
    limit: int = Query(20, le=50),
):
    """Return recent news articles, optionally filtered by symbol(s)."""
    symbol_list = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    )
    return {"articles": await get_news(symbol_list, limit)}


# ── Article analysis endpoint ─────────────────────────────────────────────────

_ANALYZE_SYSTEM = """You are a financial analyst assistant. Given a news headline and summary, return JSON with:
- sentiment: "bullish", "bearish", or "neutral" (from the perspective of the mentioned stock/market)
- tldr: a 1-sentence plain-English summary (max 120 chars)
- tier: "major" (earnings, Fed, M&A, scandal), "notable" (exec changes, analyst upgrades, product launches), "standard" (everything else)

Return ONLY valid JSON, no other text."""


class AnalyzeRequest(BaseModel):
    headline: str
    summary: str
    symbol: Optional[str] = None


class AnalyzeResponse(BaseModel):
    sentiment: Literal["bullish", "bearish", "neutral"]
    tldr: str
    tier: Literal["major", "notable", "standard"]


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_article(
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    """Analyze a news article for sentiment, TL;DR, and importance tier."""
    user_msg = f"Headline: {body.headline}\n\nSummary: {body.summary[:1000]}"
    if body.symbol:
        user_msg = f"Symbol: {body.symbol}\n\n{user_msg}"

    try:
        import asyncio, hashlib
        from app.services.llm_client import call_llm_cached
        url_hash = hashlib.sha256((body.headline + body.summary[:100]).encode()).hexdigest()[:16]
        text = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: call_llm_cached(
                model="claude-haiku-4-5-20251001",
                prompt=user_msg,
                system_prompt=_ANALYZE_SYSTEM,
                max_tokens=256,
                ttl_seconds=86400 * 7,
                cache_key_extra=url_hash,
                agent_name="news",
            ),
        )
        parsed = json.loads(text)
        return AnalyzeResponse(
            sentiment=parsed.get("sentiment", "neutral"),
            tldr=parsed.get("tldr", body.headline[:120]),
            tier=parsed.get("tier", "standard"),
        )
    except Exception as e:
        logger.warning(f"analyze_article failed: {e}")
        return AnalyzeResponse(sentiment="neutral", tldr=body.headline[:120], tier="standard")
