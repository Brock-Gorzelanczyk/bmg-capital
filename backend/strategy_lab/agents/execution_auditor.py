"""
Execution Auditor — Deploy 2 Tier A autonomous fill quality monitor.

Analyzes slippage, fill rates, and execution quality from bot_trades.
Runs daily at 5 PM ET after market close — Mon-Fri.
Posts to #bmg-monitoring when slippage thresholds exceeded.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Slippage thresholds (basis points: 100 bps = 1%)
SLIPPAGE_WARN_BPS   = 50    # YELLOW if avg slippage > 50 bps
SLIPPAGE_ALERT_BPS  = 150   # RED if avg slippage > 150 bps
MIN_TRADES_TO_AUDIT = 3     # Skip alert if fewer trades than this


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
        logger.warning("[exec_auditor] Discord post failed: %s", exc)
        return False


def _get_today_trades(db: Session) -> list[dict]:
    """Fetch today's bot_trades with slippage data and bot names."""
    try:
        today = date.today().isoformat()
        rows = db.execute(text("""
            SELECT bp.name, bt.symbol, bt.side, bt.qty,
                   bt.fill_price_cents, bt.expected_fill_cents,
                   bt.slippage_bps, bt.fees_cents, bt.ts
            FROM bot_trades bt
            JOIN bot_allocations ba ON ba.id = bt.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE DATE(bt.ts) = :today
              AND bt.quarantined_at IS NULL
            ORDER BY bt.ts DESC
        """), {"today": today}).fetchall()

        return [
            {
                "bot": r[0], "symbol": r[1], "side": r[2],
                "qty": r[3], "fill_price_cents": r[4],
                "expected_fill_cents": r[5], "slippage_bps": r[6],
                "fees_cents": r[7], "ts": str(r[8]),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[exec_auditor] trade query failed: %s", exc)
        return []


def _compute_slippage_stats(trades: list[dict]) -> dict:
    """Compute per-bot and fleet-level slippage statistics."""
    slippage_vals = [t["slippage_bps"] for t in trades if t["slippage_bps"] is not None]
    fees_total = sum(t["fees_cents"] or 0 for t in trades)

    by_bot: dict[str, list[float]] = {}
    for t in trades:
        if t["slippage_bps"] is not None:
            by_bot.setdefault(t["bot"], []).append(t["slippage_bps"])

    bot_avg: dict[str, float] = {
        bot: round(sum(vals) / len(vals), 1)
        for bot, vals in by_bot.items()
    }

    worst_bot = max(bot_avg.items(), key=lambda x: x[1]) if bot_avg else None

    return {
        "trade_count":   len(trades),
        "slippage_count": len(slippage_vals),
        "avg_slippage_bps": round(sum(slippage_vals) / len(slippage_vals), 1) if slippage_vals else None,
        "max_slippage_bps": round(max(slippage_vals), 1) if slippage_vals else None,
        "fees_usd": round(fees_total / 100, 2),
        "bot_avg_slippage": bot_avg,
        "worst_bot": worst_bot,
    }


def _classify(stats: dict) -> str:
    avg = stats.get("avg_slippage_bps")
    if avg is None or stats["trade_count"] < MIN_TRADES_TO_AUDIT:
        return "GREEN"
    if avg >= SLIPPAGE_ALERT_BPS:
        return "RED"
    if avg >= SLIPPAGE_WARN_BPS:
        return "YELLOW"
    return "GREEN"


def run_execution_audit(db: Session) -> dict:
    """
    Main entry point — called daily at 5 PM ET by APScheduler.
    Posts to #bmg-monitoring when slippage thresholds exceeded.
    """
    now = datetime.now(timezone.utc)

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="execution_auditor")
    except Exception:
        pass

    trades = _get_today_trades(db)
    stats = _compute_slippage_stats(trades)
    level = _classify(stats)

    result = {
        "ok":         level == "GREEN",
        "level":      level,
        "stats":      stats,
        "audited_at": now.isoformat(),
    }

    logger.info(
        "[exec_auditor] level=%s trades=%d avg_slippage=%.1f bps fees=$%.2f",
        level, stats["trade_count"],
        stats["avg_slippage_bps"] or 0.0, stats["fees_usd"],
    )

    if level in ("YELLOW", "RED"):
        colors = {"YELLOW": 0xF59E0B, "RED": 0xDC2626}
        icons  = {"YELLOW": "⚠️",     "RED": "🚨"}
        fields = [
            {"name": f"{icons[level]} Fill Quality", "value": level, "inline": True},
            {"name": "Trades Audited",               "value": str(stats["trade_count"]), "inline": True},
            {"name": "Avg Slippage",                 "value": f"{stats['avg_slippage_bps']:.1f} bps", "inline": True},
            {"name": "Max Slippage",                 "value": f"{stats['max_slippage_bps']:.1f} bps" if stats["max_slippage_bps"] else "N/A", "inline": True},
            {"name": "Total Fees",                   "value": f"${stats['fees_usd']:.2f}", "inline": True},
        ]
        if stats.get("worst_bot"):
            bot, bps = stats["worst_bot"]
            fields.append({"name": "Worst Bot", "value": f"{bot}: {bps:.1f} bps", "inline": True})

        embed = {
            "author":    {"name": "BMG Capital — Execution Auditor"},
            "title":     f"Execution Quality Alert — {now.strftime('%Y-%m-%d')}",
            "color":     colors[level],
            "fields":    fields,
            "footer":    {"text": "Execution Auditor · Tier A · Daily 5 PM ET"},
            "timestamp": now.isoformat(),
        }
        token, ch = _get_channel()
        if ch and _post(ch, token, embed):
            logger.warning("[exec_auditor] %s alert posted to Discord", level)

    # Publish to bus
    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import EXEC_AUDIT
        _bus_publish(
            db, channel=EXEC_AUDIT, from_agent="execution_auditor",
            msg_type="audit_result",
            subject=f"Execution audit: {level} — {stats['trade_count']} trades",
            payload=result, priority=7 if level == "RED" else 4,
        )
    except Exception as exc:
        logger.debug("[exec_auditor] bus publish skipped: %s", exc)

    return result
