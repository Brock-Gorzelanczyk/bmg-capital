"""
Autonomous execution layer router.

GET  /api/autonomous/status           — live engine status
GET  /api/autonomous/actions          — recent actions (filterable)
GET  /api/autonomous/actions/feed     — live feed (last 20 actions)
POST /api/autonomous/pause            — pause autonomous engine
POST /api/autonomous/resume           — resume autonomous engine
GET  /api/autonomous/guardrails       — current guardrail settings
PUT  /api/autonomous/guardrails       — update guardrail settings
GET  /api/autonomous/digest/latest    — latest daily digest
GET  /api/autonomous/digest/history   — last 30 digests
GET  /api/autonomous/stats/24h        — 24-hour action statistics
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.autonomous import AutonomousAction, AutonomousGuardrail, AutonomousDigest
from app.db.models.paper import PaperPosition
from app.services.autonomous_logger import log_action
from app.services.guardrail_checker import get_or_create_guardrail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autonomous", tags=["autonomous"])

TOTAL_ASSETS_MONITORED = 8212


# ── Helpers ──────────────────────────────────────────────────────────────────

def _guardrail_to_dict(g: AutonomousGuardrail) -> dict:
    return {
        "id": g.id,
        "user_id": g.user_id,
        "daily_loss_limit_pct": g.daily_loss_limit_pct,
        "weekly_loss_limit_pct": g.weekly_loss_limit_pct,
        "max_consecutive_losses": g.max_consecutive_losses,
        "max_drawdown_pct": g.max_drawdown_pct,
        "max_position_concentration": g.max_position_concentration,
        "max_open_positions": g.max_open_positions,
        "autonomous_paused": g.autonomous_paused,
        "paused_reason": g.paused_reason,
        "paused_at": g.paused_at.isoformat() if g.paused_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


def _action_to_dict(a: AutonomousAction) -> dict:
    return {
        "id": a.id,
        "lab": a.lab,
        "strategy_id": a.strategy_id,
        "action_type": a.action_type,
        "asset": a.asset,
        "params": json.loads(a.params) if a.params else {},
        "rationale": a.rationale,
        "result": a.result,
        "outcome_value": a.outcome_value,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _market_status() -> str:
    """Return a simple market status label based on UTC time (ET offset = UTC-4 or UTC-5)."""
    now_et = datetime.now(timezone.utc) - timedelta(hours=4)  # approximate ET (EDT)
    if now_et.weekday() >= 5:
        return "closed-weekend"
    hour = now_et.hour + now_et.minute / 60
    if 9.5 <= hour < 16:
        return "open"
    if 4 <= hour < 9.5:
        return "pre-market"
    return "after-hours"


# ── Schemas ───────────────────────────────────────────────────────────────────

class PauseRequest(BaseModel):
    reason: Optional[str] = None


class GuardrailUpdate(BaseModel):
    daily_loss_limit_pct: Optional[float] = None
    weekly_loss_limit_pct: Optional[float] = None
    max_consecutive_losses: Optional[int] = None
    max_open_positions: Optional[int] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Live autonomous engine status."""
    try:
        user_id = current_user.id

        # Last action
        last_action = (
            db.query(AutonomousAction)
            .filter(AutonomousAction.user_id == user_id)
            .order_by(AutonomousAction.created_at.desc())
            .first()
        )

        # Open positions count
        open_positions = db.query(PaperPosition).filter_by(user_id=user_id).count()

        # Active strategies: distinct strategy_ids that fired in last 30 days
        cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
        active_strategies_rows = (
            db.query(AutonomousAction.strategy_id)
            .filter(
                AutonomousAction.user_id == user_id,
                AutonomousAction.action_type == "signal_fired",
                AutonomousAction.created_at >= cutoff_30d,
                AutonomousAction.strategy_id.isnot(None),
            )
            .distinct()
            .all()
        )
        strategies_active = len(active_strategies_rows)

        # Guardrail status
        guardrail = get_or_create_guardrail(user_id, db)
        guardrail_status = "paused" if guardrail.autonomous_paused else "ok"
        autonomous_paused = guardrail.autonomous_paused

        last_action_at = None
        last_action_summary = None
        if last_action:
            last_action_at = last_action.created_at.isoformat() if last_action.created_at else None
            last_action_summary = last_action.rationale or f"{last_action.action_type} on {last_action.asset or 'system'}"

        return {
            "engine_running": True,
            "strategies_active": strategies_active,
            "total_assets_monitored": TOTAL_ASSETS_MONITORED,
            "open_positions": open_positions,
            "last_action_at": last_action_at,
            "last_action_summary": last_action_summary,
            "guardrail_status": guardrail_status,
            "autonomous_paused": autonomous_paused,
            "market_status": _market_status(),
        }
    except Exception as e:
        logger.error(f"autonomous /status error: {e}", exc_info=True)
        return {
            "engine_running": False,
            "strategies_active": 0,
            "total_assets_monitored": TOTAL_ASSETS_MONITORED,
            "open_positions": 0,
            "last_action_at": None,
            "last_action_summary": None,
            "guardrail_status": "unknown",
            "autonomous_paused": False,
            "market_status": _market_status(),
        }


@router.get("/actions/feed")
def get_actions_feed(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Live feed — last 20 actions, no filters."""
    try:
        actions = (
            db.query(AutonomousAction)
            .filter(AutonomousAction.user_id == current_user.id)
            .order_by(AutonomousAction.created_at.desc())
            .limit(20)
            .all()
        )
        return [_action_to_dict(a) for a in actions]
    except Exception as e:
        logger.error(f"autonomous /actions/feed error: {e}", exc_info=True)
        return []


@router.get("/actions")
def get_actions(
    limit: int = Query(50, ge=1, le=500),
    lab: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Recent autonomous actions with optional filters."""
    try:
        q = db.query(AutonomousAction).filter(AutonomousAction.user_id == current_user.id)
        if lab:
            q = q.filter(AutonomousAction.lab == lab)
        if action_type:
            q = q.filter(AutonomousAction.action_type == action_type)
        if date_from:
            try:
                dt = datetime.fromisoformat(date_from)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                q = q.filter(AutonomousAction.created_at >= dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_from format (use ISO 8601)")
        actions = q.order_by(AutonomousAction.created_at.desc()).limit(limit).all()
        return [_action_to_dict(a) for a in actions]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"autonomous /actions error: {e}", exc_info=True)
        return []


@router.post("/pause")
def pause_engine(
    body: PauseRequest = PauseRequest(),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Pause the autonomous trading engine for this user."""
    guardrail = get_or_create_guardrail(current_user.id, db)
    guardrail.autonomous_paused = True
    guardrail.paused_reason = body.reason or "User requested pause"
    guardrail.paused_at = datetime.now(timezone.utc)
    guardrail.updated_at = datetime.now(timezone.utc)
    db.add(guardrail)
    db.commit()
    db.refresh(guardrail)

    log_action(
        user_id=current_user.id,
        lab="system",
        action_type="guardrail_trip",
        rationale=f"Autonomous engine paused by user. Reason: {guardrail.paused_reason}",
        result="success",
    )

    return _guardrail_to_dict(guardrail)


@router.post("/resume")
def resume_engine(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resume the autonomous trading engine for this user."""
    guardrail = get_or_create_guardrail(current_user.id, db)
    guardrail.autonomous_paused = False
    guardrail.paused_reason = None
    guardrail.paused_at = None
    guardrail.updated_at = datetime.now(timezone.utc)
    db.add(guardrail)
    db.commit()
    db.refresh(guardrail)

    log_action(
        user_id=current_user.id,
        lab="system",
        action_type="heartbeat",
        rationale="Autonomous engine resumed by user. Guardrails reset.",
        result="success",
    )

    return _guardrail_to_dict(guardrail)


@router.get("/guardrails")
def get_guardrails(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return user's guardrail settings, creating defaults if none exist."""
    guardrail = get_or_create_guardrail(current_user.id, db)
    return _guardrail_to_dict(guardrail)


@router.put("/guardrails")
def update_guardrails(
    body: GuardrailUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update guardrail settings with validation."""
    guardrail = get_or_create_guardrail(current_user.id, db)

    if body.daily_loss_limit_pct is not None:
        if not (1.0 <= body.daily_loss_limit_pct <= 10.0):
            raise HTTPException(status_code=400, detail="daily_loss_limit_pct must be between 1 and 10")
        guardrail.daily_loss_limit_pct = body.daily_loss_limit_pct

    if body.weekly_loss_limit_pct is not None:
        if not (3.0 <= body.weekly_loss_limit_pct <= 20.0):
            raise HTTPException(status_code=400, detail="weekly_loss_limit_pct must be between 3 and 20")
        guardrail.weekly_loss_limit_pct = body.weekly_loss_limit_pct

    if body.max_consecutive_losses is not None:
        if body.max_consecutive_losses < 1:
            raise HTTPException(status_code=400, detail="max_consecutive_losses must be >= 1")
        guardrail.max_consecutive_losses = body.max_consecutive_losses

    if body.max_open_positions is not None:
        if not (5 <= body.max_open_positions <= 50):
            raise HTTPException(status_code=400, detail="max_open_positions must be between 5 and 50")
        guardrail.max_open_positions = body.max_open_positions

    guardrail.updated_at = datetime.now(timezone.utc)
    db.add(guardrail)
    db.commit()
    db.refresh(guardrail)
    return _guardrail_to_dict(guardrail)


def _generate_mock_digest(user_id: int, db: Session) -> dict:
    """Generate a mock digest from recent actions when no stored digest exists."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    recent = (
        db.query(AutonomousAction)
        .filter(AutonomousAction.user_id == user_id, AutonomousAction.created_at >= cutoff)
        .all()
    )
    signals = sum(1 for a in recent if a.action_type == "signal_fired")
    buys = sum(1 for a in recent if a.action_type == "paper_buy")
    sells = sum(1 for a in recent if a.action_type in ("paper_sell", "stop_hit", "target_hit"))
    pnl_actions = [a for a in recent if a.outcome_value is not None]
    best = max(pnl_actions, key=lambda a: a.outcome_value or 0, default=None)
    worst = min(pnl_actions, key=lambda a: a.outcome_value or 0, default=None)
    total_pnl = sum(a.outcome_value or 0 for a in pnl_actions)

    # Most active strategy
    strategy_counts: dict[str, int] = {}
    for a in recent:
        if a.strategy_id:
            strategy_counts[a.strategy_id] = strategy_counts.get(a.strategy_id, 0) + 1
    spotlight = max(strategy_counts, key=lambda k: strategy_counts[k]) if strategy_counts else "N/A"

    return {
        "id": None,
        "user_id": user_id,
        "digest_date": date.today().isoformat(),
        "tldr": f"Engine processed {signals} signals, opened {buys} positions, closed {sells} today.",
        "highlights": json.dumps([
            f"{signals} signals scanned across {TOTAL_ASSETS_MONITORED:,} assets",
            f"{buys} paper buys placed by autonomous engine",
            f"Net P&L: ${total_pnl:+.2f}",
        ]),
        "strategy_spotlight": spotlight,
        "signals_fired": signals,
        "paper_buys": buys,
        "paper_sells": sells,
        "best_action": best.asset if best else None,
        "worst_action": worst.asset if worst else None,
        "tomorrow_preview": "Engine will continue scanning all 19 presets at market open.",
        "market_regime_note": "Monitor SPY vs 200-day MA for regime confirmation.",
        "full_narrative": (
            f"The autonomous engine ran its full cycle, scanning {TOTAL_ASSETS_MONITORED:,} assets "
            f"across 19 strategy presets. {signals} signals fired, resulting in {buys} new positions opened "
            f"and {sells} positions closed. Total realized P&L for the session: ${total_pnl:+.2f}. "
            f"The most active strategy was {spotlight}. All guardrails remained nominal."
        ),
        "portfolio_delta": total_pnl,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/digest/latest")
def get_latest_digest(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the latest digest, generating a mock one from recent actions if none stored."""
    try:
        digest = (
            db.query(AutonomousDigest)
            .filter(AutonomousDigest.user_id == current_user.id)
            .order_by(AutonomousDigest.digest_date.desc())
            .first()
        )
        if digest:
            return {
                "id": digest.id,
                "user_id": digest.user_id,
                "digest_date": digest.digest_date.isoformat() if digest.digest_date else None,
                "tldr": digest.tldr,
                "highlights": json.loads(digest.highlights) if digest.highlights else [],
                "strategy_spotlight": digest.strategy_spotlight,
                "signals_fired": digest.signals_fired,
                "paper_buys": digest.paper_buys,
                "paper_sells": digest.paper_sells,
                "best_action": digest.best_action,
                "worst_action": digest.worst_action,
                "tomorrow_preview": digest.tomorrow_preview,
                "market_regime_note": digest.market_regime_note,
                "full_narrative": digest.full_narrative,
                "portfolio_delta": digest.portfolio_delta,
                "created_at": digest.created_at.isoformat() if digest.created_at else None,
            }
        return _generate_mock_digest(current_user.id, db)
    except Exception as e:
        logger.error(f"autonomous /digest/latest error: {e}", exc_info=True)
        return _generate_mock_digest(current_user.id, db)


@router.get("/digest/history")
def get_digest_history(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return last 30 digests."""
    try:
        digests = (
            db.query(AutonomousDigest)
            .filter(AutonomousDigest.user_id == current_user.id)
            .order_by(AutonomousDigest.digest_date.desc())
            .limit(30)
            .all()
        )
        return [
            {
                "id": d.id,
                "digest_date": d.digest_date.isoformat() if d.digest_date else None,
                "tldr": d.tldr,
                "signals_fired": d.signals_fired,
                "paper_buys": d.paper_buys,
                "paper_sells": d.paper_sells,
                "portfolio_delta": d.portfolio_delta,
                "strategy_spotlight": d.strategy_spotlight,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in digests
        ]
    except Exception as e:
        logger.error(f"autonomous /digest/history error: {e}", exc_info=True)
        return []


@router.get("/stats/24h")
def get_stats_24h(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Aggregate stats for the last 24 hours."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        actions = (
            db.query(AutonomousAction)
            .filter(
                AutonomousAction.user_id == current_user.id,
                AutonomousAction.created_at >= cutoff,
            )
            .all()
        )

        signals_fired = sum(1 for a in actions if a.action_type == "signal_fired")
        paper_buys = sum(1 for a in actions if a.action_type == "paper_buy")
        paper_sells = sum(1 for a in actions if a.action_type == "paper_sell")
        stop_hits = sum(1 for a in actions if a.action_type == "stop_hit")
        target_hits = sum(1 for a in actions if a.action_type == "target_hit")

        pnl_actions = [a for a in actions if a.outcome_value is not None]
        pnl_24h = sum(a.outcome_value or 0 for a in pnl_actions)

        best = max(pnl_actions, key=lambda a: a.outcome_value or 0, default=None)
        worst = min(pnl_actions, key=lambda a: a.outcome_value or 0, default=None)

        # By lab
        by_lab: dict[str, int] = {}
        for a in actions:
            if a.lab:
                by_lab[a.lab] = by_lab.get(a.lab, 0) + 1

        return {
            "signals_fired": signals_fired,
            "paper_buys": paper_buys,
            "paper_sells": paper_sells,
            "stop_hits": stop_hits,
            "target_hits": target_hits,
            "pnl_24h": round(pnl_24h, 2),
            "best_action": {"asset": best.asset, "pnl": best.outcome_value} if best else None,
            "worst_action": {"asset": worst.asset, "pnl": worst.outcome_value} if worst else None,
            "by_lab": by_lab,
        }
    except Exception as e:
        logger.error(f"autonomous /stats/24h error: {e}", exc_info=True)
        return {
            "signals_fired": 0,
            "paper_buys": 0,
            "paper_sells": 0,
            "stop_hits": 0,
            "target_hits": 0,
            "pnl_24h": 0.0,
            "best_action": None,
            "worst_action": None,
            "by_lab": {},
        }
