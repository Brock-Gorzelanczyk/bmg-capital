"""Discord webhook notifications for bot signals."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Embed colors
_COLOR_BUY  = 0x2EC4A1
_COLOR_SELL = 0xEF4444
_COLOR_HOLD = 0x6B7280

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


def _webhook_url() -> str:
    from app.config import settings
    return settings.discord_signal_webhook_url


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
