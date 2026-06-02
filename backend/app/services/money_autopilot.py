from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.services.autopilot_logger import log_autopilot_action

logger = logging.getLogger(__name__)


def _iso_week(dt: datetime) -> str:
    """Return 'YYYY-Www' string for the given datetime."""
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


async def simulate_round_up(user_id: int, db: Session) -> None:
    """
    Weekly: simulate rounding up 'purchases' to nearest $1, batch investing the total.
    Uses a deterministic random seed (user_id + ISO week number) to generate $2–$15.
    Idempotent: one log per calendar week.
    action_type="round_up_invested", category="money"
    """
    try:
        from app.db.models.autopilot import AutopilotAction

        now = datetime.now(timezone.utc)
        week_str = _iso_week(now)

        # Idempotency: one entry per week
        # We store the week in params; check by scanning this week's actions
        week_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - __import__("datetime").timedelta(days=now.weekday())

        existing = (
            db.query(AutopilotAction)
            .filter(
                AutopilotAction.user_id == user_id,
                AutopilotAction.action_type == "round_up_invested",
                AutopilotAction.created_at >= week_start,
            )
            .first()
        )
        if existing:
            return

        # Deterministic amount: seed with user_id + week number so it's stable
        rng = random.Random(hash((user_id, week_str)))
        # $2.00–$15.00 in cents, then round to 2 dp
        amount = round(rng.uniform(2.0, 15.0), 2)

        log_autopilot_action(
            user_id=user_id,
            category="money",
            action_type="round_up_invested",
            params={"week": week_str, "amount": amount},
            ai_rationale=(
                f"Weekly round-ups of ${amount:.2f} invested into paper portfolio diversification."
            ),
            outcome_value=amount,
        )
    except Exception:
        logger.exception("simulate_round_up failed user_id=%s", user_id)


async def simulate_cash_sweep(user_id: int, db: Session) -> None:
    """
    Check paper account cash balance. If > $5,000, log a cash_sweep action.
    action_type="cash_sweep", category="money"
    outcome_value: excess amount above $5,000
    """
    try:
        from app.db.models.paper import PaperAccount

        account = db.query(PaperAccount).filter_by(user_id=user_id).first()
        if account is None:
            return

        cash = float(getattr(account, "cash", 0.0) or 0.0)
        threshold = 5_000.0
        if cash <= threshold:
            return

        excess = round(cash - threshold, 2)

        log_autopilot_action(
            user_id=user_id,
            category="money",
            action_type="cash_sweep",
            params={"cash_balance": cash, "threshold": threshold, "excess": excess},
            ai_rationale=(
                f"Cash balance of ${cash:,.2f} exceeds $5,000 threshold. "
                f"Excess ${excess:,.2f} swept to HYSA simulation."
            ),
            outcome_value=excess,
        )
    except Exception:
        logger.exception("simulate_cash_sweep failed user_id=%s", user_id)


async def analyze_subscription_spend(user_id: int, db: Session) -> None:
    """
    Weekly: simulate subscription tracking using a fixed list of common services.
    Picks 2–3 subscriptions deterministically by (user_id + ISO week).
    Idempotent: one log per calendar week.
    action_type="subscription_tracked", category="money"
    outcome_value: total monthly cost of tracked subscriptions
    """
    try:
        from app.db.models.autopilot import AutopilotAction

        now = datetime.now(timezone.utc)
        week_str = _iso_week(now)

        week_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - __import__("datetime").timedelta(days=now.weekday())

        existing = (
            db.query(AutopilotAction)
            .filter(
                AutopilotAction.user_id == user_id,
                AutopilotAction.action_type == "subscription_tracked",
                AutopilotAction.created_at >= week_start,
            )
            .first()
        )
        if existing:
            return

        all_subs = [
            ("Netflix", 15.99),
            ("Spotify", 9.99),
            ("Disney+", 7.99),
            ("Hulu", 7.99),
            ("Apple TV+", 9.99),
        ]

        # Deterministic selection: seed with user_id + week
        rng = random.Random(hash((user_id, week_str)))
        count = rng.randint(2, 3)
        selected = rng.sample(all_subs, count)

        total_cost = round(sum(cost for _, cost in selected), 2)
        names = ", ".join(name for name, _ in selected)

        log_autopilot_action(
            user_id=user_id,
            category="money",
            action_type="subscription_tracked",
            params={
                "week": week_str,
                "subscriptions": [{"name": n, "cost": c} for n, c in selected],
                "total_monthly": total_cost,
            },
            ai_rationale=(
                f"Tracked ${total_cost:.2f}/mo in streaming subscriptions ({names}). "
                "AI bill negotiation available on Premium plan."
            ),
            outcome_value=total_cost,
        )
    except Exception:
        logger.exception("analyze_subscription_spend failed user_id=%s", user_id)
