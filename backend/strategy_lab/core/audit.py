"""Audit helpers — persist signals, fills, and daily P&L to the database."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy.orm import Session

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)


def _write_to_bridge_postgres(
    signal_id: int,
    allocation_id: int,
    user_id: int,
    profile_id: int,
    profile_name: str,
    ts: datetime,
    symbol: str,
    side: str,
    confidence: float,
    size_hint: Optional[float],
    reason: Optional[str],
    strategy: Optional[str],
    entry_price: Optional[float],
    stop_price: Optional[float],
    target_price: Optional[float],
    is_test: bool = False,
    starting_capital_cents: Optional[int] = None,
) -> None:
    """Best-effort write to discord-worker's Postgres bridge.

    Mirrors the signal row (plus its referenced allocation and profile rows)
    into the Railway Postgres that the discord-worker polls. Never blocks or
    raises — failures are logged and swallowed.
    """
    import os
    bridge_url = os.environ.get("DISCORD_BRIDGE_DATABASE_URL")
    if not bridge_url:
        return
    try:
        import psycopg2
        with psycopg2.connect(bridge_url) as conn:
            with conn.cursor() as cur:
                # Mirror bot_profiles row (ON CONFLICT is idempotent)
                cur.execute(
                    "INSERT INTO bot_profiles (id, name) VALUES (%s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (profile_id, profile_name),
                )
                # Mirror bot_allocations row — upsert so starting_capital_cents stays current
                cur.execute(
                    "INSERT INTO bot_allocations (id, user_id, profile_id, starting_capital_cents) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET starting_capital_cents = EXCLUDED.starting_capital_cents",
                    (allocation_id, user_id, profile_id, starting_capital_cents),
                )
                # Write signal row
                cur.execute(
                    """
                    INSERT INTO bot_signals
                      (allocation_id, ts, symbol, side, confidence, size_hint,
                       reason, strategy, entry_price, stop_price, target_price,
                       discord_posted_at, is_test)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (allocation_id, ts, symbol, side, confidence, size_hint,
                     reason, strategy, entry_price, stop_price, target_price,
                     is_test),
                )
            conn.commit()
        logger.debug("[bridge] signal %d (%s %s) → discord-worker Postgres", signal_id, side, symbol)
    except Exception as exc:
        logger.warning("[bridge] write failed for signal %d: %s", signal_id, exc)


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
) -> Optional[int]:
    """Persist a Signal to bot_signals, then fire Discord embed in background.

    Returns the new row's id, or None if the insert failed.
    """
    from app.db.models.bots import BotSignal, BotAllocation, BotProfile

    # Always persist stop and target — compute defaults if caller omitted them.
    # Discord embed and frontend both require these to show all three price levels.
    if entry_price:
        is_buy = signal.side in ("buy", "cover")
        if stop_price is None:
            stop_price = entry_price * 0.93 if is_buy else entry_price * 1.07
            logger.warning(
                "log_signal: stop_price missing for %s %s — defaulting to %.5f",
                signal.side, signal.symbol, stop_price,
            )
        if target_price is None:
            target_price = entry_price * 1.10 if is_buy else entry_price * 0.90
            logger.warning(
                "log_signal: target_price missing for %s %s — defaulting to %.5f",
                signal.side, signal.symbol, target_price,
            )

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
        return None

    # Resolve bot profile name + starting capital for embed routing
    profile_name = ""
    _user_id = 0
    _profile_id = 0
    _starting_capital_cents: Optional[int] = None
    try:
        alloc = db.get(BotAllocation, allocation_id)
        if alloc:
            _user_id = alloc.user_id or 0
            _profile_id = alloc.profile_id or 0
            _starting_capital_cents = alloc.starting_capital_cents
            prof = db.get(BotProfile, alloc.profile_id)
            if prof:
                profile_name = prof.name
    except Exception:
        pass

    # Bridge write: mirror to discord-worker's Postgres (best-effort, non-blocking)
    threading.Thread(
        target=_write_to_bridge_postgres,
        args=(
            row.id, allocation_id, _user_id, _profile_id, profile_name,
            signal.ts, signal.symbol, signal.side, signal.confidence,
            signal.size_hint, signal.reason, signal.strategy,
            entry_price or None, stop_price or None, target_price or None,
        ),
        kwargs={"is_test": False, "starting_capital_cents": _starting_capital_cents},
        daemon=True,
    ).start()

    signal_dict = {
        "bot":                    profile_name,
        "symbol":                 signal.symbol,
        "side":                   signal.side,
        "confidence":             signal.confidence,
        "reason":                 signal.reason or "",
        "strategy":               signal.strategy or "",
        "size_pct":               round(signal.size_hint * 100, 1) if signal.size_hint else None,
        "price":                  entry_price or None,
        "stop":                   stop_price or None,
        "target":                 target_price or None,
        "starting_capital_cents": _starting_capital_cents,
    }

    threading.Thread(
        target=_post_signal_to_discord,
        args=(row.id, signal_dict),
        daemon=True,
    ).start()

    return row.id


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
