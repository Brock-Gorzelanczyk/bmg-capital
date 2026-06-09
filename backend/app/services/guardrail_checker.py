from __future__ import annotations

from datetime import date, timedelta, datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.autonomous import AutonomousAction, AutonomousGuardrail
from app.db.models.paper import PaperAccount


def get_or_create_guardrail(user_id: int, db: Session) -> AutonomousGuardrail:
    g = db.query(AutonomousGuardrail).filter_by(user_id=user_id).first()
    if not g:
        g = AutonomousGuardrail(user_id=user_id)
        db.add(g)
        db.commit()
        db.refresh(g)
    return g


def check_guardrails(user_id: int, db: Session) -> tuple[bool, str]:
    """
    Returns (ok: bool, reason: str).
    ok=False means autonomous trading should be paused for this user.
    """
    guardrail = get_or_create_guardrail(user_id, db)

    # User manually paused
    if guardrail.autonomous_paused:
        return False, guardrail.paused_reason or "User paused"

    # Get paper account for portfolio value
    acct = db.query(PaperAccount).filter_by(user_id=user_id).first()
    if not acct:
        return True, ""

    portfolio_value = float(acct.balance) if hasattr(acct, "balance") and acct.balance else float(acct.cash or 0)
    if portfolio_value <= 0:
        return True, ""

    # Daily loss check: sum outcome_value for today's paper_sell/stop_hit/target_hit actions
    today = date.today()
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    daily_actions = db.query(AutonomousAction).filter(
        AutonomousAction.user_id == user_id,
        AutonomousAction.action_type.in_(["paper_sell", "stop_hit", "target_hit"]),
        AutonomousAction.created_at >= today_start,
    ).all()

    daily_pnl = sum(a.outcome_value or 0 for a in daily_actions)
    daily_loss_pct = abs(min(0, daily_pnl)) / portfolio_value * 100

    if daily_loss_pct >= guardrail.daily_loss_limit_pct:
        return False, f"Daily loss limit hit ({daily_loss_pct:.1f}% vs {guardrail.daily_loss_limit_pct}% limit)"

    # Weekly loss check
    week_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(days=today.weekday())
    weekly_actions = db.query(AutonomousAction).filter(
        AutonomousAction.user_id == user_id,
        AutonomousAction.action_type.in_(["paper_sell", "stop_hit", "target_hit"]),
        AutonomousAction.created_at >= week_start,
    ).all()
    weekly_pnl = sum(a.outcome_value or 0 for a in weekly_actions)
    weekly_loss_pct = abs(min(0, weekly_pnl)) / portfolio_value * 100
    if weekly_loss_pct >= guardrail.weekly_loss_limit_pct:
        return False, f"Weekly loss limit hit ({weekly_loss_pct:.1f}% vs {guardrail.weekly_loss_limit_pct}% limit)"

    # Max open positions is intentionally NOT checked here.
    # Each bot profile enforces its own position_cap from its YAML config.
    # A single user can run multiple bots, each with independent books —
    # summing cross-bot positions and comparing to a user-level cap
    # incorrectly blocks bots that haven't hit their own limits.
    # Per-bot cap: runner.py lines ~533-541, scan_and_execute.py execute gate.

    return True, ""
