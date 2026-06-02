from __future__ import annotations

import logging
import random
from datetime import date

from sqlalchemy.orm import Session

from app.services.autonomous_logger import log_action

logger = logging.getLogger(__name__)

RELATED_MAP: dict[str, str] = {
    "NVDA": "ASML",
    "AAPL": "MSFT",
    "TSLA": "RIVN",
    "AMD": "INTC",
    "AMZN": "SHOP",
    "META": "SNAP",
    "GOOGL": "MSFT",
    "SPY": "QQQ",
}


async def curate_watchlist(user_id: int, db: Session) -> None:
    """
    Auto-add symbols from the user's open paper positions to their default watchlist.
    Skips symbols already present. Logs an action for each addition.
    """
    try:
        from app.db.models.watchlist import Watchlist, WatchlistItem
        from app.db.models.paper import PaperPosition

        # Get the user's default (first) watchlist
        watchlist = (
            db.query(Watchlist)
            .filter(Watchlist.user_id == user_id)
            .order_by(Watchlist.id)
            .first()
        )
        if not watchlist:
            logger.debug(f"curate_watchlist: no watchlist found for user {user_id}")
            return

        # Symbols already in the watchlist
        existing_items = db.query(WatchlistItem).filter_by(watchlist_id=watchlist.id).all()
        existing_symbols: set[str] = {item.symbol for item in existing_items}

        # Open paper positions
        positions = db.query(PaperPosition).filter_by(user_id=user_id).all()
        if not positions:
            return

        for pos in positions:
            try:
                if pos.symbol in existing_symbols:
                    continue

                new_item = WatchlistItem(
                    watchlist_id=watchlist.id,
                    symbol=pos.symbol,
                )
                db.add(new_item)
                db.commit()
                existing_symbols.add(pos.symbol)

                log_action(
                    user_id=user_id,
                    lab="research",
                    action_type="watchlist_curate",
                    asset=pos.symbol,
                    rationale=(
                        f"{pos.symbol} added to watchlist based on open paper position."
                    ),
                    result="success",
                )
            except Exception as e:
                db.rollback()
                logger.warning(f"curate_watchlist: skipping {pos.symbol} for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"curate_watchlist failed for user {user_id}: {e}", exc_info=True)


async def prep_earnings_brief(user_id: int, db: Session) -> None:
    """
    Check if any paper position has earnings in the next 24h.
    Simulated: uses a deterministic daily seed to pick one symbol from holdings as "has earnings".
    Logs an earnings_prep action with rationale.
    """
    try:
        from app.db.models.paper import PaperPosition

        positions = db.query(PaperPosition).filter_by(user_id=user_id).all()
        if not positions:
            return

        symbols = [pos.symbol for pos in positions]

        # Deterministic pick: same user gets the same symbol on the same day
        today_str = str(date.today())
        seed_value = hash(f"{user_id}_{today_str}") % (2 ** 32)
        rng = random.Random(seed_value)
        earnings_symbol = rng.choice(symbols)

        log_action(
            user_id=user_id,
            lab="research",
            action_type="earnings_prep",
            asset=earnings_symbol,
            rationale=(
                f"{earnings_symbol} reports earnings tomorrow. "
                f"Pre-earnings position review recommended."
            ),
            result="success",
        )

    except Exception as e:
        logger.error(f"prep_earnings_brief failed for user {user_id}: {e}", exc_info=True)


async def flag_related_assets(user_id: int, db: Session) -> None:
    """
    For the user's top 3 open positions, suggest a related asset from RELATED_MAP.
    Logs a related_asset_flag action for each match found.
    """
    try:
        from app.db.models.paper import PaperPosition

        positions = (
            db.query(PaperPosition)
            .filter_by(user_id=user_id)
            .order_by(PaperPosition.opened_at.desc())
            .limit(3)
            .all()
        )
        if not positions:
            return

        for pos in positions:
            try:
                related = RELATED_MAP.get(pos.symbol)
                if not related:
                    continue

                log_action(
                    user_id=user_id,
                    lab="research",
                    action_type="related_asset_flag",
                    asset=pos.symbol,
                    rationale=(
                        f"{related} identified as a related asset to your {pos.symbol} position. "
                        f"Consider researching {related} for diversification or pair-trade opportunities."
                    ),
                    result="success",
                    params={"related_asset": related},
                )
            except Exception as e:
                logger.warning(f"flag_related_assets: skipping {pos.symbol} for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"flag_related_assets failed for user {user_id}: {e}", exc_info=True)
