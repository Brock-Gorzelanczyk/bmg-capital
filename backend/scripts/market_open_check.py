"""Market open readiness check.

Runs 8:55 AM CT weekdays. Posts to Discord ops channel with the state of
the fleet 5 min before market open. Verifies:
  - Fleet total capital
  - Active + halted bot counts
  - Signals + trades in the last hour
  - Portfolio value + cash floor
  - Any bot without a heartbeat in last 6h

Usage: run manually or wire to APScheduler.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def build_check(db: Session, user_id: int = 1) -> dict:
    now = datetime.now(timezone.utc)
    cut_1h = (now - timedelta(hours=1)).isoformat()
    cut_6h = (now - timedelta(hours=6)).isoformat()

    # Fleet total capital
    fleet_total_row = db.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": user_id}).fetchone()
    fleet_total = int(fleet_total_row[0] or 0)

    # Active bot count
    active_row = db.execute(text(
        "SELECT COUNT(*) FROM bot_allocations "
        "WHERE user_id = :uid AND starting_capital_cents > 0 AND enabled = 1"
    ), {"uid": user_id}).fetchone()
    active_count = int(active_row[0] or 0)

    # Halted bots
    halted_row = db.execute(text(
        "SELECT COUNT(*) FROM bot_allocations "
        "WHERE user_id = :uid AND (enabled = 0 OR paused_reason IS NOT NULL) "
        "  AND starting_capital_cents = 0"
    ), {"uid": user_id}).fetchone()
    halted_count = int(halted_row[0] or 0)

    # Signals + trades last 1h
    sig_1h = db.execute(text(
        "SELECT COUNT(*) FROM bot_signals s "
        "JOIN bot_allocations a ON a.id = s.allocation_id "
        "WHERE a.user_id = :uid AND s.ts >= :cut"
    ), {"uid": user_id, "cut": cut_1h}).fetchone()
    signals_1h = int(sig_1h[0] or 0)

    trd_1h = db.execute(text(
        "SELECT COUNT(*) FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = :uid AND t.ts >= :cut AND t.quarantined_at IS NULL"
    ), {"uid": user_id, "cut": cut_1h}).fetchone()
    trades_1h = int(trd_1h[0] or 0)

    # Portfolio value via canonical aggregator
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(user_id, db) or {}
        pv_cents = int(agg.get("total_value_cents") or 0)
    except Exception as exc:
        logger.warning("[market_open_check] aggregate failed: %s", exc)
        pv_cents = 0

    # Cash floor allocation
    cf_row = db.execute(text(
        "SELECT COALESCE(a.starting_capital_cents, 0) "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid AND p.name = 'cash_floor'"
    ), {"uid": user_id}).fetchone()
    cash_floor_cents = int(cf_row[0] or 0) if cf_row else 0

    # Stale bots (no signal in last 6h among enabled bots)
    stale_rows = db.execute(text(
        "SELECT p.name, MAX(s.ts) AS last_ts "
        "FROM bot_profiles p "
        "JOIN bot_allocations a ON a.profile_id = p.id AND a.user_id = :uid "
        "LEFT JOIN bot_signals s ON s.allocation_id = a.id "
        "WHERE a.starting_capital_cents > 0 AND a.enabled = 1 "
        "GROUP BY p.name "
        "HAVING MAX(s.ts) < :cut OR MAX(s.ts) IS NULL"
    ), {"uid": user_id, "cut": cut_6h}).fetchall()
    stale = [{"bot": r[0], "last_signal": str(r[1]) if r[1] else None} for r in stale_rows]

    return {
        "as_of": now.isoformat(),
        "user_id": user_id,
        "fleet_total_usd": fleet_total / 100,
        "active_bots": active_count,
        "halted_bots": halted_count,
        "signals_last_1h": signals_1h,
        "trades_last_1h": trades_1h,
        "portfolio_value_usd": pv_cents / 100,
        "cash_floor_usd": cash_floor_cents / 100,
        "stale_bots_over_6h": stale,
        "stale_count": len(stale),
    }


def post_market_open_check(db: Session) -> bool:
    from app.services.discord import send_ops_alert
    payload = build_check(db)

    fleet_ok = abs(payload["fleet_total_usd"] - 1_000_000) < 1
    stale_ok = payload["stale_count"] == 0

    msg_lines = [
        f"**Fleet total capital:** ${payload['fleet_total_usd']:,.0f}  {'PASS' if fleet_ok else 'FAIL'}",
        f"**Active bots:** {payload['active_bots']}",
        f"**Halted bots:** {payload['halted_bots']}",
        f"**Portfolio value:** ${payload['portfolio_value_usd']:,.0f}",
        f"**Cash floor:** ${payload['cash_floor_usd']:,.0f}",
        f"**Signals last 1h:** {payload['signals_last_1h']}",
        f"**Trades last 1h:** {payload['trades_last_1h']}",
        f"**Stale bots (>6h no signal):** {payload['stale_count']}",
    ]
    if payload["stale_bots_over_6h"]:
        msg_lines.append("")
        msg_lines.append("Stale bots:")
        for s in payload["stale_bots_over_6h"][:10]:
            msg_lines.append(f"  - {s['bot']} (last: {s['last_signal'] or 'never'})")

    return send_ops_alert(
        title="Market Open Check (8:55 CT)",
        message="\n".join(msg_lines),
        severity="info" if (fleet_ok and stale_ok) else "warn",
        source="market_open_check",
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/app")
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        import json
        result = build_check(db)
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()
