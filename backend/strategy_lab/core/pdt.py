"""Pattern Day Trader (PDT) enforcement.

US FINRA rule 4210: an account with < $25,000 equity may not execute more
than 3 day trades in any rolling 5-business-day window.

For paper accounts this is a soft guard — it won't actually block Alpaca
from filling the order, but we enforce it here so back-testing and live
trading behave identically.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PDT_THRESHOLD = 25_000  # $25,000 paper equity
MAX_DAY_TRADES = 3
WINDOW_DAYS = 7  # approximation for 5 business days


def count_day_trades(db: Session, allocation_id: int) -> int:
    """Count day trades in the rolling 5-business-day window (~7 calendar days).

    A "day trade" is counted as each sell-side BotTrade in the window.
    A more precise implementation would pair same-day buy+sell, but this
    approximation errs on the side of caution.
    """
    from app.db.models.bots import BotTrade

    five_days_ago = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    count = (
        db.query(BotTrade)
        .filter(
            BotTrade.allocation_id == allocation_id,
            BotTrade.ts >= five_days_ago,
            BotTrade.side == "sell",
            BotTrade.is_paper.is_(True),
        )
        .count()
    )
    return count


def can_day_trade(
    db: Session,
    allocation_id: int,
    capital_cents: int,
) -> tuple[bool, str]:
    """Return (allowed, reason).  Enforces PDT rule for sub-$25K paper accounts.

    Args:
        db: SQLAlchemy session.
        allocation_id: BotAllocation.id to check.
        capital_cents: Current account equity in cents.
    """
    equity = capital_cents / 100.0
    if equity >= PDT_THRESHOLD:
        return True, f"equity ${equity:,.0f} above PDT threshold ${PDT_THRESHOLD:,}"

    day_trades = count_day_trades(db, allocation_id)
    remaining = MAX_DAY_TRADES - day_trades

    if day_trades >= MAX_DAY_TRADES:
        reason = (
            f"PDT limit: {day_trades} day trades in {WINDOW_DAYS}-day window "
            f"(max {MAX_DAY_TRADES} for sub-${PDT_THRESHOLD:,} account)"
        )
        logger.warning("PDT blocked allocation %d: %s", allocation_id, reason)
        return False, reason

    return True, f"{remaining} day trade(s) remaining this window"
