from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.users import User
from app.db.models.voice_session import VoiceSession
from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

FREE_VOICE_LIMIT_SECONDS = 600  # 10 minutes per day


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_effective_tier(db: Session, user_id: int) -> str:
    """Return the user's effective tier."""
    try:
        from app.db.models.tier import UserTier
        from app.services.entitlements import effective_tier
        row = db.query(UserTier).filter_by(user_id=user_id).first()
        return effective_tier(row)
    except Exception:
        return "free"


def _get_daily_usage(db: Session, user_id: int) -> int:
    """Sum duration_seconds for all voice sessions created today (UTC)."""
    today = date.today().isoformat()
    sessions = (
        db.query(VoiceSession)
        .filter(
            VoiceSession.user_id == user_id,
            VoiceSession.created_at >= f"{today}T00:00:00",
        )
        .all()
    )
    return sum(s.duration_seconds or 0 for s in sessions)


def _get_strategy_lab_summary(db: Session, user_id: int) -> str:
    """Build a compact Strategy Lab portfolio summary for the Voice AI system prompt.

    Reads live data from the canonical aggregate (same source as the UI).
    Stays under ~400 tokens so it doesn't eat the model's context window.
    """
    try:
        from datetime import timedelta
        from app.core.canonical import compute_strategy_lab_aggregate
        from app.db.models.bots import (
            BotAllocation, BotProfile, BotSignal, BotPosition, StrategyPortfolio,
        )

        agg = compute_strategy_lab_aggregate(user_id, db)
        if not agg:
            return "Strategy Lab portfolios not yet initialised."

        now = datetime.now(timezone.utc)
        total_usd  = (agg.get("total_value_cents") or 0) / 100
        today_pnl  = (agg.get("today_pnl_cents")   or 0) / 100
        today_pct  = agg.get("today_pnl_pct")  or 0.0
        ret_30d    = agg.get("return_30d_pct")  or 0.0
        open_pos   = agg.get("total_open_positions") or 0

        sign = "+" if today_pnl >= 0 else ""
        lines = [
            f"USER PORTFOLIO STATE (live, {now.strftime('%Y-%m-%d %H:%M UTC')}):",
            f"  Total value:   ${total_usd:,.2f}",
            f"  Today P&L:     {sign}${today_pnl:,.2f} ({sign}{today_pct:.2f}%)",
            f"  30d return:    {ret_30d:+.2f}%",
            f"  Open positions: {open_pos}",
            "",
            "  By portfolio:",
        ]

        # Per-portfolio breakdown
        portfolios = (
            db.query(StrategyPortfolio)
            .filter(StrategyPortfolio.user_id == user_id)
            .all()
        )
        allocs = db.query(BotAllocation).filter(BotAllocation.user_id == user_id).all()
        profile_ids = list({a.profile_id for a in allocs})
        profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
        prof_map = {p.id: p.name for p in profiles}
        port_alloc_map: dict[int, list[str]] = {}
        for a in allocs:
            if a.portfolio_id:
                port_alloc_map.setdefault(a.portfolio_id, []).append(
                    prof_map.get(a.profile_id, str(a.profile_id))
                )

        for port in portfolios:
            port_bots = port_alloc_map.get(port.id, [])
            cap_usd = (port.starting_capital_cents or 0) / 100
            bot_list = ", ".join(port_bots) if port_bots else "none"
            lines.append(
                f"    {port.name:<10} ${cap_usd:>10,.0f}  ({len(port_bots)} bot{'s' if len(port_bots) != 1 else ''}: {bot_list})"
            )

        # Recent signals (last 24h)
        cutoff = now - timedelta(hours=24)
        alloc_ids = [a.id for a in allocs]
        recent_signals = 0
        recent_signal_details: list[str] = []
        if alloc_ids:
            sigs = (
                db.query(BotSignal)
                .filter(
                    BotSignal.allocation_id.in_(alloc_ids),
                    BotSignal.ts >= cutoff,
                    (BotSignal.is_test == False) | (BotSignal.is_test.is_(None)),
                )
                .order_by(BotSignal.ts.desc())
                .limit(5)
                .all()
            )
            recent_signals = len(sigs)
            for s in sigs[:3]:
                bot_name = prof_map.get(
                    next((a.profile_id for a in allocs if a.id == s.allocation_id), 0), "?"
                )
                recent_signal_details.append(
                    f"{bot_name}: {s.side.upper()} {s.symbol} conf={s.confidence:.0%}"
                )

        lines.append("")
        lines.append(f"  Recent signals (24h): {recent_signals}")
        if recent_signal_details:
            for d in recent_signal_details:
                lines.append(f"    • {d}")

        # Leaderboard top performer
        lb = agg.get("leaderboard") or []
        if lb:
            best = lb[0]
            lines.append(
                f"  Top performer: {best.get('name')} ({best.get('return_30d_pct', 0):+.2f}% 30d)"
            )

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("_get_strategy_lab_summary failed: %s", exc)
        return "Portfolio data temporarily unavailable."


def _get_market_context(db: Session) -> str:
    """Return a short market regime summary for the Voice AI market tab."""
    try:
        from app.db.models.bots import RegimeSnapshot
        snap = (
            db.query(RegimeSnapshot)
            .order_by(RegimeSnapshot.id.desc())
            .first()
        )
        if not snap:
            return "No market regime data available yet."
        lines = [
            "CURRENT MARKET REGIME:",
            f"  VIX regime:   {snap.vix_regime}",
            f"  Trend regime: {snap.trend_regime}",
        ]
        if hasattr(snap, "vix") and snap.vix:
            lines.append(f"  VIX level:    {snap.vix:.1f}")
        if hasattr(snap, "spy_price") and snap.spy_price:
            lines.append(f"  SPY:          ${snap.spy_price:.2f}")
        if hasattr(snap, "btc_dominance") and snap.btc_dominance:
            lines.append(f"  BTC dominance:{snap.btc_dominance:.1f}%")
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("_get_market_context failed: %s", exc)
        return "Market regime data unavailable."


def _serialize_session(s: VoiceSession) -> Dict[str, Any]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "messages": s.messages or [],
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "duration_seconds": s.duration_seconds or 0,
    }


async def _call_ai(system_prompt: str, user_message: str, context: str) -> tuple[str, list[str]]:
    """Call Anthropic Claude Haiku and return (response_text, citations)."""
    if not settings.anthropic_api_key:
        return (
            "Voice briefing temporarily unavailable. Try again in a moment.",
            [],
        )
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        response_text = message.content[0].text if message.content else ""

        # Extract simple citations from the response (sentences that start with "According to" etc.)
        citations: list[str] = []
        for sentence in response_text.split(". "):
            if any(
                kw in sentence.lower()
                for kw in ["according to", "based on", "data shows", "historically"]
            ):
                citations.append(sentence.strip())

        return response_text, citations
    except Exception as e:
        logger.error(f"Anthropic call failed: {e}", exc_info=True)
        return "Voice briefing temporarily unavailable. Try again in a moment.", []


# ── Request/Response models ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None
    context: str = "general"  # portfolio | market | general


class ChatResponse(BaseModel):
    response: str
    session_id: int
    citations: List[str]
    duration_seconds: int = 0


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def voice_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """Send a message to the voice AI. Creates or continues a session."""
    tier = _get_effective_tier(db, current_user.id)
    if tier == "free":
        daily_usage = _get_daily_usage(db, current_user.id)
        if daily_usage >= FREE_VOICE_LIMIT_SECONDS:
            raise HTTPException(
                status_code=429,
                detail={
                    "detail": "Daily voice limit reached. Upgrade to Plus for unlimited voice.",
                    "upgrade": True,
                },
            )

    # Get or create session
    session: Optional[VoiceSession] = None
    if body.session_id:
        session = (
            db.query(VoiceSession)
            .filter_by(id=body.session_id, user_id=current_user.id)
            .first()
        )
    if not session:
        session = VoiceSession(user_id=current_user.id, messages=[], duration_seconds=0)
        db.add(session)
        db.flush()

    # Build system prompt — inject live context per tab
    if body.context == "portfolio":
        context_data = _get_strategy_lab_summary(db, current_user.id)
        context_hint = "Focus on the user's specific portfolio holdings, positions, and performance."
    elif body.context == "market":
        context_data = _get_market_context(db)
        context_hint = "Focus on current market conditions, macro trends, and sector analysis."
    else:
        context_data = ""
        context_hint = "Answer general investing and financial questions."

    system_prompt = (
        "You are BMG Capital's AI advisor. "
        + context_hint
        + (" \n\n" + context_data + "\n\n" if context_data else " ")
        + "Answer in 1-3 sentences, spoken-language style. Always cite your reasoning. "
        "Never give specific buy/sell advice without saying "
        "'this is educational, not financial advice.'"
    )

    # Call AI
    ai_response, citations = await _call_ai(system_prompt, body.message, body.context)

    # Append messages
    now_iso = datetime.now(timezone.utc).isoformat()
    msgs = list(session.messages or [])
    msgs.append({"role": "user", "content": body.message, "timestamp": now_iso})
    msgs.append({"role": "assistant", "content": ai_response, "timestamp": now_iso})
    session.messages = msgs
    session.duration_seconds = (session.duration_seconds or 0) + 10
    session.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(session)

    return ChatResponse(
        response=ai_response,
        session_id=session.id,
        citations=citations,
        duration_seconds=session.duration_seconds or 0,
    )


@router.get("/sessions")
async def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Return the last 20 voice sessions for the current user."""
    sessions = (
        db.query(VoiceSession)
        .filter_by(user_id=current_user.id)
        .order_by(VoiceSession.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": s.id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "duration_seconds": s.duration_seconds or 0,
            "message_count": len(s.messages or []),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return a full voice session with all messages."""
    session = (
        db.query(VoiceSession)
        .filter_by(id=session_id, user_id=current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": _serialize_session(session)}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """Delete a voice session."""
    session = (
        db.query(VoiceSession)
        .filter_by(id=session_id, user_id=current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"status": "deleted"}


@router.get("/daily-usage")
async def get_daily_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return today's voice usage stats for the current user."""
    tier = _get_effective_tier(db, current_user.id)
    used = _get_daily_usage(db, current_user.id)
    limit = FREE_VOICE_LIMIT_SECONDS if tier == "free" else None
    remaining = max(0, (limit or FREE_VOICE_LIMIT_SECONDS) - used) if tier == "free" else None
    return {
        "tier": tier,
        "used_seconds": used,
        "limit_seconds": limit,
        "remaining_seconds": remaining,
        "unlimited": tier in ("plus", "premium"),
    }


@router.get("/usage")
async def get_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return today's voice usage stats (aliased endpoint for frontend)."""
    tier = _get_effective_tier(db, current_user.id)
    used = _get_daily_usage(db, current_user.id)
    limit_seconds = FREE_VOICE_LIMIT_SECONDS if tier == "free" else -1
    return {
        "used_seconds": used,
        "limit_seconds": limit_seconds,
        "unlimited": tier in ("plus", "premium"),
        "tier": tier,
    }
