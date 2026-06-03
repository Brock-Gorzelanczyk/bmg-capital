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
    return result
