"""
Risk Sentinel — Deploy 2 Tier A autonomous risk watchdog.

Monitors drawdown, fleet health, and position concentration.
Holds veto power over Portfolio Manager.
Runs every 30 minutes — posts to #risk-alerts when YELLOW or RED.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Risk thresholds
DRAWDOWN_WARN_PCT   = 8.0   # YELLOW
DRAWDOWN_HALT_PCT   = 15.0  # RED — propose fleet pause
CONSEC_LOSS_WARN    = 4     # YELLOW
CONSEC_LOSS_HALT    = 7     # RED
STALE_BOT_WARN      = 2     # YELLOW if 2+ bots stale
CRITICAL_DRAWDOWN_PCT = -4.0  # 24h drawdown worse than this → CRITICAL

# 4h cooldown on repeated RED alerts to reduce noise
_last_alert_ts: dict[str, datetime] = {}
_ALERT_COOLDOWN_HOURS = 4


def _get_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_RISK_ALERTS", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token, channel_id


def _post(channel_id: str, token: str, embed: dict, content: str = "") -> bool:
    if not channel_id or not token:
        return False
    import httpx
    try:
        payload: dict = {"embeds": [embed]}
        if content:
            payload["content"] = content
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json=payload,
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[risk_sentinel] Discord post failed: %s", exc)
        return False


def _get_fleet_drawdown(db: Session) -> dict:
    """Compute max drawdown across all active bots from bot_daily_pnl."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        rows = db.execute(text("""
            SELECT bp.name, SUM(bdp.realized_cents + COALESCE(bdp.unrealized_cents, 0)) as total_pnl,
                   MIN(bdp.realized_cents + COALESCE(bdp.unrealized_cents, 0)) as worst_day
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON ba.id = bdp.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bdp.date >= :cutoff AND ba.enabled = 1
            GROUP BY bp.name
        """), {"cutoff": cutoff}).fetchall()

        bots = []
        total_pnl = 0
        for row in rows:
            pnl_usd = (row[1] or 0) / 100
            bots.append({"bot": row[0], "pnl_usd": round(pnl_usd, 2), "worst_day_usd": round((row[2] or 0) / 100, 2)})
            total_pnl += pnl_usd

        return {"bots": bots, "total_pnl_usd": round(total_pnl, 2)}
    except Exception as exc:
        logger.warning("[risk_sentinel] drawdown query failed: %s", exc)
        return {"bots": [], "total_pnl_usd": 0}


def _get_consecutive_losses(db: Session) -> dict[str, int]:
    """Count consecutive losing days per bot."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
        rows = db.execute(text("""
            SELECT bp.name, bdp.date,
                   (bdp.realized_cents + COALESCE(bdp.unrealized_cents, 0)) as day_pnl
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON ba.id = bdp.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bdp.date >= :cutoff AND ba.enabled = 1
            ORDER BY bp.name, bdp.date DESC
        """), {"cutoff": cutoff}).fetchall()

        streaks: dict[str, int] = {}
        by_bot: dict[str, list] = {}
        for r in rows:
            by_bot.setdefault(r[0], []).append(r[2])

        for bot, pnls in by_bot.items():
            streak = 0
            for p in pnls:  # already sorted desc (most recent first)
                if p < 0:
                    streak += 1
                else:
                    break
            streaks[bot] = streak

        return streaks
    except Exception as exc:
        logger.warning("[risk_sentinel] consec_loss query failed: %s", exc)
        return {}


def _get_stale_bots(db: Session) -> list[str]:
    """Return names of bots that haven't fired a signal recently."""
    try:
        from strategy_lab.agents.strategy_monitor import run_strategy_health_check
        health = run_strategy_health_check(db)
        return [b["bot"] for b in health.get("bots", []) if b.get("status") == "STALE"]
    except Exception:
        return []


def _get_fleet_drawdown_24h(db: Session) -> float:
    """
    Compute the fleet's 24h P&L as a percentage of starting capital.
    Returns a negative float (e.g. -5.2 means -5.2%) when losing, 0.0 on error.
    Starting capital is estimated as the sum of all active allocation amounts.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = db.execute(text("""
            SELECT SUM(bt.pnl_cents) as pnl_24h,
                   SUM(ba.allocated_cents) as starting_capital
            FROM bot_trades bt
            JOIN bot_allocations ba ON ba.id = bt.allocation_id
            WHERE bt.closed_at >= :since AND ba.enabled = 1
        """), {"since": since}).fetchone()

        if not row or not row[1] or row[1] == 0:
            return 0.0

        pnl_24h = (row[0] or 0) / 100.0
        starting_capital = row[1] / 100.0
        return round(pnl_24h / starting_capital * 100, 4)
    except Exception as exc:
        logger.warning("[risk_sentinel] 24h drawdown query failed: %s", exc)
        return 0.0


def _classify(drawdown_pct: float, consec_losses: int, stale_count: int,
              drawdown_24h_pct: float = 0.0, circuit_breaker_tripped: bool = False) -> str:
    # CRITICAL takes precedence over RED
    if drawdown_24h_pct <= CRITICAL_DRAWDOWN_PCT:
        return "CRITICAL"
    if circuit_breaker_tripped:
        return "CRITICAL"
    if drawdown_pct >= DRAWDOWN_HALT_PCT or consec_losses >= CONSEC_LOSS_HALT:
        return "RED"
    if drawdown_pct >= DRAWDOWN_WARN_PCT or consec_losses >= CONSEC_LOSS_WARN or stale_count >= STALE_BOT_WARN:
        return "YELLOW"
    return "GREEN"


def _build_embed(level: str, summary: dict, now: datetime) -> dict:
    colors = {
        "GREEN":    0x16A34A,
        "YELLOW":   0xF59E0B,
        "RED":      0xDC2626,
        "CRITICAL": 0x7F1D1D,
    }
    icons = {
        "GREEN":    "✅",
        "YELLOW":   "⚠️",
        "RED":      "🚨",
        "CRITICAL": "🔴",
    }
    titles = {
        "GREEN":    f"Risk Health Check — {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "YELLOW":   f"Risk Health Check — {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "RED":      "🚨 Dick (CRO) — RED ALERT",
        "CRITICAL": "🔴 Dick (CRO) — CRITICAL ALERT",
    }
    fields = [
        {"name": f"{icons[level]} Risk Level", "value": level, "inline": True},
        {"name": "Fleet P&L (30d)",            "value": f"${summary['total_pnl_usd']:,.2f}", "inline": True},
        {"name": "Stale Bots",                 "value": str(summary["stale_count"]), "inline": True},
    ]
    if summary.get("fleet_drawdown_24h_pct") is not None and summary["fleet_drawdown_24h_pct"] != 0.0:
        fields.append({
            "name":   "Fleet Drawdown (24h)",
            "value":  f"{summary['fleet_drawdown_24h_pct']:.2f}%",
            "inline": True,
        })
    if summary.get("worst_consec"):
        bot, n = summary["worst_consec"]
        fields.append({"name": "Consecutive Losses", "value": f"{bot}: {n} days", "inline": True})
    if summary.get("red_bots"):
        fields.append({"name": "⚠️ Bots at Risk", "value": ", ".join(summary["red_bots"][:5]), "inline": False})
    if level == "RED":
        fields.append({"name": "ACTION REQUIRED", "value": "Review allocations immediately. Fleet pause may be warranted.", "inline": False})
    if level == "CRITICAL":
        reason_parts = []
        dd24 = summary.get("fleet_drawdown_24h_pct", 0.0)
        if dd24 <= CRITICAL_DRAWDOWN_PCT:
            reason_parts.append(f"24h drawdown {dd24:.2f}% exceeds threshold ({CRITICAL_DRAWDOWN_PCT}%)")
        if summary.get("circuit_breaker_tripped"):
            reason_parts.append("Circuit breaker tripped")
        fields.append({
            "name":   "🔴 CRITICAL TRIGGER",
            "value":  " | ".join(reason_parts) if reason_parts else "Threshold exceeded",
            "inline": False,
        })
        fields.append({
            "name":   "IMMEDIATE ACTION REQUIRED",
            "value":  "Halt all trading activity and review positions immediately.",
            "inline": False,
        })
    return {
        "author":    {"name": "BMG Capital — Dick (Chief Risk Officer)"},
        "title":     titles[level],
        "color":     colors[level],
        "fields":    fields,
        "footer":    {"text": "Dick (CRO) · Tier A autonomous · Every 30 min"},
        "timestamp": now.isoformat(),
    }


def run_risk_health_check(db: Session) -> dict:
    """
    Main entry point — called every 30 min by APScheduler.
    Posts to #risk-alerts on YELLOW or RED. Returns risk dict.
    """
    now = datetime.now(timezone.utc)

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="risk_sentinel")
    except Exception:
        pass

    drawdown      = _get_fleet_drawdown(db)
    streaks       = _get_consecutive_losses(db)
    stale         = _get_stale_bots(db)
    drawdown_24h  = _get_fleet_drawdown_24h(db)

    # Find worst drawdown as percentage of starting capital
    worst_dd_pct = 0.0
    total_pnl_usd = drawdown["total_pnl_usd"]
    if total_pnl_usd < 0:
        # rough estimate: fleet ~$50k starting → %drawdown
        worst_dd_pct = abs(total_pnl_usd) / 50_000 * 100

    worst_consec = max(streaks.items(), key=lambda x: x[1]) if streaks else None
    consec_max   = worst_consec[1] if worst_consec else 0

    red_bots = [b for b, n in streaks.items() if n >= CONSEC_LOSS_WARN]
    level = _classify(
        worst_dd_pct, consec_max, len(stale),
        drawdown_24h_pct=drawdown_24h,
        circuit_breaker_tripped=False,  # populated from bus payload if available
    )

    summary = {
        "level":                  level,
        "total_pnl_usd":          total_pnl_usd,
        "worst_dd_pct":           round(worst_dd_pct, 2),
        "fleet_drawdown_24h_pct": drawdown_24h,
        "stale_count":            len(stale),
        "stale_bots":             stale,
        "worst_consec":           worst_consec,
        "red_bots":               red_bots,
        "circuit_breaker_tripped": False,
    }

    logger.info(
        "[risk_sentinel] level=%s dd=%.1f%% dd_24h=%.2f%% stale=%d consec=%d",
        level, worst_dd_pct, drawdown_24h, len(stale), consec_max,
    )

    # Post to Discord: skip GREEN; YELLOW posts embed only; RED adds @CIO mention;
    # CRITICAL adds @CIO @here mention. All respect the cooldown.
    if level in ("YELLOW", "RED", "CRITICAL"):
        last = _last_alert_ts.get(level)
        if not last or (now - last).total_seconds() > _ALERT_COOLDOWN_HOURS * 3600:
            _last_alert_ts[level] = now
            token, ch = _get_channel()
            cio_id = os.getenv("CIO_DISCORD_USER_ID", "")
            embed = _build_embed(level, summary, now)

            mentions = os.getenv("DISCORD_CIO_MENTIONS", f"<@{cio_id}>" if cio_id else "").strip()
            content = ""
            if level == "RED":
                content = mentions
            elif level == "CRITICAL":
                content = f"{mentions} @here".strip()

            if _post(ch, token, embed, content=content):
                logger.warning("[risk_sentinel] %s alert posted to Discord", level)
            else:
                logger.warning("[risk_sentinel] %s alert — Discord post failed", level)

    # Publish to bus
    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import SENTINEL_HEALTH, SENTINEL_BREACH
        bus_priority = 10 if level == "CRITICAL" else (8 if level == "RED" else 5)
        _bus_publish(db, channel=SENTINEL_HEALTH, from_agent="risk_sentinel",
                     msg_type="health", subject=f"Risk check: {level}",
                     payload=summary, priority=bus_priority)
        if level in ("RED", "CRITICAL"):
            _bus_publish(db, channel=SENTINEL_BREACH, from_agent="risk_sentinel",
                         to_agent="queen", msg_type="breach",
                         subject=f"RISK BREACH: {level}", payload=summary,
                         priority=10 if level == "CRITICAL" else 9)
    except Exception as exc:
        logger.debug("[risk_sentinel] bus publish skipped: %s", exc)

    # Proactive observation: if any metric is within 20% of a threshold, observe
    try:
        from agents.bus import observe as _obs
        fleet_pnl = summary.get("fleet_pnl_30d_pct", 0)
        WARN_THRESHOLD = -0.4  # 80% of the -0.5% alert threshold
        if fleet_pnl <= WARN_THRESHOLD and level == "GREEN":
            _obs(db, agent_id="risk_sentinel",
                 content=f"Fleet P&L approaching threshold: {fleet_pnl:.2f}% (alert at -0.5%). No action needed yet — monitoring.",
                 context={"fleet_pnl_30d_pct": fleet_pnl})
    except Exception:
        pass

    # Daily check-in to #fund-team-chat
    try:
        from agents.bus import post_daily_checkin as _checkin
        dd = abs(summary.get("worst_dd_pct", 0))
        _checkin(db, "risk_sentinel",
                 f"Dick (CRO): Risk check {level} — Fleet 30d P&L ${summary['total_pnl_usd']:+,.0f}, "
                 f"max drawdown {dd:.1f}%, {summary['stale_count']} stale bots. "
                 f"{'No flags raised.' if level == 'GREEN' else 'Elevated — see #risk-alerts.'}")
    except Exception:
        pass

    return summary
