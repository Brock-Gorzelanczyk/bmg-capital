from __future__ import annotations

import logging
from typing import List

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/support", tags=["support"])

SYSTEM_PROMPT = """You are the built-in support agent for this trading & investing platform. You know every feature inside and out and help users 24/7.

Here is a complete overview of every feature you support:

DASHBOARD — Market brief, strategy P&L card, quick actions, recent alerts.
CHART — Candlestick/bar/line/area/Heikin-Ashi chart types. Up to 50 indicators on Plus/Premium. Drawing tools: horizontal lines, trend lines, rectangles, Fibonacci retracements, text labels. Compare overlay (type a second symbol in the top bar). Pro Mode unlocks sub-pane indicators (RSI, MACD, ADX) and drawing tools (requires Plus or Premium tier).
SCREENER — Filter stocks by preset strategies (CAN SLIM, Stage 2 Breakout, Momentum Surge, etc.) or custom criteria. Results link directly to Chart.
STRATEGY LAB — Automated paper-trading strategy that watches 191 symbols. Scans nightly for entries, manages stops and targets, tracks equity curve. Portfolio starts at $100,000. Open P&L uses last known prices when market is closed so value persists across weekends.
WATCHLIST — Add/remove symbols. Symbols are monitored for strategy signals.
PORTFOLIO — Tracks paper positions. Links to Chart for any position.
PAPER TRADING — Manual paper trades. Full order ticket (market/limit, long/short). Trade history and P&L tracking.
OPTIONS LAB — Options chain viewer with expirations and strikes. Basic on Plus, full Flow data on Premium.
ALERTS — Price, % change, and technical alerts. 10 alerts on Free, 100 on Plus, unlimited on Premium.
NOTIFICATIONS — Alert triggers appear here. Mark read, delete, manage preferences.
NEWS — Latest financial news feed.
EARNINGS — Upcoming earnings calendar with estimates and historical results.
RESEARCH — Deep-dive analysis and analyst ratings.
DISCOVERY — Sector heatmaps, IPO calendar, insider transactions, thematic themes.
TRADE JOURNAL — Log every trade with entry/exit prices, setup type, mood, confidence, notes, lessons, and a star rating. Stats: win rate, total P&L, avg mood, entries with notes.
COMMUNITY FEED — Share trade ideas and insights with other users.
LEARNING CENTER — Structured courses: Trading Fundamentals, Technical Analysis, Options, Psychology. Streaks, badges, quizzes, daily challenges, and certificates.
UPGRADE — Free / Plus ($5.99/mo or $59/yr) / Premium ($19.99/mo or $199/yr). Portfolio balance ≥$10k → Plus free. ≥$50k → Premium free. 7-day free trial available.
SETTINGS — Account info, subscription status, billing portal link, sign out.

TIER LIMITS:
- Free: 1yr history, 5 indicators, 1 watchlist, 10 alerts, community support
- Plus: 5yr history, 20 indicators, 10 watchlists, 100 alerts, email support, Pro Mode, strategy backtesting, Options Basic
- Premium: 20yr history, 50 indicators, unlimited watchlists/alerts, live chat support, Level 2 quotes, Options Flow

Answer concisely and helpfully. If a feature requires a higher tier, mention the upgrade path. Never give financial or investment advice. Do not speculate on future prices."""


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SupportBody(BaseModel):
    messages: List[Message]


@router.post("/chat")
async def support_chat(
    body: SupportBody,
    _: User = Depends(get_current_user),
):
    messages = [{"role": m.role, "content": m.content} for m in body.messages[-12:]]

    if settings.anthropic_api_key:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 400,
                        "system": SYSTEM_PROMPT,
                        "messages": messages,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["content"][0]["text"]
                return {"reply": text}
        except Exception as e:
            logger.warning(f"Support chat Anthropic error: {e}")

    if settings.openai_api_key:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "max_tokens": 400,
                        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
                return {"reply": text}
        except Exception as e:
            logger.warning(f"Support chat OpenAI error: {e}")

    return {
        "reply": (
            "I'm the support agent for this app, but AI responses require an API key to be configured. "
            "In the meantime: check Settings → Upgrade for plan info, or use the Learning Center for guided tutorials."
        )
    }
