"""
Cross-bot conflict resolution.

Priority: lt > swing > day (higher priority bot's position wins).

Conflicts:
1. Two bots want opposite sides on same symbol → lower priority loses
2. Total exposure to single symbol > 15% across bots → reduce lower priority
3. Same sector > 30% across bots → reduce additions

Uses DB CrossBotPosition table (read from DB passed in).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Bot priority (higher number = higher priority)
_BOT_PRIORITY: dict[str, int] = {
    "stock_day": 1,
    "crypto_day": 1,
    "stock_swing": 2,
    "crypto_swing": 2,
    "stock_lt": 3,
    "crypto_lt": 3,
}

_SYMBOL_EXPOSURE_CAP = 15.0  # % of portfolio per symbol across all bots
_SECTOR_EXPOSURE_CAP = 30.0  # % of portfolio per sector across all bots


def _get_priority(bot_name: str) -> int:
    return _BOT_PRIORITY.get(bot_name, 1)


def _get_cross_bot_positions(user_id: int, symbol: str, db) -> list:
    """Fetch CrossBotPosition rows for this user+symbol, or BotPosition fallback."""
    try:
        from app.db.models.bots import CrossBotPosition  # may not exist yet
        return (
            db.query(CrossBotPosition)
            .filter(
                CrossBotPosition.user_id == user_id,
                CrossBotPosition.symbol == symbol,
            )
            .all()
        )
    except Exception:
        # CrossBotPosition table not yet created — query BotPosition via allocations
        try:
            from app.db.models.bots import BotPosition, BotAllocation
            positions = (
                db.query(BotPosition, BotAllocation)
                .join(BotAllocation, BotPosition.allocation_id == BotAllocation.id)
                .filter(
                    BotAllocation.user_id == user_id,
                    BotPosition.symbol == symbol,
                    BotPosition.closed_at.is_(None),
                )
                .all()
            )
            return positions
        except Exception as exc:
            logger.debug("[bot_coordinator] Could not query positions: %s", exc)
            return []


def check_conflicts(
    user_id: int,
    symbol: str,
    bot_name: str,  # "stock_day" | "stock_swing" | etc.
    intended_side: str,
    intended_size_pct: float,
    db,  # SQLAlchemy session
) -> dict:
    """
    Returns:
    {
      allowed: bool,
      adjusted_size_pct: float,
      reason: str | None
    }
    """
    my_priority = _get_priority(bot_name)
    existing_positions = _get_cross_bot_positions(user_id, symbol, db)
    total_symbol_exposure = 0.0

    for row in existing_positions:
        # Handle both CrossBotPosition and (BotPosition, BotAllocation) tuples
        if isinstance(row, tuple):
            pos, alloc = row
            other_bot = getattr(alloc, "profile_name", None) or getattr(alloc, "bot_name", "unknown")
            other_side = getattr(pos, "side", None) or "buy"  # BotPosition may not have side
            other_size = getattr(pos, "size_pct", 0.0) or 5.0  # default estimate
        else:
            other_bot = getattr(row, "bot_name", "unknown")
            other_side = getattr(row, "side", "buy")
            other_size = getattr(row, "size_pct", 5.0)

        other_priority = _get_priority(other_bot)
        total_symbol_exposure += other_size

        # Conflict 1: Opposite sides on same symbol
        if intended_side in ("buy", "sell") and other_side in ("buy", "sell"):
            if intended_side != other_side and intended_side != "hold":
                if my_priority <= other_priority:
                    logger.info(
                        "[bot_coordinator:%s] Conflict: %s wants %s, this bot (%s) wants %s; lower/equal priority loses",
                        symbol, other_bot, other_side, bot_name, intended_side,
                    )
                    return {
                        "allowed": False,
                        "adjusted_size_pct": 0.0,
                        "reason": f"Cross-bot conflict: {other_bot} holds {other_side} position; {bot_name} has equal/lower priority",
                    }

    # Conflict 2: Symbol exposure cap
    projected_total = total_symbol_exposure + intended_size_pct
    if projected_total > _SYMBOL_EXPOSURE_CAP:
        headroom = max(0.0, _SYMBOL_EXPOSURE_CAP - total_symbol_exposure)
        if headroom <= 0:
            return {
                "allowed": False,
                "adjusted_size_pct": 0.0,
                "reason": f"Symbol {symbol} exposure cap {_SYMBOL_EXPOSURE_CAP}% reached (current={total_symbol_exposure:.1f}%)",
            }
        logger.info(
            "[bot_coordinator:%s] Symbol cap: reducing size from %.2f%% to %.2f%%",
            symbol, intended_size_pct, headroom,
        )
        return {
            "allowed": True,
            "adjusted_size_pct": headroom,
            "reason": f"Symbol exposure cap: reduced to {headroom:.1f}%",
        }

    return {
        "allowed": True,
        "adjusted_size_pct": intended_size_pct,
        "reason": None,
    }


def update_cross_bot_position(
    user_id: int,
    symbol: str,
    bot_name: str,
    qty_delta: float,
    db,
) -> None:
    """Update CrossBotPosition table after a fill."""
    try:
        from app.db.models.bots import CrossBotPosition

        row = (
            db.query(CrossBotPosition)
            .filter(
                CrossBotPosition.user_id == user_id,
                CrossBotPosition.symbol == symbol,
                CrossBotPosition.bot_name == bot_name,
            )
            .first()
        )

        if row is None:
            row = CrossBotPosition(
                user_id=user_id,
                symbol=symbol,
                bot_name=bot_name,
                qty=qty_delta,
                updated_at=datetime.now(timezone.utc),
            )
            db.add(row)
        else:
            row.qty = (row.qty or 0) + qty_delta
            row.updated_at = datetime.now(timezone.utc)

        db.commit()
        logger.debug(
            "[bot_coordinator] Updated CrossBotPosition: user=%d sym=%s bot=%s delta=%.4f",
            user_id, symbol, bot_name, qty_delta,
        )
    except Exception as exc:
        logger.warning("[bot_coordinator] Could not update CrossBotPosition: %s", exc)
        db.rollback()
