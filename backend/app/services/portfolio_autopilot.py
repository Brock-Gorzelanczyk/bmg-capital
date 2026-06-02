from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.services.autonomous_logger import log_action

logger = logging.getLogger(__name__)


async def scan_portfolio_drift(user_id: int, db: Session) -> None:
    """
    Check if any paper position has drifted >5% from target allocation.
    If so, log a signal_fired action with rationale.
    Informational only — no actual trade executed (paper simulation).
    """
    try:
        from app.db.models.paper import PaperAccount, PaperPosition

        account = db.query(PaperAccount).filter_by(user_id=user_id).first()
        if not account:
            return

        positions = db.query(PaperPosition).filter_by(user_id=user_id).all()
        if not positions:
            return

        # Compute total portfolio value (cash + market value of positions)
        total_value = account.cash
        position_values: dict[str, float] = {}
        for pos in positions:
            price = float(pos.prev_close or pos.avg_cost or 0)
            mv = price * float(pos.qty or 0)
            position_values[pos.symbol] = mv
            total_value += mv

        if total_value <= 0:
            return

        # Equal-weight target per position
        target_weight = 1.0 / len(positions)

        for pos in positions:
            try:
                actual_weight = position_values[pos.symbol] / total_value
                drift = actual_weight - target_weight
                drift_pct = drift * 100.0

                if abs(drift_pct) > 5.0:
                    direction = "above" if drift_pct > 0 else "below"
                    log_action(
                        user_id=user_id,
                        lab="portfolio",
                        action_type="rebalance_drift",
                        asset=pos.symbol,
                        rationale=(
                            f"{pos.symbol} has drifted {abs(drift_pct):.1f}% {direction} target allocation. "
                            f"Rebalance signal triggered."
                        ),
                        result="success",
                    )
            except Exception as e:
                logger.warning(f"scan_portfolio_drift: skipping {pos.symbol} for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"scan_portfolio_drift failed for user {user_id}: {e}", exc_info=True)


async def scan_tax_loss_opportunities(user_id: int, db: Session) -> None:
    """
    Look for paper positions with unrealized losses > 5%.
    Log tax_loss_harvest action with rationale.
    Wash-sale guard: skip if the same symbol was bought in the last 30 days.
    """
    try:
        from app.db.models.paper import PaperPosition, PaperTransaction

        positions = db.query(PaperPosition).filter_by(user_id=user_id).all()
        if not positions:
            return

        wash_sale_cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        for pos in positions:
            try:
                cost_basis = float(pos.avg_cost or 0)
                if cost_basis <= 0:
                    continue

                current_price = float(pos.prev_close or cost_basis)
                loss_pct = (current_price - cost_basis) / cost_basis * 100.0

                if loss_pct >= -5.0:
                    # Not a significant loss — skip
                    continue

                # Wash-sale guard: check for a buy of this symbol in last 30 days
                recent_buy = (
                    db.query(PaperTransaction)
                    .filter(
                        PaperTransaction.user_id == user_id,
                        PaperTransaction.symbol == pos.symbol,
                        PaperTransaction.side == "buy",
                        PaperTransaction.created_at >= wash_sale_cutoff,
                    )
                    .first()
                )
                if recent_buy:
                    logger.debug(
                        f"scan_tax_loss_opportunities: {pos.symbol} skipped — wash-sale conflict for user {user_id}"
                    )
                    continue

                log_action(
                    user_id=user_id,
                    lab="tax",
                    action_type="tax_loss_harvest",
                    asset=pos.symbol,
                    rationale=(
                        f"{pos.symbol} shows {abs(loss_pct):.1f}% unrealized loss. "
                        f"TLH opportunity identified; no wash-sale conflict."
                    ),
                    result="success",
                )
            except Exception as e:
                logger.warning(f"scan_tax_loss_opportunities: skipping {pos.symbol} for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"scan_tax_loss_opportunities failed for user {user_id}: {e}", exc_info=True)


async def check_concentration_caps(user_id: int, db: Session) -> None:
    """
    Flag any position exceeding 15% of total portfolio value.
    Log concentration_alert action.
    """
    try:
        from app.db.models.paper import PaperAccount, PaperPosition

        account = db.query(PaperAccount).filter_by(user_id=user_id).first()
        if not account:
            return

        positions = db.query(PaperPosition).filter_by(user_id=user_id).all()
        if not positions:
            return

        total_value = account.cash
        position_values: dict[str, float] = {}
        for pos in positions:
            price = float(pos.prev_close or pos.avg_cost or 0)
            mv = price * float(pos.qty or 0)
            position_values[pos.symbol] = mv
            total_value += mv

        if total_value <= 0:
            return

        for pos in positions:
            try:
                weight_pct = position_values[pos.symbol] / total_value * 100.0
                if weight_pct > 15.0:
                    log_action(
                        user_id=user_id,
                        lab="portfolio",
                        action_type="concentration_alert",
                        asset=pos.symbol,
                        rationale=(
                            f"{pos.symbol} represents {weight_pct:.1f}% of portfolio, "
                            f"exceeding the 15% concentration cap."
                        ),
                        result="success",
                    )
            except Exception as e:
                logger.warning(f"check_concentration_caps: skipping {pos.symbol} for user {user_id}: {e}")

    except Exception as e:
        logger.error(f"check_concentration_caps failed for user {user_id}: {e}", exc_info=True)
