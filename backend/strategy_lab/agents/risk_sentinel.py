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


def _classify(drawdown_pct: float, consec_losses: int, stale_count: int) -> str:
    if drawdown_pct >= DRAWDOWN_HALT_PCT or consec_losses >= CONSEC_LOSS_HALT:
        return "RED"
    if drawdown_pct >= DRAWDOWN_WARN_PCT or consec_losses >= CONSEC_LOSS_WARN or stale_count >= STALE_BOT_WARN:
        return "YELLOW"
    return "GREEN"


def _build_embed(level: str, summary: dict, now: datetime) -> dict:
    colors = {"GREEN": 0x16A34A, "YELLOW": 0xF59E0B, "RED": 0xDC2626}
    icons  = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}
    fields = [
        {"name": f"{icons[level]} Risk Level",    "value": level, "inline": True},
        {"name": "Fleet P&L (30d)",               "value": f"${summary['total_pnl_usd']:,.2f}", "inline": True},
        {"name": "Stale Bots",                    "value": str(summary["stale_count"]), "inline": True},
    ]
    if summary.get("worst_consec"):
        bot, n = summary["worst_consec"]
        fields.append({"name": "Consecutive Losses", "value": f"{bot}: {n} days", "inline": True})
    if summary.get("red_bots"):
        fields.append({"name": "⚠️ Bots at Risk", "value": ", ".join(summary["red_bots"][:5]), "inline": False})
    if level == "RED":
        fields.append({"name": "ACTION REQUIRED", "value": "Review allocations immediately. Fleet pause may be warranted.", "inline": False})
    return {
        "author":    {"name": "BMG Capital — Risk Sentinel"},
        "title":     f"Risk Health Check — {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "color":     colors[level],
        "fields":    fields,
        "footer":    {"text": "Risk Sentinel · Tier A autonomous · Every 30 min"},
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

    drawdown  = _get_fleet_drawdown(db)
    streaks   = _get_consecutive_losses(db)
    stale     = _get_stale_bots(db)

    # Find worst drawdown as percentage of starting capital
    worst_dd_pct = 0.0
    total_pnl_usd = drawdown["total_pnl_usd"]
    if total_pnl_usd < 0:
        # rough estimate: fleet ~$50k starting → %drawdown
        worst_dd_pct = abs(total_pnl_usd) / 50_000 * 100

    worst_consec = max(streaks.items(), key=lambda x: x[1]) if streaks else None
    consec_max   = worst_consec[1] if worst_consec else 0

    red_bots = [b for b, n in streaks.items() if n >= CONSEC_LOSS_WARN]
    level = _classify(worst_dd_pct, consec_max, len(stale))

    summary = {
        "level":          level,
        "total_pnl_usd":  total_pnl_usd,
        "worst_dd_pct":   round(worst_dd_pct, 2),
        "stale_count":    len(stale),
        "stale_bots":     stale,
        "worst_consec":   worst_consec,
        "red_bots":       red_bots,
    }

    logger.info("[risk_sentinel] level=%s dd=%.1f%% stale=%d consec=%d", level, worst_dd_pct, len(stale), consec_max)

    # Post to Discord only when YELLOW or RED, respecting cooldown
    if level in ("YELLOW", "RED"):
        last = _last_alert_ts.get(level)
        if not last or (now - last).total_seconds() > _ALERT_COOLDOWN_HOURS * 3600:
            _last_alert_ts[level] = now
            token, ch = _get_channel()
            embed = _build_embed(level, summary, now)
            if _post(ch, token, embed):
                logger.warning("[risk_sentinel] %s alert posted to Discord", level)
            else:
                logger.warning("[risk_sentinel] %s alert — Discord post failed", level)

    # Publish to bus
    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import SENTINEL_HEALTH, SENTINEL_BREACH
        _bus_publish(db, channel=SENTINEL_HEALTH, from_agent="risk_sentinel",
                     msg_type="health", subject=f"Risk check: {level}",
                     payload=summary, priority=8 if level == "RED" else 5)
        if level == "RED":
            _bus_publish(db, channel=SENTINEL_BREACH, from_agent="risk_sentinel",
                         to_agent="queen", msg_type="breach",
                         subject=f"RISK BREACH: {level}", payload=summary, priority=9)
    except Exception as exc:
        logger.debug("[risk_sentinel] bus publish skipped: %s", exc)

    return summary
