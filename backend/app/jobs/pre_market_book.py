"""Pre-market book post — fires 8:00 AM CT weekdays.

Reads current fund state and posts a "here's what I'm running today"
embed to the ops Discord channel. First execution of Brock's aggressive-
paper-trading directive: prove the machine is awake, sized, and pressing.

Sections:
  1. PV + P&L windows (all-time / mtd / wtd)
  2. Deployment ratio + open positions count
  3. Bots armed for today with their size + cap
  4. Signals fired in the last 24h (top 5 bots by volume)
  5. Trades filled in the last 24h
  6. Kill triggers (fund-level 6% single-day drawdown, per Brock)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fmt_usd(cents: int) -> str:
    usd = cents / 100
    sign = "+" if usd >= 0 else "-"
    return f"{sign}${abs(usd):,.0f}"


def _fund_pv_and_pnl(db: Session, user_id: int = 1) -> dict:
    """Sum starting_capital + realized + unrealized across all user_1 allocations."""
    row = db.execute(text(
        "SELECT "
        "  COALESCE(SUM(starting_capital_cents), 0), "
        "  COALESCE(SUM(current_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": user_id}).fetchone()
    starting = int(row[0] or 0)
    current = int(row[1] or 0)
    if current == 0:
        current = starting  # fallback if current not populated
    # 2026-07-06: include portfolio-rank capital so the pre-market digest
    # matches the $1M fund invariant. Portfolio-rank bots contribute their
    # starting_capital + SUM(current_pnl_cents on holdings).
    try:
        pr_starting_row = db.execute(text(
            "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM portfolio_rank_bots"
        )).fetchone()
        pr_starting = int(pr_starting_row[0] or 0) if pr_starting_row else 0
        pr_pnl_row = db.execute(text(
            "SELECT COALESCE(SUM(current_pnl_cents), 0) FROM portfolio_rank_holdings"
        )).fetchone()
        pr_pnl = int(pr_pnl_row[0] or 0) if pr_pnl_row else 0
        starting += pr_starting
        current += pr_starting + pr_pnl
    except Exception:
        pass
    return {
        "pv_cents": current,
        "starting_cents": starting,
        "all_time_pnl_cents": current - 100_000_000,  # vs $1M inception
    }


def _deployment_ratio(db: Session, user_id: int = 1) -> dict:
    """Sum of open position entry-cost / total starting_capital."""
    row = db.execute(text(
        "SELECT "
        "  COALESCE(SUM(p.qty * p.avg_cost_cents), 0), "
        "  COUNT(*) "
        "FROM bot_positions p "
        "JOIN bot_allocations a ON a.id = p.allocation_id "
        "WHERE a.user_id = :uid AND p.closed_at IS NULL "
        "AND (p.quarantined_at IS NULL)"
    ), {"uid": user_id}).fetchone()
    deployed_cents = int(row[0] or 0)
    n_open = int(row[1] or 0)
    total = db.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": user_id}).fetchone()[0] or 1
    return {
        "deployed_cents": deployed_cents,
        "n_open_positions": n_open,
        "deployment_ratio": deployed_cents / int(total),
    }


def _armed_bots(db: Session, user_id: int = 1) -> list[dict]:
    """List of user_1 bots with enabled=True, sorted by capital desc."""
    rows = db.execute(text(
        "SELECT p.name, a.starting_capital_cents, p.enabled "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid AND a.starting_capital_cents > 0 "
        "ORDER BY a.starting_capital_cents DESC"
    ), {"uid": user_id}).fetchall()
    return [
        {"bot": r[0], "cents": int(r[1] or 0), "enabled": bool(r[2])}
        for r in rows
    ]


def _recent_activity(db: Session, hours: int = 24) -> dict:
    """Signals + trades in last N hours across ALL user_1 allocations."""
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    sig_rows = db.execute(text(
        "SELECT p.name, COUNT(*) "
        "FROM bot_signals s "
        "JOIN bot_allocations a ON a.id = s.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND s.ts >= :cut "
        "GROUP BY p.name ORDER BY COUNT(*) DESC LIMIT 8"
    ), {"cut": cut}).fetchall()
    trd_rows = db.execute(text(
        "SELECT p.name, COUNT(*) "
        "FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND t.ts >= :cut AND t.quarantined_at IS NULL "
        "GROUP BY p.name ORDER BY COUNT(*) DESC LIMIT 8"
    ), {"cut": cut}).fetchall()
    return {
        "signals": [(r[0], int(r[1])) for r in sig_rows],
        "trades":  [(r[0], int(r[1])) for r in trd_rows],
    }


def build_pre_market_post(db: Session) -> dict:
    """Assemble the pre-market embed dict."""
    pv = _fund_pv_and_pnl(db)
    dep = _deployment_ratio(db)
    armed = _armed_bots(db)
    recent = _recent_activity(db, hours=24)

    # Header line: PV + P&L window
    pv_line = f"**${pv['pv_cents']/100:,.0f}**   {_fmt_usd(pv['all_time_pnl_cents'])} all-time"

    # Deployment
    dep_line = (
        f"**{dep['deployment_ratio']*100:.1f}%** deployed  ·  "
        f"{dep['n_open_positions']} open positions  ·  "
        f"${dep['deployed_cents']/100:,.0f} at risk"
    )

    # Armed bots — group by tier
    enabled_bots = [b for b in armed if b["enabled"]]
    total_armed_cents = sum(b["cents"] for b in enabled_bots)
    armed_lines = []
    for b in enabled_bots[:12]:
        armed_lines.append(f"`{b['bot']:<28}` ${b['cents']/100:>7,.0f}")
    if len(enabled_bots) > 12:
        armed_lines.append(f"_+{len(enabled_bots)-12} more_")

    # 24h activity
    total_sigs = sum(c for _, c in recent["signals"])
    total_trds = sum(c for _, c in recent["trades"])
    conv = (total_trds / total_sigs * 100) if total_sigs else 0
    activity_lines = [
        f"**{total_sigs}** signals  →  **{total_trds}** trades  =  **{conv:.1f}%** conversion",
        "",
        "Top signal generators:",
    ]
    for name, cnt in recent["signals"][:5]:
        activity_lines.append(f"  `{name:<28}` {cnt} sigs")
    if recent["trades"]:
        activity_lines.append("\nTrades filled:")
        for name, cnt in recent["trades"][:5]:
            activity_lines.append(f"  `{name:<28}` {cnt} trades")

    fields = [
        {"name": "📊 PORTFOLIO", "value": pv_line, "inline": False},
        {"name": "💰 DEPLOYMENT", "value": dep_line, "inline": False},
        {"name": f"🤖 ARMED FOR TODAY ({len(enabled_bots)} bots, ${total_armed_cents/100:,.0f})",
         "value": "\n".join(armed_lines) or "_none_", "inline": False},
        {"name": "📡 24h ACTIVITY", "value": "\n".join(activity_lines), "inline": False},
        {"name": "🛑 KILL TRIGGERS",
         "value": "• Fund-level 6% single-day drawdown → Discord ping\n"
                  "• No per-bot auto-halt on individual -5% losses (paper aggressive mode)",
         "inline": False},
    ]

    return {
        "title": "🌅 Pre-Market Book",
        "message": f"Market open in ~30 min. Fleet is armed and pressing.\n"
                   f"Session date: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        "fields": fields,
    }


def post_pre_market_book(db: Session) -> bool:
    """Build + post the pre-market embed. Returns True on 2xx."""
    from app.services.discord import send_ops_alert
    try:
        payload = build_pre_market_post(db)
    except Exception as exc:
        logger.exception("[pre-market-book] build failed: %s", exc)
        return False
    ok = send_ops_alert(
        title=payload["title"],
        message=payload["message"],
        severity="info",
        source="pre_market_book",
        fields=payload["fields"],
    )
    if ok:
        logger.warning("[pre-market-book] posted OK")
    else:
        logger.warning("[pre-market-book] post FAILED (see ops-alert logs)")
    return ok
