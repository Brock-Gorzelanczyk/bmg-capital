"""The Forge API — user-built custom bots with combined strategies + watchlists.

Feature-flagged: set ENABLE_STRATEGY_FORGE=true in Railway to activate.

Endpoints:
  GET  /api/forge/catalog           — list available strategies (same as Scout catalog)
  GET  /api/forge/bots              — list user's forge bots
  POST /api/forge/bots              — create a forge bot (wizard final step)
  GET  /api/forge/bots/{id}         — get one forge bot detail
  PUT  /api/forge/bots/{id}         — update forge bot config
  PATCH /api/forge/bots/{id}/status — pause / resume
  DELETE /api/forge/bots/{id}       — soft-delete
  GET  /api/forge/signals           — last 50 user forge signals
  GET  /api/forge/bots/{id}/signals — signals for one forge bot
"""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from strategy_lab.scout_catalog import SCOUT_CATALOG, list_catalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forge", tags=["forge"])


def _forge_enabled() -> None:
    if not os.getenv("ENABLE_STRATEGY_FORGE", "false").strip().lower() == "true":
        raise HTTPException(status_code=404, detail="Strategy Forge not enabled")


def _bot_to_dict(bot, signal_count: int = 0) -> dict:
    return {
        "id": bot.id,
        "name": bot.name,
        "description": bot.description,
        "status": bot.status,
        "strategies": json.loads(bot.strategies or "[]"),
        "watchlist": json.loads(bot.watchlist or "[]"),
        "capital_pct": bot.capital_pct,
        "created_at": bot.created_at.isoformat() if bot.created_at else None,
        "last_scanned_at": bot.last_scanned_at.isoformat() if bot.last_scanned_at else None,
        "last_fired_at": bot.last_fired_at.isoformat() if bot.last_fired_at else None,
        "signal_count": signal_count,
    }


def _signal_to_dict(r, bot_name: str) -> dict:
    return {
        "id": r.id,
        "forge_bot_id": r.forge_bot_id,
        "bot_name": bot_name,
        "ticker": r.ticker,
        "strategy_id": r.strategy_id,
        "display_name": SCOUT_CATALOG.get(r.strategy_id, {}).get("display_name", r.strategy_id),
        "side": r.side,
        "confidence": r.confidence,
        "entry_price": r.entry_price,
        "stop_price": r.stop_price,
        "target_price": r.target_price,
        "reason": r.reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog(_: None = Depends(_forge_enabled)):
    return {"strategies": list_catalog()}


@router.get("/bots")
def list_bots(
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot, UserForgeSignal

    bots = (
        db.query(UserForgeBot)
        .filter(
            UserForgeBot.user_id == current_user.id,
            UserForgeBot.status != "deleted",
        )
        .order_by(UserForgeBot.created_at.desc())
        .all()
    )
    result = []
    for bot in bots:
        count = (
            db.query(func.count(UserForgeSignal.id))
            .filter(UserForgeSignal.forge_bot_id == bot.id)
            .scalar() or 0
        )
        result.append(_bot_to_dict(bot, count))
    return {"bots": result}


@router.post("/bots")
def create_bot(
    body: dict = Body(...),
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot

    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    strategies = body.get("strategies") or []
    watchlist = body.get("watchlist") or []

    if not isinstance(strategies, list):
        raise HTTPException(status_code=422, detail="strategies must be a list")
    if not isinstance(watchlist, list):
        raise HTTPException(status_code=422, detail="watchlist must be a list")

    invalid = [s for s in strategies if s not in SCOUT_CATALOG]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unknown strategy IDs: {invalid}")

    active_count = (
        db.query(UserForgeBot)
        .filter(UserForgeBot.user_id == current_user.id, UserForgeBot.status != "deleted")
        .count()
    )
    if active_count >= 10:
        raise HTTPException(status_code=422, detail="Maximum 10 forge bots per user")

    capital_pct = max(0.1, min(float(body.get("capital_pct") or 5.0), 100.0))

    bot = UserForgeBot(
        user_id=current_user.id,
        name=name,
        description=(body.get("description") or "").strip() or None,
        status="active",
        strategies=json.dumps([s for s in strategies if s in SCOUT_CATALOG]),
        watchlist=json.dumps([t.strip().upper() for t in watchlist if t.strip()]),
        capital_pct=capital_pct,
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return _bot_to_dict(bot)


@router.get("/bots/{bot_id}")
def get_bot(
    bot_id: int,
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot, UserForgeSignal

    bot = db.get(UserForgeBot, bot_id)
    if not bot or bot.user_id != current_user.id or bot.status == "deleted":
        raise HTTPException(status_code=404, detail="Forge bot not found")
    count = (
        db.query(func.count(UserForgeSignal.id))
        .filter(UserForgeSignal.forge_bot_id == bot_id)
        .scalar() or 0
    )
    return _bot_to_dict(bot, count)


@router.put("/bots/{bot_id}")
def update_bot(
    bot_id: int,
    body: dict = Body(...),
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot

    bot = db.get(UserForgeBot, bot_id)
    if not bot or bot.user_id != current_user.id or bot.status == "deleted":
        raise HTTPException(status_code=404, detail="Forge bot not found")

    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name cannot be empty")
        bot.name = name
    if "description" in body:
        bot.description = (body["description"] or "").strip() or None
    if "strategies" in body:
        strats = body["strategies"] or []
        invalid = [s for s in strats if s not in SCOUT_CATALOG]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Unknown strategy IDs: {invalid}")
        bot.strategies = json.dumps(strats)
    if "watchlist" in body:
        bot.watchlist = json.dumps([t.strip().upper() for t in (body["watchlist"] or []) if t.strip()])
    if "capital_pct" in body:
        bot.capital_pct = max(0.1, min(float(body["capital_pct"] or 5.0), 100.0))

    db.commit()
    db.refresh(bot)
    return _bot_to_dict(bot)


@router.patch("/bots/{bot_id}/status")
def update_bot_status(
    bot_id: int,
    body: dict = Body(...),
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot

    bot = db.get(UserForgeBot, bot_id)
    if not bot or bot.user_id != current_user.id or bot.status == "deleted":
        raise HTTPException(status_code=404, detail="Forge bot not found")

    new_status = (body.get("status") or "").strip().lower()
    if new_status not in ("active", "paused"):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'paused'")

    bot.status = new_status
    db.commit()
    return {"ok": True, "status": bot.status}


@router.delete("/bots/{bot_id}")
def delete_bot(
    bot_id: int,
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot

    bot = db.get(UserForgeBot, bot_id)
    if not bot or bot.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Forge bot not found")
    bot.status = "deleted"
    db.commit()
    return {"ok": True}


@router.get("/signals")
def get_signals(
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot, UserForgeSignal

    rows = (
        db.query(UserForgeSignal)
        .filter(UserForgeSignal.user_id == current_user.id)
        .order_by(UserForgeSignal.created_at.desc())
        .limit(50)
        .all()
    )
    bot_names: dict[int, str] = {}
    for r in rows:
        if r.forge_bot_id not in bot_names:
            bot = db.get(UserForgeBot, r.forge_bot_id)
            bot_names[r.forge_bot_id] = bot.name if bot else str(r.forge_bot_id)

    return {"signals": [_signal_to_dict(r, bot_names.get(r.forge_bot_id, "")) for r in rows]}


@router.get("/bots/{bot_id}/signals")
def get_bot_signals(
    bot_id: int,
    _: None = Depends(_forge_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.forge import UserForgeBot, UserForgeSignal

    bot = db.get(UserForgeBot, bot_id)
    if not bot or bot.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Forge bot not found")

    rows = (
        db.query(UserForgeSignal)
        .filter(UserForgeSignal.forge_bot_id == bot_id)
        .order_by(UserForgeSignal.created_at.desc())
        .limit(50)
        .all()
    )
    return {"signals": [_signal_to_dict(r, bot.name) for r in rows]}
