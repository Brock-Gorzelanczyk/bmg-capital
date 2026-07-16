"""Discord webhook notifications.

Two independent channels, two independent kill switches:

  Signals  → discord_signal_webhook_url (bot trade signals)
             Gated by DISCORD_SIGNAL_POSTING_ENABLED (default false — quiet)
             → send_signal(), send_daily_summary()

  Ops      → alert_webhook_url (operational alerts: scheduler stops,
             allocator errors, drawdown breaches, reconciliation mismatches,
             gate breaches, halt-on-swing)
             Gated by DISCORD_OPS_ALERTS_ENABLED (default true — always on)
             → send_ops_alert()

The split exists so silencing signal noise during an incident or post-launch
quiet period DOESN'T also silence the alerts that tell us the platform is
on fire. They are routed to different webhooks and respect different env vars.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Embed colors
_COLOR_BUY  = 0x2EC4A1
_COLOR_SELL = 0xEF4444
_COLOR_HOLD = 0x6B7280
_COLOR_OPS_INFO = 0x3B82F6      # blue
_COLOR_OPS_WARN = 0xF59E0B      # amber
_COLOR_OPS_CRIT = 0xDC2626      # red

BOT_DISPLAY = {
    "stock_swing":          "Stock Swing",
    "stock_day":            "Stock Day",
    "stock_lt":             "Stock Long-Term",
    "crypto_swing":         "Crypto Swing",
    "crypto_day":           "Crypto Day",
    "crypto_lt":            "Crypto Long-Term",
    "options_income":       "Equity Income",
    "options_directional":  "Equity Directional",
}


def _discord_master_kill() -> bool:
    """Master kill switch — silences EVERY Discord post regardless of channel.

    2026-07-16: added because DISCORD_OPS_ALERTS_ENABLED=false only gated
    ops alerts; per-trade signal posts (send_signal, send_daily_summary)
    kept posting. Set DISCORD_ENABLED=false and NOTHING goes to Discord.
    """
    return os.getenv("DISCORD_ENABLED", "true").strip().lower() == "false"


def _webhook_url() -> str:
    if _discord_master_kill():
        return ""
    from app.config import settings
    return settings.discord_signal_webhook_url


def _ops_webhook_url() -> str:
    """Ops alert webhook — distinct from signal webhook so silencing signals
    doesn't also silence ops health."""
    if _discord_master_kill():
        return ""
    from app.config import settings
    return settings.alert_webhook_url


def _ops_alerts_enabled() -> bool:
    """Return True unless explicitly disabled. Defaults to TRUE — operational
    health alerts should always reach the operator. Set
    DISCORD_OPS_ALERTS_ENABLED=false only when intentionally silencing
    everything (e.g. planned maintenance window)."""
    return os.getenv("DISCORD_OPS_ALERTS_ENABLED", "true").strip().lower() != "false"


def send_ops_alert(
    *,
    title: str,
    message: str,
    severity: str = "warn",  # info | warn | critical
    source: Optional[str] = None,
    fields: Optional[list[dict]] = None,
) -> bool:
    """Fire-and-forget operational alert. Routes to the ops webhook, NOT the
    signal webhook, and is gated by DISCORD_OPS_ALERTS_ENABLED (default true).

    Returns True on confirmed 2xx, False otherwise (logged but never raises).
    Callers should NOT depend on return value for control flow — alerting is
    advisory, the underlying condition is the source of truth.

    severity:
      info     — heartbeat / informational ("EOD recon completed cleanly")
      warn     — degraded but not catastrophic ("yfinance 503 storm started")
      critical — needs immediate attention ("EOD P&L swing > $5K, halted")
    """
    if not _ops_alerts_enabled():
        logger.debug("[ops-alert] suppressed (DISCORD_OPS_ALERTS_ENABLED=false): %s", title)
        return False
    url = _ops_webhook_url()
    if not url:
        logger.warning("[ops-alert] no alert_webhook_url configured — alert dropped: %s", title)
        return False
    color = {
        "info": _COLOR_OPS_INFO,
        "warn": _COLOR_OPS_WARN,
        "critical": _COLOR_OPS_CRIT,
    }.get(severity, _COLOR_OPS_WARN)

    embed = {
        "title": f"[{severity.upper()}] {title}",
        "description": message[:1900],  # Discord embed description limit ~2000
        "color": color,
        "footer": {"text": f"BMG Capital · ops · {source or 'unknown'}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = fields[:20]  # Discord embed field limit 25; safety margin

    try:
        with httpx.Client(timeout=5) as client:
            resp = client.post(url, json={"embeds": [embed]})
            if resp.status_code in (200, 204):
                return True
            logger.warning("[ops-alert] webhook returned %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        logger.warning("[ops-alert] webhook failed: %s", exc)
        return False


def send_signal(
    *,
    bot: str,
    symbol: str,
    side: str,           # buy | sell | hold
    strategy: str,
    reason: str,
    confidence: float,   # 0–1
    price: Optional[float] = None,
    size_pct: Optional[float] = None,
) -> None:
    """Fire-and-forget Discord embed. Silently no-ops if webhook not configured."""
    url = _webhook_url()
    if not url:
        return

    color = _COLOR_BUY if side == "buy" else (_COLOR_SELL if side == "sell" else _COLOR_HOLD)
    side_label = side.upper()
    bot_name = BOT_DISPLAY.get(bot, bot)
    conf_pct = round(confidence * 100, 1)

    fields = [
        {"name": "Strategy",    "value": strategy,          "inline": True},
        {"name": "Confidence",  "value": f"{conf_pct}%",    "inline": True},
    ]
    if price is not None:
        fields.append({"name": "Price", "value": f"${price:,.2f}", "inline": True})
    if size_pct is not None:
        fields.append({"name": "Size",  "value": f"{size_pct:.1f}%", "inline": True})

    payload = {
        "embeds": [{
            "title": f"{side_label} — {bot_name} fired on {symbol}",
            "description": reason or "No reason provided.",
            "color": color,
            "fields": fields,
            "footer": {"text": "BMG Capital · Paper Trading"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }

    try:
        with httpx.Client(timeout=5) as client:
            resp = client.post(url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning("Discord webhook returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Discord signal notification failed: %s", exc)


def send_daily_summary(
    *,
    total_signals: int,
    by_bot: dict[str, int],
    top_symbols: list[str],
    realized_pnl_cents: int,
) -> None:
    """Send a daily summary embed. Silently no-ops if webhook not configured."""
    url = _webhook_url()
    if not url:
        return

    pnl_usd = realized_pnl_cents / 100
    pnl_pos = pnl_usd >= 0
    color = _COLOR_BUY if pnl_pos else _COLOR_SELL

    bot_lines = "\n".join(
        f"• {BOT_DISPLAY.get(k, k)}: **{v}** signals"
        for k, v in sorted(by_bot.items(), key=lambda x: -x[1])
    ) or "No signals today."

    payload = {
        "embeds": [{
            "title": "Daily Bot Summary",
            "color": color,
            "fields": [
                {"name": "Total Signals",   "value": str(total_signals),                     "inline": True},
                {"name": "Realized P&L",    "value": f"{'+'if pnl_pos else ''}{pnl_usd:,.2f}", "inline": True},
                {"name": "Top Symbols",     "value": ", ".join(top_symbols[:5]) or "—",      "inline": True},
                {"name": "By Bot",          "value": bot_lines,                              "inline": False},
            ],
            "footer": {"text": "BMG Capital · Paper Trading"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }

    try:
        with httpx.Client(timeout=5) as client:
            resp = client.post(url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning("Discord daily summary returned %s", resp.status_code)
    except Exception as exc:
        logger.warning("Discord daily summary failed: %s", exc)
