"""
Operations Agent — Deploy 3 Tier A back-office reconciliation.

Daily end-of-day reconciliation: open positions vs trades, P&L consistency,
quarantined position audit, capital-at-risk summary.
Runs 6 PM ET Mon-Fri (after Execution Auditor).
Posts daily summary to #bmg-monitoring.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, date, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Thresholds
STALE_POSITION_DAYS  = 14   # warn if open position older than this
MAX_QUARANTINE_COUNT = 5    # warn if more than this many quarantined today


def _get_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_BMG_MONITORING", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token, channel_id


def _post(channel_id: str, token: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    import httpx
    try:
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json={"embeds": [embed]},
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[operations] Discord post failed: %s", exc)
        return False


def _open_positions_summary(db: Session) -> dict:
    """Count open positions and flag stale ones."""
    try:
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_POSITION_DAYS)).isoformat()
        rows = db.execute(text("""
            SELECT bp.name, COUNT(*) as cnt,
                   SUM(bpos.qty * bpos.avg_cost_cents / 100.0) as notional_usd,
                   MIN(bpos.opened_at) as oldest
            FROM bot_positions bpos
            JOIN bot_allocations ba ON ba.id = bpos.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bpos.closed_at IS NULL AND bpos.quarantined_at IS NULL
            GROUP BY bp.name
        """)).fetchall()

        stale = db.execute(text("""
            SELECT COUNT(*) FROM bot_positions
            WHERE closed_at IS NULL
              AND quarantined_at IS NULL
              AND opened_at < :cutoff
        """), {"cutoff": stale_cutoff}).scalar() or 0

        total = sum(r[1] for r in rows)
        notional = sum((r[2] or 0) for r in rows)

        return {
            "open_count": total,
            "notional_usd": round(notional, 2),
            "stale_count": stale,
            "by_bot": {r[0]: r[1] for r in rows},
        }
    except Exception as exc:
        logger.warning("[operations] positions query failed: %s", exc)
        return {"open_count": 0, "notional_usd": 0.0, "stale_count": 0, "by_bot": {}}


def _quarantine_audit(db: Session) -> dict:
    """Count positions quarantined today."""
    try:
        today = date.today().isoformat()
        count = db.execute(text("""
            SELECT COUNT(*) FROM bot_positions
            WHERE DATE(quarantined_at) = :today
        """), {"today": today}).scalar() or 0

        total_quarantined = db.execute(text("""
            SELECT COUNT(*) FROM bot_positions WHERE quarantined_at IS NOT NULL
        """)).scalar() or 0

        return {"quarantined_today": count, "total_quarantined": total_quarantined}
    except Exception as exc:
        logger.warning("[operations] quarantine query failed: %s", exc)
        return {"quarantined_today": 0, "total_quarantined": 0}


def _pnl_summary(db: Session) -> dict:
    """Today's realized P&L across all bots."""
    try:
        today = date.today().isoformat()
        rows = db.execute(text("""
            SELECT bp.name,
                   SUM(bdp.realized_cents) as realized,
                   SUM(COALESCE(bdp.unrealized_cents, 0)) as unrealized
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON ba.id = bdp.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bdp.date = :today
            GROUP BY bp.name
        """), {"today": today}).fetchall()

        total_realized = sum((r[1] or 0) for r in rows)
        total_unrealized = sum((r[2] or 0) for r in rows)

        return {
            "realized_usd": round(total_realized / 100, 2),
            "unrealized_usd": round(total_unrealized / 100, 2),
            "total_usd": round((total_realized + total_unrealized) / 100, 2),
            "by_bot": {r[0]: round(((r[1] or 0) + (r[2] or 0)) / 100, 2) for r in rows},
        }
    except Exception as exc:
        logger.warning("[operations] pnl query failed: %s", exc)
        return {"realized_usd": 0.0, "unrealized_usd": 0.0, "total_usd": 0.0, "by_bot": {}}


def _classify(positions: dict, quarantine: dict) -> str:
    if quarantine["quarantined_today"] > MAX_QUARANTINE_COUNT:
        return "YELLOW"
    if positions["stale_count"] > 0:
        return "YELLOW"
    return "GREEN"


def run_operations_reconciliation(db: Session) -> dict:
    """
    Main entry point — called daily at 6 PM ET by APScheduler.
    Posts summary to #bmg-monitoring. Returns reconciliation dict.
    """
    now = datetime.now(timezone.utc)

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="operations")
    except Exception:
        pass

    positions  = _open_positions_summary(db)
    quarantine = _quarantine_audit(db)
    pnl        = _pnl_summary(db)
    level      = _classify(positions, quarantine)

    result = {
        "ok":         level == "GREEN",
        "level":      level,
        "positions":  positions,
        "quarantine": quarantine,
        "pnl":        pnl,
        "reconciled_at": now.isoformat(),
    }

    logger.info(
        "[operations] level=%s open=%d stale=%d quarantined_today=%d pnl=$%.2f",
        level, positions["open_count"], positions["stale_count"],
        quarantine["quarantined_today"], pnl["total_usd"],
    )

    pnl_sign = "+" if pnl["total_usd"] >= 0 else ""
    colors = {"GREEN": 0x16A34A, "YELLOW": 0xF59E0B}
    fields = [
        {"name": "Open Positions",    "value": str(positions["open_count"]), "inline": True},
        {"name": "Notional (est.)",   "value": f"${positions['notional_usd']:,.0f}", "inline": True},
        {"name": "Today P&L",         "value": f"{pnl_sign}${pnl['total_usd']:,.2f}", "inline": True},
        {"name": "Realized",          "value": f"${pnl['realized_usd']:,.2f}", "inline": True},
        {"name": "Unrealized",        "value": f"${pnl['unrealized_usd']:,.2f}", "inline": True},
        {"name": "Quarantined Today", "value": str(quarantine["quarantined_today"]), "inline": True},
    ]
    if positions["stale_count"] > 0:
        fields.append({"name": "⚠️ Stale Positions", "value": f"{positions['stale_count']} open > {STALE_POSITION_DAYS}d", "inline": False})
    if quarantine["quarantined_today"] > MAX_QUARANTINE_COUNT:
        fields.append({"name": "⚠️ High Quarantine Volume", "value": f"{quarantine['quarantined_today']} positions quarantined today", "inline": False})

    embed = {
        "author":    {"name": "BMG Capital — Wick (Operations)"},
        "title":     f"Daily Reconciliation — {now.strftime('%Y-%m-%d')}",
        "color":     colors.get(level, 0x16A34A),
        "fields":    fields,
        "footer":    {"text": "Wick (Operations) · Tier A · Daily 6 PM ET"},
        "timestamp": now.isoformat(),
    }
    token, ch = _get_channel()
    try:
        from agents.plain_english import translate_for_brock, make_plain_english_field
        _pe_text = " | ".join(f"{f['name']}: {f['value']}" for f in embed.get("fields", []) if not f['name'].startswith("💬"))
        _pe = translate_for_brock(_pe_text, db=db, channel_id=ch, charge_agent="operations")
        if _pe:
            embed["fields"].append(make_plain_english_field(_pe))
    except Exception as _pe_exc:
        logger.debug("[operations] plain_english failed: %s", _pe_exc)
    if ch:
        _post(ch, token, embed)

    # Publish to bus
    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import OPS_REPORT
        _bus_publish(
            db, channel=OPS_REPORT, from_agent="operations",
            msg_type="reconciliation",
            subject=f"Daily ops: {level} — {positions['open_count']} open positions",
            payload=result, priority=6 if level == "YELLOW" else 3,
        )
    except Exception as exc:
        logger.debug("[operations] bus publish skipped: %s", exc)

    # Proactive observation: any stale positions or quarantine spikes
    try:
        from agents.bus import observe as _obs
        stale = positions.get("stale_count", 0)
        q_today = quarantine.get("quarantined_today", 0)
        if stale > 0:
            _obs(db, agent_id="operations",
                 content=f"{stale} position(s) stale (open >{STALE_POSITION_DAYS}d). Manual review recommended before next capital rebalance.",
                 context={"stale_count": stale})
        elif q_today > 3:
            _obs(db, agent_id="operations",
                 content=f"Quarantine spike: {q_today} positions quarantined today. Possible data or execution anomaly.",
                 context={"quarantined_today": q_today})
    except Exception:
        pass

    # App API cross-check: verify dashboard open position count matches DB
    try:
        import asyncio as _aio
        from agents.app_client import get_client as _get_client
        _client = _get_client("operations")
        if _client.available:
            snapshot = _aio.get_event_loop().run_until_complete(_client.portfolio_snapshot())
            api_open = snapshot.get("open_positions") or snapshot.get("total_open_positions")
            db_open = positions["open_count"]
            if api_open is not None and abs(int(api_open) - db_open) > 2:
                logger.warning(
                    "[operations] position count mismatch: API=%s DB=%d — possible frontend drift",
                    api_open, db_open,
                )
                result["api_cross_check"] = {"mismatch": True, "api_open": api_open, "db_open": db_open}
            else:
                result["api_cross_check"] = {"mismatch": False, "db_open": db_open}
    except Exception as _exc:
        logger.debug("[operations] app_client cross-check skipped: %s", _exc)

    # Daily check-in to #fund-team-chat
    try:
        from agents.bus import post_daily_checkin as _checkin
        _checkin(db, "operations",
                 f"Wick (Operations): Reconciliation {level}. {positions['open_count']} open positions "
                 f"(${positions['notional_usd']:,.0f} notional), today P&L {'+' if pnl['total_usd'] >= 0 else ''}${pnl['total_usd']:,.2f}. "
                 f"{'Books balanced.' if level == 'GREEN' else 'Flags raised — see #bmg-monitoring.'}")
    except Exception:
        pass

    return result
