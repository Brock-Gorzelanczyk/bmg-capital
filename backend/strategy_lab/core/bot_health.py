"""
Bot health monitoring — heartbeats, live Sharpe tracking, backtest divergence,
and circuit-breaker auto-pause logic.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Divergence threshold above which the bot is auto-paused
_DIVERGENCE_PAUSE_THRESHOLD = 0.5

# PART 7: in-process rate limiter for heartbeat writes during order placement.
# Prevents DB write storm — at most 1 update per minute per allocation_id.
# Survives process lifetime, resets on restart (acceptable; logs are source of truth).
_LAST_ORDER_HEARTBEAT_AT: dict[int, datetime] = {}
_ORDER_HEARTBEAT_MIN_INTERVAL_SEC = 60


def record_order_placement_heartbeat(allocation_id: int, db: Session) -> bool:
    """Best-effort heartbeat write triggered by a successful order placement.

    Differs from scheduled scan heartbeat (`record_heartbeat`) by being
    RATE-LIMITED to once per minute per allocation. Active-trading bots
    update their heartbeat from the execution path so the diagnostics
    "stale" view doesn't false-positive when scans are rare.

    Returns True if a write happened, False if rate-limited or failed.
    """
    now = datetime.now(timezone.utc)
    last = _LAST_ORDER_HEARTBEAT_AT.get(allocation_id)
    if last is not None:
        if (now - last).total_seconds() < _ORDER_HEARTBEAT_MIN_INTERVAL_SEC:
            return False
    try:
        record_heartbeat(allocation_id, db)
        _LAST_ORDER_HEARTBEAT_AT[allocation_id] = now
        return True
    except Exception as exc:
        logger.warning(
            "record_order_placement_heartbeat failed for alloc=%d: %s",
            allocation_id, exc,
        )
        return False


def record_heartbeat(allocation_id: int, db: Session) -> None:
    """
    Upsert a BotHealth row with heartbeat_ok=True for the current UTC date.
    Updates the existing row if one already exists for today.
    """
    from app.db.models.bots import BotHealth

    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    existing = (
        db.query(BotHealth)
        .filter(
            BotHealth.allocation_id == allocation_id,
            BotHealth.date >= today,
        )
        .order_by(BotHealth.date.desc())
        .first()
    )

    if existing:
        existing.heartbeat_ok = True
        existing.date = now
    else:
        row = BotHealth(
            allocation_id=allocation_id,
            date=now,
            heartbeat_ok=True,
            paused_by_health=False,
        )
        db.add(row)

    db.commit()
    logger.debug("Heartbeat recorded for allocation_id=%d", allocation_id)


def check_heartbeat(
    allocation_id: int, db: Session, tolerance_seconds: int = 120
) -> bool:
    """
    Returns True if a recent heartbeat exists within `tolerance_seconds`.
    Returns False (unhealthy) if no recent heartbeat found.
    """
    from app.db.models.bots import BotHealth

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=tolerance_seconds)
    row = (
        db.query(BotHealth)
        .filter(
            BotHealth.allocation_id == allocation_id,
            BotHealth.heartbeat_ok.is_(True),
            BotHealth.date >= cutoff,
        )
        .order_by(BotHealth.date.desc())
        .first()
    )
    return row is not None


def compute_live_sharpe(
    allocation_id: int, db: Session, days: int = 30
) -> Optional[float]:
    """
    Compute rolling Sharpe ratio from BotDailyPnL over the last `days` calendar days.
    Returns None if insufficient data (< 5 rows).
    Uses $10k notional per allocation (matches risk_overlay default).
    """
    from app.db.models.bots import BotDailyPnL

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    rows = (
        db.query(BotDailyPnL)
        .filter(
            BotDailyPnL.allocation_id == allocation_id,
            BotDailyPnL.date >= cutoff,
        )
        .order_by(BotDailyPnL.date.asc())
        .all()
    )

    if len(rows) < 5:
        return None

    capital_cents = 1_000_000  # $10k

    daily_returns: list[float] = []
    for row in rows:
        net_cents = row.realized_cents + row.unrealized_cents - row.fees_cents
        daily_returns.append(net_cents / capital_cents)

    n = len(daily_returns)
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / max(n - 1, 1)
    std = math.sqrt(variance)

    if std == 0:
        return None

    # Annualize: 252 trading days
    sharpe = (mean / std) * math.sqrt(252)
    return round(sharpe, 3)


def check_divergence(
    allocation_id: int, backtest_sharpe: float, db: Session
) -> Optional[float]:
    """
    Compares live 30d Sharpe to backtest_sharpe.
    Returns divergence_sigma = (backtest_sharpe - live_sharpe) / std_estimate.
    Auto-pauses the allocation if divergence_sigma > _DIVERGENCE_PAUSE_THRESHOLD.
    Returns None if insufficient live data.
    """
    from app.db.models.bots import BotAllocation

    live_sharpe = compute_live_sharpe(allocation_id, db, days=30)
    if live_sharpe is None:
        return None

    # Simple sigma estimate: use backtest_sharpe as scale reference
    # In production this would use Monte Carlo bootstrapped sigma
    scale = max(abs(backtest_sharpe) * 0.3, 0.1)
    divergence_sigma = (backtest_sharpe - live_sharpe) / scale

    if divergence_sigma > _DIVERGENCE_PAUSE_THRESHOLD:
        # Auto-pause the allocation
        alloc = db.query(BotAllocation).filter(BotAllocation.id == allocation_id).first()
        if alloc and alloc.enabled:
            alloc.enabled = False
            alloc.paused_reason = (
                f"auto_pause:divergence_sigma={divergence_sigma:.2f}>"
                f"{_DIVERGENCE_PAUSE_THRESHOLD}"
            )
            db.commit()
            logger.warning(
                "Allocation %d auto-paused: divergence_sigma=%.2f (live=%.3f backtest=%.3f)",
                allocation_id,
                divergence_sigma,
                live_sharpe,
                backtest_sharpe,
            )

    return round(divergence_sigma, 3)


def check_dead_mans_switch(db: Session, lookback_hours: int = 4) -> bool:
    """
    Alert if 0 signals across ALL active bots during US market hours.
    Only active Mon-Fri 9:30am-4:00pm ET.
    Returns True if switch tripped (silence detected), False if all clear.
    """
    import pytz
    from datetime import datetime, timezone, timedelta
    from app.db.models.bots import BotSignal, AnomalyEvent

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)

    # Only check on weekdays
    if now_et.weekday() >= 5:
        return False

    # Only check during market hours (9:30 AM – 4:00 PM ET)
    in_session = (now_et.hour == 9 and now_et.minute >= 30) or (
        10 <= now_et.hour < 16
    )
    if not in_session:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        recent_signals = (
            db.query(BotSignal).filter(BotSignal.ts > cutoff).count()
        )
    except Exception as exc:
        logger.error("[dead_mans_switch] DB query failed: %s", exc)
        return False

    if recent_signals == 0:
        logger.warning(
            "[dead_mans_switch] TRIPPED: 0 signals in last %dh during market hours",
            lookback_hours,
        )
        # Log as AnomalyEvent — use first active allocation_id as the anchor
        # (system-wide event; allocation_id FK is non-nullable in schema)
        try:
            from app.db.models.bots import BotAllocation as _BotAlloc

            first_alloc = (
                db.query(_BotAlloc)
                .filter(_BotAlloc.enabled.is_(True))
                .first()
            )
            if first_alloc:
                event = AnomalyEvent(
                    allocation_id=first_alloc.id,
                    anomaly_type="dead_mans_switch",
                    snapshot={
                        "lookback_hours": lookback_hours,
                        "market_time_et": now_et.isoformat(),
                        "system_wide": True,
                    },
                )
                db.add(event)
                db.commit()
        except Exception as exc:
            logger.debug("[dead_mans_switch] Could not log AnomalyEvent: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # Notify all active users
        try:
            from app.db.models.bots import BotAllocation
            from app.db.models.users import User
            from strategy_lab.notifier import notify

            user_ids = (
                db.query(BotAllocation.user_id)
                .filter(BotAllocation.enabled.is_(True))
                .distinct()
                .all()
            )
            for (uid,) in user_ids:
                user = db.query(User).filter(User.id == uid).first()
                if user:
                    notify(
                        user_id=uid,
                        user_email=user.email,
                        notification_type="health_alert",
                        subject=f"Dead-man's switch tripped — 0 signals in {lookback_hours}h",
                        body=(
                            f"No trading signals have been generated across any active bot "
                            f"in the last {lookback_hours} hours during market hours. "
                            f"Check the Command Center immediately."
                        ),
                        deep_link=None,
                    )
        except Exception as exc:
            logger.error("[dead_mans_switch] Notification failed: %s", exc)

        return True

    return False


def run_health_check(
    allocation_id: int,
    db: Session,
    backtest_sharpe: float = 1.5,
) -> dict:
    """
    Run all health checks. Persists a BotHealth row with results.
    Returns a health summary dict.
    """
    from app.db.models.bots import BotHealth

    now = datetime.now(timezone.utc)
    heartbeat_ok = check_heartbeat(allocation_id, db, tolerance_seconds=120)
    live_sharpe = compute_live_sharpe(allocation_id, db, days=30)
    divergence_sigma = check_divergence(allocation_id, backtest_sharpe, db)

    paused_by_health = False
    notes_parts: list[str] = []

    if not heartbeat_ok:
        paused_by_health = True
        notes_parts.append("heartbeat_missing")

    if divergence_sigma is not None and divergence_sigma > _DIVERGENCE_PAUSE_THRESHOLD:
        paused_by_health = True
        notes_parts.append(f"divergence_sigma={divergence_sigma:.2f}")

    notes = "; ".join(notes_parts) if notes_parts else None

    # Derive a coarse health_status (GREEN|YELLOW|RED) consumed by
    # fleet_sentinel red-transition checks and the queen daily brief.
    if not heartbeat_ok or paused_by_health:
        health_status = "RED"
    elif divergence_sigma is not None and divergence_sigma > (_DIVERGENCE_PAUSE_THRESHOLD * 0.6):
        health_status = "YELLOW"
    else:
        health_status = "GREEN"

    # Upsert health record for today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    existing = (
        db.query(BotHealth)
        .filter(
            BotHealth.allocation_id == allocation_id,
            BotHealth.date >= today_start,
        )
        .order_by(BotHealth.date.desc())
        .first()
    )

    if existing:
        existing.date = now
        existing.live_sharpe_30d = live_sharpe
        existing.backtest_sharpe = backtest_sharpe
        existing.divergence_sigma = divergence_sigma
        existing.paused_by_health = paused_by_health
        existing.heartbeat_ok = heartbeat_ok
        existing.notes = notes
        existing.health_status = health_status
    else:
        row = BotHealth(
            allocation_id=allocation_id,
            date=now,
            live_sharpe_30d=live_sharpe,
            backtest_sharpe=backtest_sharpe,
            divergence_sigma=divergence_sigma,
            paused_by_health=paused_by_health,
            heartbeat_ok=heartbeat_ok,
            notes=notes,
            health_status=health_status,
        )
        db.add(row)

    db.commit()

    result = {
        "allocation_id": allocation_id,
        "checked_at": now.isoformat(),
        "heartbeat_ok": heartbeat_ok,
        "live_sharpe_30d": live_sharpe,
        "backtest_sharpe": backtest_sharpe,
        "divergence_sigma": divergence_sigma,
        "paused_by_health": paused_by_health,
        "notes": notes,
    }
    logger.info("Health check allocation=%d: %s", allocation_id, result)

    # Fire health-alert notification when bot is auto-paused
    if paused_by_health and notes:
        try:
            from app.db.models.bots import BotAllocation, BotProfile
            from app.db.models.users import User
            from strategy_lab.notifier import notify

            alloc = db.query(BotAllocation).filter(BotAllocation.id == allocation_id).first()
            if alloc:
                user = db.query(User).filter(User.id == alloc.user_id).first()
                profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
                bot_label = profile.name if profile else f"allocation_{allocation_id}"
                if user:
                    notify(
                        user_id=user.id,
                        user_email=user.email,
                        notification_type="health_alert",
                        subject=f"Bot health alert — {bot_label} auto-paused",
                        body=(
                            f"Bot <strong>{bot_label}</strong> has been auto-paused due to "
                            f"health check failure: {notes}. "
                            f"Review the Command Center and resume when ready."
                        ),
                        bot_name=bot_label,
                    )
        except Exception as exc:
            logger.error(
                "[bot_health] Failed to send health alert notification for allocation %d: %s",
                allocation_id,
                exc,
            )

    return result
