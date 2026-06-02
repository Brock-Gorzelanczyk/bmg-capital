from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.services.autonomous_logger import log_action

logger = logging.getLogger(__name__)

LESSON_POOL = [
    "options_basics",
    "risk_management",
    "technical_analysis",
    "fundamental_analysis",
    "portfolio_theory",
    "behavioral_finance",
    "tax_efficiency",
    "crypto_defi",
    "macro_indicators",
    "earnings_analysis",
]


async def assign_daily_lesson(user_id: int, db: Session) -> None:
    """
    Assign one lesson concept to the user's feed each day, idempotent by date.
    Rotates deterministically through LESSON_POOL using today's ordinal.
    """
    try:
        today = date.today()
        lesson = LESSON_POOL[today.toordinal() % len(LESSON_POOL)]
        today_str = today.isoformat()

        # Idempotency: check if we already logged this lesson for today
        from app.db.models.autonomous import AutonomousAction

        already_logged = (
            db.query(AutonomousAction)
            .filter(
                AutonomousAction.user_id == user_id,
                AutonomousAction.action_type == "daily_lesson_assigned",
                AutonomousAction.asset == lesson,
                # created_at is a DateTime; compare by date prefix via string cast
            )
            .order_by(AutonomousAction.created_at.desc())
            .first()
        )

        if already_logged:
            # Check if the existing record is from today
            if already_logged.created_at and already_logged.created_at.date().isoformat() == today_str:
                logger.debug(f"assign_daily_lesson: already assigned '{lesson}' for user {user_id} today")
                return

        log_action(
            user_id=user_id,
            lab="learning",
            action_type="daily_lesson_assigned",
            asset=lesson,
            rationale=(
                f"Today's lesson: {lesson.replace('_', ' ').title()}. "
                f"Concept assigned to your learning feed for {today_str}."
            ),
            result="success",
            params={"lesson": lesson, "date": today_str},
        )

    except Exception as e:
        logger.error(f"assign_daily_lesson failed for user {user_id}: {e}", exc_info=True)


async def detect_trade_patterns(user_id: int, db: Session) -> None:
    """
    Check the last 10 closed paper trades for a loss streak (3+ consecutive losses).
    If detected, logs a pattern_detected action.
    """
    try:
        from app.db.models.paper import PaperTransaction

        # Closed/sell transactions represent realized outcomes; look at last 10 sells
        recent_sells = (
            db.query(PaperTransaction)
            .filter(
                PaperTransaction.user_id == user_id,
                PaperTransaction.side == "sell",
            )
            .order_by(PaperTransaction.created_at.desc())
            .limit(10)
            .all()
        )

        if len(recent_sells) < 3:
            return

        # Check for 3+ consecutive losses (realized_pnl < 0) from most recent
        consecutive_losses = 0
        for txn in recent_sells:
            try:
                pnl = float(txn.realized_pnl or 0)
                if pnl < 0:
                    consecutive_losses += 1
                else:
                    break  # streak broken
            except Exception:
                break

        if consecutive_losses >= 3:
            log_action(
                user_id=user_id,
                lab="journal",
                action_type="pattern_detected",
                rationale=(
                    f"{consecutive_losses} consecutive losses detected in paper trading. "
                    f"Recommend reviewing entry criteria."
                ),
                result="success",
                params={"consecutive_losses": consecutive_losses},
            )

    except Exception as e:
        logger.error(f"detect_trade_patterns failed for user {user_id}: {e}", exc_info=True)
