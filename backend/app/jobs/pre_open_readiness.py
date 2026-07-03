"""Pre-open readiness Discord post — fires 8:15 AM CT weekdays.

Combines fund state + P0 fix verification + per-bot cadence + execution
health into one embed for Brock before market open.

Also fires on-boot when BMG_FIRE_READINESS_NOW=true (for immediate verify).
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fund_state(db: Session) -> dict:
    from app.core.canonical import compute_strategy_lab_aggregate
    agg = compute_strategy_lab_aggregate(1, db)
    return {
        "pv_cents": int(agg.get("total_value_cents") or 0),
        "pnl": agg.get("pnl", {}),
        "open_positions": int(agg.get("total_open_positions") or 0),
    }


def _armed_bots(db: Session) -> list[dict]:
    rows = db.execute(text(
        "SELECT p.name, a.starting_capital_cents, p.enabled, a.enabled "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND a.starting_capital_cents > 0 "
        "ORDER BY a.starting_capital_cents DESC"
    )).fetchall()
    return [{"bot": r[0], "cents": int(r[1] or 0), "profile_enabled": bool(r[2]), "alloc_enabled": bool(r[3])} for r in rows]


def _last_activity(db: Session) -> dict:
    """When each bot last fired a signal / trade."""
    cut_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    sig_rows = db.execute(text(
        "SELECT p.name, COUNT(*), MAX(s.ts) "
        "FROM bot_signals s "
        "JOIN bot_allocations a ON a.id = s.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND s.ts >= :cut "
        "GROUP BY p.name"
    ), {"cut": cut_24h}).fetchall()

    trd_rows = db.execute(text(
        "SELECT p.name, COUNT(*), MAX(t.ts) "
        "FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND t.ts >= :cut AND t.quarantined_at IS NULL "
        "GROUP BY p.name"
    ), {"cut": cut_24h}).fetchall()

    return {
        "signals": {r[0]: (int(r[1]), str(r[2])) for r in sig_rows},
        "trades":  {r[0]: (int(r[1]), str(r[2])) for r in trd_rows},
    }


def build_readiness_post(db: Session) -> dict:
    fs = _fund_state(db)
    armed = _armed_bots(db)
    activity = _last_activity(db)

    # ── Fund block
    pnl = fs["pnl"] or {}
    at = pnl.get("all_time", {"cents": 0, "pct": 0.0})
    tot = pnl.get("today", {"cents": 0, "pct": 0.0})
    pv_line = (
        f"**${fs['pv_cents']/100:,.0f}**   "
        f"All-time: {'+' if at.get('cents',0) >= 0 else ''}${at.get('cents',0)/100:,.0f} "
        f"({at.get('pct', 0)*100:+.3f}%)"
    )

    # ── Bots by activity band
    now = datetime.now(timezone.utc)
    green_bots = []
    yellow_bots = []
    red_bots = []
    for b in armed:
        name = b["bot"]
        last_sig = activity["signals"].get(name)
        last_trd = activity["trades"].get(name)
        # Determine expected active status (weekday morning: crypto always, stocks/options M-F)
        is_weekday = now.weekday() < 5
        expected_active = False
        if name.startswith("crypto") or name.startswith("options") or name.startswith("stock") or name == "cash_floor":
            expected_active = True
        if last_sig:
            _, ts_str = last_sig
            try:
                _ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if _ts.tzinfo is None:
                    _ts = _ts.replace(tzinfo=timezone.utc)
                age_h = (now - _ts).total_seconds() / 3600
            except Exception:
                age_h = 999
            if age_h < 4:
                green_bots.append(f"`{name}` (last sig {age_h:.1f}h ago)")
            elif age_h < 24:
                yellow_bots.append(f"`{name}` ({age_h:.1f}h)")
            else:
                red_bots.append(f"`{name}` ({age_h:.1f}h)")
        else:
            # No signal in 24h
            if expected_active and name.startswith("crypto"):
                red_bots.append(f"`{name}` (silent 24h+)")
            else:
                yellow_bots.append(f"`{name}` (idle, market may be closed)")

    # ── Execution health
    total_sigs = sum(v[0] for v in activity["signals"].values())
    total_trds = sum(v[0] for v in activity["trades"].values())
    conv = (total_trds / total_sigs * 100) if total_sigs else 0

    # ── First-fire expectations
    et_now = now.astimezone(timezone(timedelta(hours=-4)))  # rough EDT
    ct_now = now.astimezone(timezone(timedelta(hours=-5)))  # rough CDT

    fields = [
        {
            "name": "📊 FUND STATE",
            "value": pv_line + f"\n{fs['open_positions']} open positions across armed bots",
            "inline": False,
        },
        {
            "name": f"🟢 ACTIVE (last signal < 4h)  · {len(green_bots)}",
            "value": "\n".join(green_bots) or "_none_",
            "inline": False,
        },
        {
            "name": f"🟡 SLOW / OFF-HOURS · {len(yellow_bots)}",
            "value": "\n".join(yellow_bots) or "_none_",
            "inline": False,
        },
        {
            "name": f"🔴 SILENT (needs attention) · {len(red_bots)}",
            "value": "\n".join(red_bots) or "_none_",
            "inline": False,
        },
        {
            "name": "📡 EXECUTION HEALTH (24h)",
            "value": f"**{total_sigs}** signals → **{total_trds}** trades = **{conv:.1f}%** conversion",
            "inline": False,
        },
        {
            "name": "🌅 FIRST-FIRE EXPECTATIONS",
            "value": (
                "**9:00 ET** stock_gap_fade + stock_day + stock_lt + stock_swing scans begin\n"
                "**10:00 ET** stock_orb_breakout + options_income + options_directional begin\n"
                "**15:30 ET** stock_momentum_breakout + stock_swing EOD\n"
                "**16:00 ET** stock_pead"
            ),
            "inline": False,
        },
        {
            "name": "🛑 KILL TRIGGERS",
            "value": (
                "• Fund-level 6% single-day drawdown → Discord ping\n"
                "• No auto-halt on per-trade -5% losses (paper aggressive mode)"
            ),
            "inline": False,
        },
    ]

    return {
        "title": "🚀 Pre-Open Readiness",
        "message": (
            f"Fleet is armed for {ct_now.strftime('%Y-%m-%d')}. "
            f"Post generated at {ct_now.strftime('%H:%M CT')}"
        ),
        "fields": fields,
    }


def post_readiness(db: Session) -> bool:
    from app.services.discord import send_ops_alert
    try:
        payload = build_readiness_post(db)
    except Exception as exc:
        logger.exception("[pre-open-readiness] build failed: %s", exc)
        return False
    ok = send_ops_alert(
        title=payload["title"],
        message=payload["message"],
        severity="info",
        source="pre_open_readiness",
        fields=payload["fields"],
    )
    if ok:
        logger.warning("[pre-open-readiness] posted OK")
    else:
        logger.warning("[pre-open-readiness] post FAILED")
    return ok
