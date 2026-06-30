"""SHIP 6 — hourly auto-pause for bots whose 7d stop-hit rate > 70%.

READ-ONLY against bot_trades and bot_positions. The only WRITE is to
BotAllocation.enabled = False + paused_reason = 'degraded_auto_pause:...'.
NEVER auto-resumes — Brock must manually re-enable via existing admin
endpoint POST /admin/bots/{bot_id}/enable (which clears paused_reason).

Re-enable loop awareness: if Brock re-enables a bot that is still above
70% stop rate, next hourly tick will see enabled=True again and auto-pause
it back. This is intentional — it serves as audible feedback that the
underlying issue (e.g. stop too tight for current vol regime) is unresolved.
The loop only breaks when either (a) Brock redesigns the strategy so the
stop rate drops below 70%, or (b) Brock accepts the risk and keeps overriding.

MIN_CLOSES_FOR_EVAL: 20 closes required before eval. Guards against pausing
a brand-new bot that has only traded a handful of times in a volatile day.

Reads bot_positions.exit_reason for stop-hit detection. The column 'exit_reason'
does NOT exist on bot_trades — only on bot_positions. The query joins
bot_trades (for side/close detection) to bot_positions (for exit_reason).
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

STOP_PCT_THRESHOLD: float = 70.0
LOOKBACK_DAYS: int = 7
MIN_CLOSES_FOR_EVAL: int = 20   # don't auto-pause off a 3-trade sample


def compute_stop_rate(
    db: Session,
    bot_id: str,
    days: int = LOOKBACK_DAYS,
) -> tuple[int, int, float]:
    """Return (total_closes, stops, stop_pct) over the lookback window.

    SQL pattern: join bot_trades to bot_positions via position_id.
    total_closes counts close-side trades (sell/close/cover).
    stops counts those closes where bot_positions.exit_reason = 'stop_loss'.

    READ-ONLY. Never writes to bot_trades or bot_positions.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        row = db.execute(
            text("""
                SELECT
                    SUM(CASE WHEN LOWER(t.side) IN ('sell','close','cover') THEN 1 ELSE 0 END) AS total_closes,
                    SUM(CASE WHEN LOWER(t.side) IN ('sell','close','cover')
                              AND pos.exit_reason = 'stop_loss' THEN 1 ELSE 0 END) AS stops
                FROM bot_trades t
                JOIN bot_allocations ba ON ba.id = t.allocation_id
                JOIN bot_profiles p ON p.id = ba.profile_id
                JOIN bot_positions pos ON pos.id = t.position_id
                WHERE p.name = :bot_id
                  AND t.ts >= :cutoff
            """),
            {"bot_id": bot_id, "cutoff": cutoff},
        ).fetchone()
    except Exception as exc:
        logger.warning(
            "[auto_pause_degraded] compute_stop_rate query failed for bot=%s: %s",
            bot_id, exc,
        )
        return (0, 0, 0.0)

    if row is None:
        return (0, 0, 0.0)

    total_closes = int(row[0] or 0)
    stops = int(row[1] or 0)
    stop_pct = round((stops / total_closes * 100.0), 1) if total_closes > 0 else 0.0
    return (total_closes, stops, stop_pct)


def auto_pause_if_degraded(
    db: Session,
    bot_id: str,
) -> dict:
    """Check stop rate; if > threshold AND closes >= min, pause every
    enabled BotAllocation for this bot.

    Returns: {bot_id, total_closes, stops, stop_pct, action,
              paused_allocation_ids, paused_reason, ts}
      action in {"paused", "below_threshold", "insufficient_data", "already_paused"}

    Sets BotAllocation.enabled = False AND
         BotAllocation.paused_reason =
           f"degraded_auto_pause:{stop_pct:.1f}%_over_{days}d"

    Posts Discord ops alert via send_ops_alert(severity='warn') on pause.
    Discord failure is caught and logged — DB write is the source of truth.
    """
    ts = datetime.now(timezone.utc).isoformat()

    # Import models lazily to avoid circular imports at module level
    try:
        from app.db.models.bots import BotAllocation, BotProfile
    except Exception as exc:
        logger.error("[auto_pause_degraded] cannot import models: %s", exc)
        return {"bot_id": bot_id, "action": "error", "ts": ts, "error": str(exc)}

    # Resolve profile_id
    try:
        bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
        if bp is None:
            return {
                "bot_id": bot_id,
                "action": "insufficient_data",
                "ts": ts,
                "total_closes": 0,
                "stops": 0,
                "stop_pct": 0.0,
                "paused_allocation_ids": [],
                "paused_reason": None,
                "note": "bot_profile not found in DB",
            }
    except Exception as exc:
        logger.warning("[auto_pause_degraded] profile lookup failed for %s: %s", bot_id, exc)
        return {"bot_id": bot_id, "action": "error", "ts": ts, "error": str(exc)}

    # Check if already paused — if every enabled allocation is already disabled, skip
    try:
        enabled_count = (
            db.query(BotAllocation)
            .filter(BotAllocation.profile_id == bp.id, BotAllocation.enabled == True)
            .count()
        )
    except Exception as exc:
        logger.warning("[auto_pause_degraded] enabled count query failed for %s: %s", bot_id, exc)
        enabled_count = 0

    if enabled_count == 0:
        return {
            "bot_id": bot_id,
            "action": "already_paused",
            "ts": ts,
            "total_closes": 0,
            "stops": 0,
            "stop_pct": 0.0,
            "paused_allocation_ids": [],
            "paused_reason": None,
        }

    total_closes, stops, stop_pct = compute_stop_rate(db, bot_id, days=LOOKBACK_DAYS)

    if total_closes < MIN_CLOSES_FOR_EVAL:
        return {
            "bot_id": bot_id,
            "action": "insufficient_data",
            "ts": ts,
            "total_closes": total_closes,
            "stops": stops,
            "stop_pct": stop_pct,
            "paused_allocation_ids": [],
            "paused_reason": None,
        }

    # Strict >: 70.0% does NOT trigger, 70.1% does
    if stop_pct <= STOP_PCT_THRESHOLD:
        return {
            "bot_id": bot_id,
            "action": "below_threshold",
            "ts": ts,
            "total_closes": total_closes,
            "stops": stops,
            "stop_pct": stop_pct,
            "paused_allocation_ids": [],
            "paused_reason": None,
        }

    paused_reason = f"degraded_auto_pause:{stop_pct:.1f}%_over_{LOOKBACK_DAYS}d"

    # Pause all ENABLED allocations for this bot (mirrors disable_bot pattern)
    paused_ids: list[int] = []
    try:
        allocs = (
            db.query(BotAllocation)
            .filter(BotAllocation.profile_id == bp.id, BotAllocation.enabled == True)
            .all()
        )
        for alloc in allocs:
            alloc.enabled = False
            alloc.paused_reason = paused_reason
            paused_ids.append(alloc.id)
        db.commit()
        logger.warning(
            "[auto_pause_degraded] PAUSED bot=%s stop_pct=%.1f total_closes=%d "
            "paused_reason=%s allocation_ids=%s",
            bot_id, stop_pct, total_closes, paused_reason, paused_ids,
        )
    except Exception as exc:
        logger.error(
            "[auto_pause_degraded] DB pause write failed for bot=%s: %s", bot_id, exc
        )
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "bot_id": bot_id,
            "action": "error",
            "ts": ts,
            "total_closes": total_closes,
            "stops": stops,
            "stop_pct": stop_pct,
            "paused_allocation_ids": [],
            "paused_reason": paused_reason,
            "error": str(exc),
        }

    # Discord ops alert — catch + log, do NOT raise
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[WARN] auto_pause_degraded",
            message=(
                f"bot={bot_id} auto-paused due to high stop-hit rate.\n"
                f"stop_pct={stop_pct:.1f}% over {LOOKBACK_DAYS}d "
                f"(threshold={STOP_PCT_THRESHOLD}%)\n"
                f"total_closes={total_closes} stops={stops}\n"
                f"Re-enable via POST /admin/bots/{bot_id}/enable"
            ),
            severity="warn",
            source="auto_pause_degraded",
        )
    except Exception as discord_exc:
        logger.warning(
            "[auto_pause_degraded] Discord alert failed for bot=%s: %s (non-fatal)",
            bot_id, discord_exc,
        )

    return {
        "bot_id": bot_id,
        "action": "paused",
        "ts": ts,
        "total_closes": total_closes,
        "stops": stops,
        "stop_pct": stop_pct,
        "paused_allocation_ids": paused_ids,
        "paused_reason": paused_reason,
    }


def run_auto_pause_degraded_job() -> dict:
    """Scheduler entry point — iterates every distinct bot_id in
    ASSET_CLASS_REGISTRY (so the universe is canonical, not derived
    from DB state which could be stale).

    Returns summary dict for the scheduler log:
      {ts, bots_checked, bots_paused, bots_below_threshold,
       bots_insufficient_data, per_bot: [...]}
    """
    ts = datetime.now(timezone.utc).isoformat()
    per_bot: list[dict] = []
    bots_paused = 0
    bots_below = 0
    bots_insufficient = 0

    try:
        from app.services.asset_class_registry import ASSET_CLASS_REGISTRY
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            for bot_id in ASSET_CLASS_REGISTRY:
                try:
                    result = auto_pause_if_degraded(db, bot_id)
                    per_bot.append(result)
                    action = result.get("action", "")
                    if action == "paused":
                        bots_paused += 1
                    elif action == "below_threshold":
                        bots_below += 1
                    elif action == "insufficient_data":
                        bots_insufficient += 1
                except Exception as exc:
                    logger.error(
                        "[auto_pause_degraded] per-bot error for %s: %s", bot_id, exc
                    )
                    per_bot.append({"bot_id": bot_id, "action": "error", "error": str(exc), "ts": ts})
        finally:
            db.close()

    except Exception as exc:
        logger.error("[auto_pause_degraded] job-level error: %s", exc)
        return {
            "ts": ts,
            "bots_checked": 0,
            "bots_paused": 0,
            "bots_below_threshold": 0,
            "bots_insufficient_data": 0,
            "per_bot": [],
            "error": str(exc),
        }

    summary = {
        "ts": ts,
        "bots_checked": len(per_bot),
        "bots_paused": bots_paused,
        "bots_below_threshold": bots_below,
        "bots_insufficient_data": bots_insufficient,
        "per_bot": per_bot,
    }
    logger.warning("[auto_pause_degraded] job complete: %s", summary)
    return summary
