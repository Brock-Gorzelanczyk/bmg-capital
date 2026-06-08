"""Stop management — place, ratchet, and ensure stops on BotPositions.

Used by stock_day and stock_swing bots. All functions are idempotent:
calling them on a position that already has a stop is a safe no-op.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def place_initial_stop(
    db,
    position_id: int,
    fill_price: float,
    stop_pct: float,
) -> Optional[str]:
    """Set stop_price_usd on a BotPosition if it isn't already set.

    Returns a paper stop reference string, or None on failure.
    The position monitor enforces the stop — no real broker order in paper mode.
    """
    from app.db.models.bots import BotPosition

    stop_price = round(fill_price * (1 - stop_pct / 100), 6)
    pos = db.get(BotPosition, position_id)
    if pos is None:
        logger.warning("[stop_mgmt] place_initial_stop: position %d not found", position_id)
        return None

    if pos.stop_price_usd and pos.stop_price_usd > 0:
        return f"paper_stop_{position_id}"  # already set

    pos.stop_price_usd = stop_price
    try:
        db.commit()
        logger.info(
            "[stop_mgmt] placed stop pos=%d stop=%.6f entry=%.6f pct=%.1f%%",
            position_id, stop_price, fill_price, stop_pct,
        )
    except Exception as exc:
        logger.error("[stop_mgmt] place_initial_stop commit failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None

    return f"paper_stop_{position_id}"


def ratchet_trailing_stop(
    db,
    position_id: int,
    current_price: float,
    entry_price: float,
    min_pct: float,
    ratchet_pct: float,
) -> str:
    """Ratchet the trailing stop up when the position is sufficiently profitable.

    - Triggers when current_price >= entry * (1 + ratchet_pct/100)
    - New stop = current_price * (1 - min_pct/100), but never lower than existing stop
    - Returns: "ratcheted" | "already_set" | "not_triggered" | "error"
    """
    from app.db.models.bots import BotPosition

    if current_price <= 0 or entry_price <= 0:
        return "error"

    gain_pct = (current_price - entry_price) / entry_price * 100
    if gain_pct < ratchet_pct:
        return "not_triggered"

    new_stop = round(current_price * (1 - min_pct / 100), 6)

    pos = db.get(BotPosition, position_id)
    if pos is None:
        return "error"

    existing_stop = pos.stop_price_usd or 0.0
    if new_stop <= existing_stop:
        return "already_set"

    pos.stop_price_usd = new_stop
    pos.trailing_stop_activated = True
    pos.trailing_stop_price_usd = new_stop
    try:
        db.commit()
        logger.info(
            "[stop_mgmt] ratcheted pos=%d gain=%.1f%% new_stop=%.6f prev=%.6f",
            position_id, gain_pct, new_stop, existing_stop,
        )
    except Exception as exc:
        logger.error("[stop_mgmt] ratchet commit failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return "error"

    return "ratcheted"


def ensure_stop_exists(
    db,
    position_id: int,
    entry_price: float,
    stop_pct: float,
) -> None:
    """Guarantee every open position has a stop set.

    Silent no-op if stop_price_usd is already positive.
    Logs a warning if it has to set one — indicates a gap in entry flow.
    """
    from app.db.models.bots import BotPosition

    pos = db.get(BotPosition, position_id)
    if pos is None:
        return

    if pos.stop_price_usd and pos.stop_price_usd > 0:
        return

    stop_price = round(entry_price * (1 - stop_pct / 100), 6)
    pos.stop_price_usd = stop_price
    try:
        db.commit()
        logger.warning(
            "[stop_mgmt] ensure_stop: pos=%d had no stop — set to %.6f (entry=%.6f pct=%.1f%%)",
            position_id, stop_price, entry_price, stop_pct,
        )
    except Exception as exc:
        logger.error("[stop_mgmt] ensure_stop commit failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
