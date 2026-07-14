"""Option-close reconciliation with Alpaca.

Fixes the RIA-stats gap where BMG's options positions accumulate marks-only
P&L but never book realized P&L on close. Alpaca handles the close side
(expiry-worthless, assignment, or buy-to-close) but BMG's DB never learned
about the event → position stays "open" forever, sleeve P&L only shows via
the running unrealized mark.

Called on-demand via /api/admin/reconcile-option-closes and on a scheduled
cron (every 30 min during market hours).

For each open BMG option position:
  1. Check Alpaca for a still-open position on the same OCC symbol.
     If found — leave it alone.
  2. If missing at Alpaca — position was closed. Determine how:
     a. Check Alpaca orders for buy_to_close on this symbol after opening.
        If found and filled → exit_reason='manual' (or take_profit/stop
        based on realized P&L pct), exit_price = order fill price.
     b. Else if expiration_date < today → exit_reason='expiry',
        exit_price = 0 (worthless).
     c. Else → exit_reason='assignment' (settled by broker), exit_price = 0.

Realized P&L is computed by _close_position (position_monitor) using the
existing formula: short = avg_cost - fill_price × qty; long = reverse.
Expiry-worthless on short leg = full premium retained (avg_cost × qty).

The exit_reason enum is enforced downstream via _CANONICAL_EXIT_REASONS.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Canonical exit_reason values (RIA spec).
CANONICAL_EXIT_REASONS = {"take_profit", "stop", "expiry", "assignment", "roll", "manual"}

# Legacy → canonical mapping (used by _close_position callers whose reason
# strings pre-date the enum).
LEGACY_REASON_MAP = {
    "hold_max_hours_force_exit": "manual",
    "hold_max_hours": "manual",
    "drawdown_circuit_breaker": "stop",
    "stop_loss": "stop",
    "trailing_stop": "stop",
    "target_hit": "take_profit",
    "time_stop": "expiry",
    "reversed": "manual",
    "sync_backfill": "manual",
}


def canonicalize_exit_reason(reason: Optional[str]) -> str:
    """Return a valid enum value. Falls back to 'manual' if unknown."""
    if not reason:
        return "manual"
    r = reason.strip().lower()
    if r in CANONICAL_EXIT_REASONS:
        return r
    if r in LEGACY_REASON_MAP:
        return LEGACY_REASON_MAP[r]
    # Substring fallback so verbose legacy reasons still map
    if "stop" in r:
        return "stop"
    if "profit" in r or "target" in r:
        return "take_profit"
    if "expir" in r:
        return "expiry"
    if "assign" in r:
        return "assignment"
    if "roll" in r:
        return "roll"
    return "manual"


def _alpaca_headers() -> dict[str, str]:
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError("Alpaca creds not configured")
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def _alpaca_positions() -> dict[str, dict]:
    """Return {occ_symbol: position_row} for all Alpaca positions."""
    try:
        r = httpx.get(
            "https://paper-api.alpaca.markets/v2/positions",
            headers=_alpaca_headers(),
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:
        logger.warning("[option_close_sync] Alpaca positions fetch failed: %s", exc)
        return {}
    return {p["symbol"].upper(): p for p in (r.json() or [])}


def _alpaca_orders_for(symbol: str, after_iso: str) -> list[dict]:
    """Fetch Alpaca orders for a specific option symbol after a given time.
    Returns filled buy_to_close orders sorted by fill time."""
    params = {
        "status": "closed",
        "symbols": symbol,
        "after": after_iso,
        "limit": 50,
        "direction": "asc",
    }
    try:
        r = httpx.get(
            "https://paper-api.alpaca.markets/v2/orders",
            headers=_alpaca_headers(),
            params=params,
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:
        logger.warning(
            "[option_close_sync] Alpaca orders fetch failed for %s: %s", symbol, exc,
        )
        return []
    orders = r.json() or []
    # Filter to filled buy orders (buy-to-close for shorts) or sell orders (sell-to-close for longs)
    return [
        o for o in orders
        if o.get("status") == "filled"
        and o.get("filled_qty") and float(o["filled_qty"]) > 0
    ]


def reconcile_option_closes(db: Session, user_id: int = 1) -> dict[str, Any]:
    """Walk all open option positions for the user, close any that are gone
    at Alpaca. Returns per-position outcome list."""
    from app.db.models.bots import BotAllocation, BotPosition, BotProfile
    from strategy_lab.core.position_monitor import _close_position

    open_pos = (
        db.query(BotPosition, BotAllocation, BotProfile)
        .join(BotAllocation, BotAllocation.id == BotPosition.allocation_id)
        .join(BotProfile, BotProfile.id == BotAllocation.profile_id)
        .filter(BotAllocation.user_id == user_id)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .filter(BotPosition.option_type.isnot(None))
        .all()
    )

    if not open_pos:
        return {"open_option_positions": 0, "actions": []}

    try:
        broker_positions = _alpaca_positions()
    except Exception as exc:
        logger.warning("[option_close_sync] setup failed: %s", exc)
        return {"error": str(exc)[:200]}

    actions: list[dict] = []
    now = datetime.now(timezone.utc)
    today = now.date()

    for pos, alloc, prof in open_pos:
        occ = str(pos.symbol).upper()
        # Case 1: still open at broker → skip
        if occ in broker_positions:
            actions.append({"symbol": occ, "action": "still_open_at_broker",
                            "position_id": pos.id})
            continue

        # Case 2: gone at broker. Determine close type.
        exit_price_usd: float = 0.0
        reason = "manual"
        opened_iso = pos.opened_at.isoformat() if pos.opened_at else now.isoformat()
        try:
            orders = _alpaca_orders_for(occ, opened_iso)
        except Exception as exc:
            logger.warning("[option_close_sync] orders lookup failed for %s: %s", occ, exc)
            orders = []

        close_order = None
        want_side = "buy" if pos.side == "short" else "sell"
        for o in orders:
            if str(o.get("side", "")).lower() == want_side:
                close_order = o
                break

        if close_order is not None:
            try:
                exit_price_usd = float(
                    close_order.get("filled_avg_price")
                    or close_order.get("limit_price")
                    or 0
                )
            except (TypeError, ValueError):
                exit_price_usd = 0.0
            # Reason: was the close in profit or loss vs entry?
            entry_usd = float(pos.avg_cost_cents or 0) / 100.0
            if pos.side == "short":
                pnl_per_contract = entry_usd - exit_price_usd
            else:
                pnl_per_contract = exit_price_usd - entry_usd
            if pnl_per_contract > 0:
                reason = "take_profit"
            elif pnl_per_contract < 0:
                reason = "stop"
            else:
                reason = "manual"
        else:
            # No close order at broker. Was the option expired?
            try:
                exp = pos.expiration_date
                if isinstance(exp, str):
                    exp_date = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                elif isinstance(exp, date):
                    exp_date = exp
                else:
                    exp_date = None
            except Exception:
                exp_date = None
            if exp_date and exp_date <= today:
                reason = "expiry"
                exit_price_usd = 0.0
            else:
                # 2026-07-15 fix: was defaulting to "assignment" on every close
                # where the per-symbol Alpaca order search missed. That's wrong
                # for mleg exits filed under parent order IDs (JD/PYPL/BABA
                # spread exits on 2026-07-14 got mislabeled). Real assignments
                # require broker settlement evidence (shares appearing in stock
                # positions post-close). Without that evidence, "manual" is the
                # honest label — the position closed at broker via some order
                # we couldn't join back to this OCC symbol.
                reason = "manual"
                exit_price_usd = 0.0

        try:
            _close_position(db, pos, alloc, exit_price_usd, reason, now)
            actions.append({
                "symbol": occ,
                "action": "closed",
                "position_id": pos.id,
                "reason": reason,
                "exit_price_usd": round(exit_price_usd, 4),
                "bot": prof.name,
            })
        except Exception as exc:
            logger.error(
                "[option_close_sync] _close_position raised for %s: %s", occ, exc,
            )
            actions.append({
                "symbol": occ, "action": "close_failed", "error": str(exc)[:200],
            })

    return {
        "open_option_positions": len(open_pos),
        "broker_positions_seen": len(broker_positions),
        "actions": actions,
    }


def setup_option_close_sync_scheduler(scheduler) -> None:
    """Register a 30-min scheduled sync during market hours + a 1-min
    bootstrap so the first sync happens right after startup."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from datetime import timedelta
    except Exception as exc:
        logger.warning("[option_close_sync] apscheduler unavailable: %s", exc)
        return

    from app.db.session import SessionLocal

    def _job() -> None:
        db = SessionLocal()
        try:
            res = reconcile_option_closes(db, user_id=1)
            actions = res.get("actions", [])
            closed = sum(1 for a in actions if a.get("action") == "closed")
            if closed > 0:
                logger.warning(
                    "[option_close_sync] closed %d option positions this run", closed,
                )
        except Exception as exc:
            logger.error("[option_close_sync] job raised: %s", exc)
        finally:
            db.close()

    # Every 30 min Mon-Fri during regular US market hours + 15 min after close.
    scheduler.add_job(
        _job,
        CronTrigger(
            day_of_week="mon-fri", hour="9-16", minute="15,45",
            timezone="America/New_York",
        ),
        id="option_close_sync",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )
    # Bootstrap 1 minute after startup so the first sync clears any built-up
    # backlog immediately.
    scheduler.add_job(
        _job,
        DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(minutes=1)),
        id="option_close_sync_bootstrap",
        replace_existing=True,
    )
    logger.warning(
        "[option_close_sync] scheduler registered (Mon-Fri 9:15/9:45/.../16:15 + bootstrap)",
    )
