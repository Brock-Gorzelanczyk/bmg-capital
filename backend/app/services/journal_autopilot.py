from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.services.autopilot_logger import log_autopilot_action

logger = logging.getLogger(__name__)


async def auto_prompt_trade_reflection(user_id: int, db: Session) -> None:
    """
    For any paper trade closed in the last 24h with no reflection logged,
    generate an AI post-mortem and log it.
    """
    try:
        from app.db.models.paper import PaperTransaction
        from app.db.models.autopilot import AutopilotAction
        from app.config import settings

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        sells = db.query(PaperTransaction).filter(
            PaperTransaction.user_id == user_id,
            PaperTransaction.created_at >= cutoff,
            PaperTransaction.side == "sell",
        ).all()

        for sell in sells[:3]:  # max 3 post-mortems per run
            symbol = getattr(sell, "symbol", "UNKNOWN")

            # Idempotency: check AutopilotAction (where log_autopilot_action writes)
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            existing = (
                db.query(AutopilotAction)
                .filter(
                    AutopilotAction.user_id == user_id,
                    AutopilotAction.action_type == "trade_reflection",
                    AutopilotAction.asset == symbol,
                    AutopilotAction.created_at >= today_start,
                )
                .first()
            )
            if existing:
                continue

            realized_pnl = getattr(sell, "realized_pnl", 0.0) or 0.0
            cost_basis = getattr(sell, "cost_basis", 0.0) or 0.0   # avg_cost at sell time
            fill_price = getattr(sell, "fill_price", 0.0) or 0.0   # exit price

            # SHIP 3 R6: deterministic template — no LLM
            direction = "profit" if realized_pnl > 0 else "loss"
            rationale = (
                f"{symbol} closed with ${realized_pnl:+.2f} {direction}. "
                f"Entry ${cost_basis:.2f} to exit ${fill_price:.2f} "
                f"({'Entry timing was effective.' if realized_pnl > 0 else 'Review entry criteria for future trades.'})"
            )

            log_autopilot_action(
                user_id=user_id,
                category="journal",
                action_type="trade_reflection",
                asset=symbol,
                params={"entry": cost_basis, "exit": fill_price, "pnl": realized_pnl},
                ai_rationale=rationale,
                outcome_value=realized_pnl,
            )
    except Exception:
        logger.exception(
            "journal auto_prompt_trade_reflection failed user_id=%s", user_id
        )


async def detect_loss_patterns(user_id: int, db: Session) -> None:
    """
    Check last 10 closed paper trades. If 3+ consecutive losses, log pattern_detected.
    Idempotent: skip if already logged today.
    """
    try:
        from app.db.models.paper import PaperTransaction
        from app.db.models.autopilot import AutopilotAction

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        existing = (
            db.query(AutopilotAction)
            .filter(
                AutopilotAction.user_id == user_id,
                AutopilotAction.action_type == "loss_pattern_detected",
                AutopilotAction.created_at >= today_start,
            )
            .first()
        )
        if existing:
            return

        sells = (
            db.query(PaperTransaction)
            .filter(
                PaperTransaction.user_id == user_id,
                PaperTransaction.side == "sell",
            )
            .order_by(PaperTransaction.created_at.desc())
            .limit(10)
            .all()
        )

        streak = 0
        for s in sells:
            pnl = getattr(s, "realized_pnl", 0.0) or 0.0
            if pnl < 0:
                streak += 1
            else:
                break

        if streak >= 3:
            log_autopilot_action(
                user_id=user_id,
                category="journal",
                action_type="loss_pattern_detected",
                params={"consecutive_losses": streak},
                ai_rationale=(
                    f"{streak} consecutive paper trading losses detected. "
                    "Review entry criteria and position sizing before next trade."
                ),
            )
    except Exception:
        logger.exception("detect_loss_patterns failed user_id=%s", user_id)


async def generate_quarterly_review(user_id: int, db: Session) -> None:
    """
    Generate a quarterly trading review on the first day of each quarter.
    Q1: Jan 1, Q2: Apr 1, Q3: Jul 1, Q4: Oct 1.
    Idempotent — checks AutopilotAction for existing entry this quarter.
    Summarizes closed trades from the past 90 days.
    """
    try:
        today = date.today()
        if today.month not in (1, 4, 7, 10) or today.day != 1:
            return

        from app.db.models.paper import PaperTransaction
        from app.db.models.autopilot import AutopilotAction
        from app.config import settings

        quarter_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        existing = (
            db.query(AutopilotAction)
            .filter(
                AutopilotAction.user_id == user_id,
                AutopilotAction.action_type == "quarterly_review",
                AutopilotAction.created_at >= quarter_start,
            )
            .first()
        )
        if existing:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        sell_rows = (
            db.query(PaperTransaction)
            .filter(
                PaperTransaction.user_id == user_id,
                PaperTransaction.created_at >= cutoff,
                PaperTransaction.side == "sell",
            )
            .all()
        )

        total_pnl = sum(
            (getattr(s, "realized_pnl", 0.0) or 0.0) for s in sell_rows
        )
        wins = sum(
            1 for s in sell_rows if (getattr(s, "realized_pnl", 0.0) or 0.0) > 0
        )
        total = len(sell_rows)
        win_rate = (wins / total * 100) if total > 0 else 0.0

        # SHIP 3 R6: deterministic template — no LLM
        rationale = (
            f"Quarterly review: {total} paper trades completed with "
            f"{win_rate:.0f}% win rate and ${total_pnl:+.2f} total P&L. "
            f"{'Strong performance — maintain current strategy.' if total_pnl > 0 else 'Review risk management and entry criteria for next quarter.'}"
        )

        log_autopilot_action(
            user_id=user_id,
            category="journal",
            action_type="quarterly_review",
            params={
                "trades": total,
                "wins": wins,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
            },
            ai_rationale=rationale,
            outcome_value=total_pnl,
        )
    except Exception:
        logger.exception("generate_quarterly_review failed user_id=%s", user_id)
