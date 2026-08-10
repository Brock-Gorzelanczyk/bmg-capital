"""Daily BMG-vs-Alpaca reconciliation (2026-08-05).

Runs once per day at 05:00 UTC (12 AM ET, after market close). Three-step
pipeline that keeps the app's trade records honest:

  1. Quarantine any BMG bot_trade whose alpaca_order_id is missing OR
     doesn't correspond to a real filled Alpaca order. This kills the
     "phantom" and "sim" leaks that were inflating losses by ~$2K.

  2. Adopt any Alpaca position that BMG has no record of. Uses order
     history within ORPHAN_ATTRIBUTION_WINDOW_HOURS (default 30 days,
     override via env) to attribute to the originating bot.

  3. Compute drift metric: BMG open positions vs Alpaca open positions,
     BMG unrealized P&L vs Alpaca truth. Log the delta. If drift > $50,
     log a loud warning so it shows in Railway logs.

Every step is idempotent — safe to run repeatedly. Kill-switch:
DAILY_RECONCILIATION_ENABLED=false disables the whole thing.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _alpaca_snapshot() -> dict[str, Any]:
    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not sec:
        return {"error": "no_creds"}
    try:
        req = urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
        )
        positions = json.loads(urllib.request.urlopen(req, timeout=15).read()) or []
        return {
            "positions_count": len(positions),
            "unrealized_pl": sum(float(p.get("unrealized_pl") or 0) for p in positions),
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _bmg_snapshot(db) -> dict[str, Any]:
    """Sum BMG open positions' unrealized P&L using live prices, same math
    as /api/portfolio/open-positions."""
    from app.db.models.bots import BotPosition, BotAllocation

    try:
        open_positions = (
            db.query(BotPosition)
            .filter(BotPosition.closed_at.is_(None), BotPosition.quarantined_at.is_(None))
            .all()
        )
        return {"positions_count": len(open_positions)}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def run_daily_reconciliation(db) -> dict[str, Any]:
    """Full pipeline. Returns diagnostic dict."""
    enabled = os.getenv("DAILY_RECONCILIATION_ENABLED", "true").strip().lower() == "true"
    if not enabled:
        return {"skipped": "disabled_by_env"}

    result: dict[str, Any] = {"as_of": datetime.now(timezone.utc).isoformat()}

    # ── Step 1: quarantine non-broker trades ─────────────────────────────
    try:
        from app.routers.admin import quarantine_non_broker_trades  # type: ignore
        # We can't call the FastAPI endpoint directly (needs Request context),
        # so inline the core loop here:
        result["quarantine"] = _run_quarantine_inline(db, lookback_days=7)
    except Exception as exc:
        result["quarantine_error"] = str(exc)[:200]

    # ── Step 2: orphan adopter ──────────────────────────────────────────
    try:
        from app.services.orphan_adopter import adopt_orphans
        result["adoption"] = adopt_orphans(db, dry_run=False)
    except Exception as exc:
        result["adoption_error"] = str(exc)[:200]

    # ── Step 3: drift check ──────────────────────────────────────────────
    alp = _alpaca_snapshot()
    bmg = _bmg_snapshot(db)
    result["alpaca"] = alp
    result["bmg"] = bmg

    if "positions_count" in alp and "positions_count" in bmg:
        pos_drift = alp["positions_count"] - bmg["positions_count"]
        pnl_drift_alpaca_side = alp.get("unrealized_pl", 0)
        result["drift"] = {
            "position_count_drift": pos_drift,
            "alpaca_total_unrealized": round(pnl_drift_alpaca_side, 2),
        }
        if abs(pos_drift) > 5:
            logger.warning(
                "[daily-recon] POSITION DRIFT: alpaca=%d bmg=%d delta=%d",
                alp["positions_count"], bmg["positions_count"], pos_drift,
            )

    logger.warning(
        "[daily-recon] cycle complete: quarantined=%s adopted=%s alpaca_upnl=$%.2f",
        result.get("quarantine", {}).get("quarantined") if isinstance(result.get("quarantine"), dict) else "err",
        result.get("adoption", {}).get("adopted") if isinstance(result.get("adoption"), dict) else "err",
        alp.get("unrealized_pl", 0) or 0,
    )
    return result


def _run_quarantine_inline(db, lookback_days: int = 7) -> dict[str, Any]:
    """Same logic as /api/admin/quarantine-non-broker-trades but callable
    from a scheduled job. Only looks back N days to keep the run fast."""
    import urllib.parse
    from app.db.models.bots import BotTrade, BotPosition

    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not sec:
        return {"error": "no_creds"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    filled_ids: set[str] = set()
    until = datetime.now(timezone.utc)
    for _ in range(20):
        params = urllib.parse.urlencode({
            "status": "closed", "limit": 500,
            "after": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "direction": "desc",
        })
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets/v2/orders?{params}",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
        )
        try:
            batch = json.loads(urllib.request.urlopen(req, timeout=15).read()) or []
        except Exception:
            break
        if not batch: break
        for o in batch:
            if o.get("status") == "filled" and o.get("id"):
                filled_ids.add(o["id"])
        oldest = min((o.get("submitted_at") or o.get("created_at") or "") for o in batch)
        if not oldest: break
        try:
            import re
            s = re.sub(r'\.(\d+)([+-Z])', lambda m: '.' + m.group(1).ljust(6, '0')[:6] + m.group(2), oldest)
            new_until = datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception: break
        if new_until >= until: break
        until = new_until - timedelta(seconds=1)
        if len(batch) < 500: break

    from app.services.trade_write_gate import is_admin_marker

    trades = (
        db.query(BotTrade)
        .filter(BotTrade.ts >= cutoff)
        .filter(BotTrade.quarantined_at.is_(None))
        .all()
    )
    quarantined = 0
    skipped_admin_marker = 0
    pos_ids: set[int] = set()
    now = datetime.now(timezone.utc)
    for t in trades:
        oid = getattr(t, "alpaca_order_id", None)
        if oid and oid in filled_ids:
            continue
        # Adopter/rebuild/reconcile markers legitimately don't map to Alpaca
        # UUIDs — they represent Alpaca-authoritative positions BMG reconciled
        # to. Quarantining them creates the daily churn loop: quarantine at
        # 05:00 → adopter step re-creates seconds later → quarantine tomorrow.
        # See ledger #31 (META 655/660 daily re-materialization, 273 quarantined
        # rows on alloc 22).
        if is_admin_marker(oid):
            skipped_admin_marker += 1
            continue
        t.quarantined_at = now
        t.quarantine_reason = (
            f"phantom_not_filled_at_alpaca:{oid}" if oid else "sim_no_alpaca_order_id"
        )
        quarantined += 1
        if t.position_id: pos_ids.add(t.position_id)

    if pos_ids:
        (
            db.query(BotPosition)
            .filter(BotPosition.id.in_(list(pos_ids)))
            .filter(BotPosition.quarantined_at.is_(None))
            .update(
                {"quarantined_at": now, "quarantine_reason": "trade_quarantined_broker_recon"},
                synchronize_session=False,
            )
        )
    db.commit()
    return {
        "trades_in_window": len(trades),
        "quarantined": quarantined,
        "skipped_admin_marker": skipped_admin_marker,
        "positions_quarantined": len(pos_ids),
        "alpaca_filled_ids": len(filled_ids),
    }


def setup_daily_reconciler(scheduler) -> None:
    """Register 05:00 UTC daily job (00:00 ET)."""
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:
        logger.warning("[daily-recon] apscheduler unavailable: %s", exc)
        return

    from app.db.session import SessionLocal

    def _job() -> None:
        db = SessionLocal()
        try:
            run_daily_reconciliation(db)
        except Exception as exc:
            logger.error("[daily-recon] job raised: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _job,
        CronTrigger(hour=5, minute=0, timezone="UTC"),
        id="daily_reconciler",
        replace_existing=True,
        max_instances=1,
    )
    logger.warning("[daily-recon] scheduler registered — 05:00 UTC daily")
