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


def _get_portfolio_summary(db: Session, user_id: int) -> str:
    """Build a short text summary of the user's portfolio for the system prompt."""
    try:
        from app.db.models.portfolio import Portfolio, Position
        portfolios = (
            db.query(Portfolio).filter_by(user_id=user_id).all()
        )
        if not portfolios:
            return "No portfolio positions on file."
        lines: list[str] = []
        for p in portfolios:
            for pos in p.positions:
                lines.append(f"{pos.symbol}: {pos.shares} shares @ avg ${pos.average_cost:.2f}")
        if not lines:
            return "No positions in portfolio."
        return "; ".join(lines[:15])  # cap at 15 positions to keep prompt short
    except Exception as e:
        logger.debug(f"Could not load portfolio for voice prompt: {e}")
        return "Portfolio data unavailable."


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
            model="claude-haiku-4-5",
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
        return f"AI temporarily unavailable: {str(e)[:100]}", []


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

    # Build system prompt
    portfolio_summary = _get_portfolio_summary(db, current_user.id)
    context_hint = {
        "portfolio": "Focus on the user's specific portfolio holdings and positions.",
        "market": "Focus on current market conditions, macro trends, and sector analysis.",
        "general": "Answer general investing and financial questions.",
    }.get(body.context, "")
    system_prompt = (
        f"You are BMG Capital's AI advisor. {context_hint} "
        f"The user's portfolio: {portfolio_summary}. "
        "Answer in 1-3 sentences, spoken-language style. Always cite your reasoning. "
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
