"""Audit helpers — persist signals, fills, and daily P&L to the database."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy.orm import Session

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)


def _post_signal_to_discord(signal_id: int, signal_dict: dict) -> None:
    """Background thread: post to Discord and stamp discord_posted_at.

    Creates its own DB session so it never blocks or shares state with
    the caller's session.  Discord failures are logged and swallowed.
    """
    try:
        from app.services.discord_public import post_signal
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            post_signal(signal_dict, db=db, signal_id=signal_id)
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Discord signal post skipped: %s", exc)


def log_signal(
    db: Session,
    allocation_id: int,
    signal: Signal,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
) -> None:
    """Persist a Signal to bot_signals, then fire Discord embed in background."""
    from app.db.models.bots import BotSignal, BotAllocation, BotProfile

    row = BotSignal(
        allocation_id=allocation_id,
        ts=signal.ts,
        symbol=signal.symbol,
        side=signal.side,
        confidence=signal.confidence,
        size_hint=signal.size_hint,
        reason=signal.reason,
        strategy=signal.strategy,
        entry_price=entry_price or None,
        stop_price=stop_price or None,
        target_price=target_price or None,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        logger.debug("Logged signal: %s %s %.0f%%", signal.side, signal.symbol, signal.confidence * 100)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to log signal: %s", exc)
        return

    # Resolve bot profile name for embed routing (session-cached, no extra queries)
    profile_name = ""
    try:
        alloc = db.get(BotAllocation, allocation_id)
        if alloc:
            prof = db.get(BotProfile, alloc.profile_id)
            if prof:
                profile_name = prof.name
    except Exception:
        pass

    signal_dict = {
        "bot":        profile_name,
        "symbol":     signal.symbol,
        "side":       signal.side,
        "confidence": signal.confidence,
        "reason":     signal.reason or "",
        "strategy":   signal.strategy or "",
        "size_pct":   round(signal.size_hint * 100, 1) if signal.size_hint else None,
        "price":      entry_price or None,
        "stop":       stop_price or None,
        "target":     target_price or None,
    }

    threading.Thread(
        target=_post_signal_to_discord,
        args=(row.id, signal_dict),
        daemon=True,
    ).start()


def log_fill(
    db: Session,
    allocation_id: int,
    symbol: str,
    side: str,
    qty: float,
    fill_price_cents: int,
    ts: Optional[datetime] = None,
    alpaca_order_id: Optional[str] = None,
    position_id: Optional[int] = None,
    is_paper: bool = True,
    fees_cents: int = 0,
) -> None:
    """Persist a filled trade to bot_trades."""
    from app.db.models.bots import BotTrade

    row = BotTrade(
        allocation_id=allocation_id,
        symbol=symbol,
        side=side,
        qty=qty,
        fill_price_cents=fill_price_cents,
        fees_cents=fees_cents,
        ts=ts or datetime.now(timezone.utc),
        alpaca_order_id=alpaca_order_id,
        position_id=position_id,
        is_paper=is_paper,
    )
    db.add(row)
    try:
        db.commit()
        logger.debug("Logged fill: %s %s x%.4f @ $%.2f", side, symbol, qty, fill_price_cents / 100)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to log fill: %s", exc)


def log_daily_pnl(
    db: Session,
    allocation_id: int,
    pnl_date: date,
    realized_cents: int,
    unrealized_cents: int,
    fees_cents: int = 0,
) -> None:
    """Upsert a BotDailyPnL row."""
    from app.db.models.bots import BotDailyPnL

    existing = (
        db.query(BotDailyPnL)
        .filter(BotDailyPnL.allocation_id == allocation_id, BotDailyPnL.date == pnl_date)
        .first()
    )
    if existing:
        existing.realized_cents = realized_cents
        existing.unrealized_cents = unrealized_cents
        existing.fees_cents = fees_cents
    else:
        db.add(BotDailyPnL(
            allocation_id=allocation_id,
            date=pnl_date,
            realized_cents=realized_cents,
            unrealized_cents=unrealized_cents,
            fees_cents=fees_cents,
        ))
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to log daily P&L: %s", exc)
