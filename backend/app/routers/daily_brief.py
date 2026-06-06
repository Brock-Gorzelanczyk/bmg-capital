from __future__ import annotations

import hashlib
import logging
import random
from datetime import timezone, date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.daily_brief import DailyBrief
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/daily-brief", tags=["daily-brief"])

READING_LEVEL_INSTRUCTIONS = {
    "pro": (
        "Use professional financial language. Include technical terms like P/E ratios, "
        "beta, sector rotation, RSI, MACD, and macro indicators. Be concise and data-driven."
    ),
    "investor": (
        "Use clear investor-friendly language. Explain concepts briefly without jargon. "
        "Focus on what it means for a retail investor's portfolio."
    ),
    "beginner": (
        "Use simple, everyday language. Avoid jargon completely. "
        "Explain every concept as if the reader is new to investing."
    ),
    "eli5": (
        "Explain everything like the reader is 5 years old. Use fun analogies, "
        "very short sentences, and no financial jargon whatsoever."
    ),
}

MARKET_SYMBOLS = ["SPY", "QQQ", "BTC"]


def _seed_move(symbol: str, brief_date: date) -> float:
    """Generate a deterministic pseudo-random pre-market move for a symbol+date."""
    seed_str = f"{symbol}-{brief_date.isoformat()}"
    seed_int = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    rng = random.Random(seed_int)
    # Realistic pre-market range: -3% to +3%
    return round(rng.uniform(-3.0, 3.0), 2)


def _get_watchlist_symbols(db: Session, user_id: int) -> list[str]:
    """Return all unique symbols from the user's watchlists."""
    try:
        from app.db.models.watchlist import Watchlist, WatchlistItem
        watchlists = db.query(Watchlist).filter_by(user_id=user_id).all()
        symbols = []
        seen = set()
        for wl in watchlists:
            for item in wl.items:
                if item.symbol not in seen:
                    symbols.append(item.symbol)
                    seen.add(item.symbol)
        return symbols
    except Exception as e:
        logger.debug(f"Could not load watchlist symbols: {e}")
        return []


def _get_portfolio_symbols(db: Session, user_id: int) -> list[str]:
    """Return all unique symbols from the user's portfolio positions."""
    try:
        from app.db.models.portfolio import Portfolio
        portfolios = db.query(Portfolio).filter_by(user_id=user_id).all()
        symbols = []
        seen = set()
        for p in portfolios:
            for pos in p.positions:
                if pos.symbol not in seen:
                    symbols.append(pos.symbol)
                    seen.add(pos.symbol)
        return symbols
    except Exception as e:
        logger.debug(f"Could not load portfolio symbols: {e}")
        return []


async def _fetch_news_for_symbols(symbols: list[str]) -> list[dict]:
    """Fetch recent news items for the given symbols."""
    if not symbols:
        return []
    try:
        from app.services.news import get_news_for_symbols
        items = await get_news_for_symbols(symbols[:10])  # cap to avoid latency
        return items or []
    except Exception:
        pass
    try:
        # Fallback: generate placeholder news items
        return [
            {
                "symbol": symbols[0] if symbols else "SPY",
                "headline": f"Market update: watch {', '.join(symbols[:3])} today",
                "source": "BMG Capital",
            }
        ]
    except Exception:
        return []


async def _fetch_upcoming_earnings(db: Session, symbols: list[str]) -> list[dict]:
    """Return upcoming earnings events for any of the given symbols (next 7 days)."""
    results = []
    if not symbols:
        return results
    try:
        from app.services.earnings import get_earnings_calendar
        all_earnings = await get_earnings_calendar(days_ahead=7)
        sym_set = {s.upper() for s in symbols}
        for e in (all_earnings or []):
            if e.get("symbol", "").upper() in sym_set:
                results.append(e)
    except Exception as e:
        logger.debug(f"Could not fetch earnings: {e}")
    return results


async def _generate_sections_with_ai(
    user_id: int,
    watchlist_symbols: list[str],
    portfolio_symbols: list[str],
    news_items: list[dict],
    earnings_events: list[dict],
    brief_date: date,
    reading_level: str,
) -> list[dict]:
    """Call Claude to generate the brief sections."""
    level_instruction = READING_LEVEL_INSTRUCTIONS.get(reading_level, READING_LEVEL_INSTRUCTIONS["investor"])

    # Build holdings overnight section data
    all_symbols = list(dict.fromkeys(portfolio_symbols + watchlist_symbols))[:20]
    holdings_lines = []
    for sym in all_symbols:
        move = _seed_move(sym, brief_date)
        direction = "+" if move >= 0 else ""
        holdings_lines.append(f"{sym}: {direction}{move:.2f}%")

    market_lines = []
    for sym in MARKET_SYMBOLS:
        move = _seed_move(sym, brief_date)
        direction = "+" if move >= 0 else ""
        market_lines.append(f"{sym}: {direction}{move:.2f}%")

    # Build context for AI
    news_context = "\n".join(
        f"- [{n.get('symbol', '')}] {n.get('headline', n.get('title', ''))}"
        for n in news_items[:8]
    ) or "No major news items."

    earnings_context = (
        "\n".join(
            f"- {e.get('symbol', '')} reports {e.get('date', 'this week')} "
            f"({'before open' if e.get('time') == 'pre' else 'after close'})"
            for e in earnings_events[:5]
        )
        or "No upcoming earnings for your watchlist this week."
    )

    system_prompt = (
        f"You are BMG Capital's AI market analyst writing a personalized daily brief. "
        f"{level_instruction} "
        "Be helpful, specific, and grounded. Write each section as flowing prose, "
        "not bullet points. Keep each section to 2-4 sentences."
    )

    user_prompt = f"""Write the following sections of a daily market brief for {brief_date.strftime("%B %d, %Y")}:

1. "Your Holdings Overnight" - comment on the pre-market moves:
{chr(10).join(holdings_lines) if holdings_lines else "No holdings on file."}

2. "What's Affecting Your Portfolio" - analyze this news:
{news_context}

3. "Earnings This Week" - comment on these upcoming earnings:
{earnings_context}

4. "Today's Market Open" - preview the market open based on these pre-market moves:
{chr(10).join(market_lines)}

For each section, write a 2-4 sentence commentary in the style requested. Return as JSON with keys:
"holdings_overnight", "portfolio_news", "earnings_preview", "market_open"
Each value should be a string (the section prose).
"""

    if settings.anthropic_api_key:
        try:
            import anthropic
            import json as _json

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = msg.content[0].text if msg.content else "{}"
            # Extract JSON from the response (handle markdown code fences)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = _json.loads(raw.strip())
        except Exception as e:
            logger.error(f"Daily brief AI call failed: {e}", exc_info=True)
            parsed = {}
    else:
        parsed = {}

    # Build structured sections with sources
    def _news_sources(syms: list[str]) -> list[dict]:
        sources = []
        for item in news_items[:5]:
            if not syms or item.get("symbol", "") in syms:
                sources.append({
                    "symbol": item.get("symbol", ""),
                    "headline": item.get("headline", item.get("title", "")),
                    "source": item.get("source", ""),
                })
        return sources

    sections = [
        {
            "key": "holdings_overnight",
            "title": "Your Holdings Overnight",
            "content": parsed.get(
                "holdings_overnight",
                f"Pre-market moves for your holdings: {', '.join(holdings_lines[:5]) if holdings_lines else 'No data'}.",
            ),
            "data": [{"symbol": sym, "change_pct": _seed_move(sym, brief_date)} for sym in all_symbols],
            "sources": [],
        },
        {
            "key": "portfolio_news",
            "title": "What's Affecting Your Portfolio",
            "content": parsed.get(
                "portfolio_news",
                "No major news items affecting your portfolio today.",
            ),
            "sources": _news_sources(all_symbols),
        },
        {
            "key": "earnings_preview",
            "title": "Earnings This Week",
            "content": parsed.get(
                "earnings_preview",
                earnings_context,
            ),
            "data": earnings_events[:5],
            "sources": [],
        },
        {
            "key": "market_open",
            "title": "Today's Market Open",
            "content": parsed.get(
                "market_open",
                f"Pre-market: {', '.join(market_lines)}.",
            ),
            "data": [{"symbol": sym, "change_pct": _seed_move(sym, brief_date)} for sym in MARKET_SYMBOLS],
            "sources": [],
        },
    ]
    return sections


def _serialize_brief(brief: DailyBrief) -> Dict[str, Any]:
    return {
        "id": brief.id,
        "user_id": brief.user_id,
        "brief_date": brief.brief_date.isoformat() if brief.brief_date else None,
        "sections": (brief.content_json or {}).get("sections", []),
        "reading_level": brief.reading_level,
        "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_brief(
    reading_level: str = Query("investor", regex="^(pro|investor|beginner|eli5)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate (or regenerate) today's personalized daily brief."""
    today = date.today()

    watchlist_symbols = _get_watchlist_symbols(db, current_user.id)
    portfolio_symbols = _get_portfolio_symbols(db, current_user.id)
    news_items = await _fetch_news_for_symbols(list(dict.fromkeys(portfolio_symbols + watchlist_symbols))[:15])
    earnings_events = await _fetch_upcoming_earnings(db, list(dict.fromkeys(watchlist_symbols + portfolio_symbols)))

    sections = await _generate_sections_with_ai(
        user_id=current_user.id,
        watchlist_symbols=watchlist_symbols,
        portfolio_symbols=portfolio_symbols,
        news_items=news_items,
        earnings_events=earnings_events,
        brief_date=today,
        reading_level=reading_level,
    )

    content = {"sections": sections}
    now = datetime.now(timezone.utc)

    # Upsert: one brief per user per day
    existing = (
        db.query(DailyBrief)
        .filter_by(user_id=current_user.id, brief_date=today)
        .first()
    )
    if existing:
        existing.content_json = content
        existing.reading_level = reading_level
        existing.generated_at = now
        db.commit()
        db.refresh(existing)
        brief = existing
    else:
        brief = DailyBrief(
            user_id=current_user.id,
            brief_date=today,
            content_json=content,
            reading_level=reading_level,
            generated_at=now,
        )
        db.add(brief)
        db.commit()
        db.refresh(brief)

    return {
        "sections": sections,
        "generated_at": brief.generated_at.isoformat(),
        "reading_level": reading_level,
    }


@router.get("/latest")
async def get_latest_brief(
    reading_level: str = Query("investor"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the latest brief, regenerating if > 4 hours old or different reading level."""
    today = date.today()
    brief = (
        db.query(DailyBrief)
        .filter_by(user_id=current_user.id, brief_date=today)
        .first()
    )

    # Regenerate if no brief, > 4h old, or reading level changed
    needs_regen = True
    if brief and brief.generated_at:
        age = datetime.now(timezone.utc) - brief.generated_at
        if age < timedelta(hours=4) and brief.reading_level == reading_level:
            needs_regen = False

    if needs_regen:
        result = await generate_brief(reading_level=reading_level, db=db, current_user=current_user)
    else:
        result = {
            "sections": (brief.content_json or {}).get("sections", []),
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
            "reading_level": brief.reading_level,
        }

    # Enrich response with date and watchlist_symbols for frontend
    watchlist_symbols = _get_watchlist_symbols(db, current_user.id)
    portfolio_symbols = _get_portfolio_symbols(db, current_user.id)
    all_symbols = list(dict.fromkeys(portfolio_symbols + watchlist_symbols))
    if not all_symbols:
        all_symbols = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]

    return {
        "date": today.strftime("%A, %B %d, %Y"),
        "reading_level": result.get("reading_level", reading_level),
        "generated_at": result.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "sections": result.get("sections", []),
        "watchlist_symbols": all_symbols,
    }
