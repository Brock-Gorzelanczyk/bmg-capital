"""
Public Discord signal feed — posts every accepted bot signal to the public
BMG Capital Discord server using the bot token + channel IDs.

Channel routing:
  all-signals  ← every bot
  stocks       ← stock_swing | stock_day | stock_lt
  crypto       ← crypto_swing | crypto_day | crypto_lt | crypto_onchain
  options      ← options_income | options_directional
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_COLOR_BUY       = 0x2EC4A1
_COLOR_SELL      = 0xEF4444
_COLOR_REBALANCE = 0xF59E0B

BOT_DISPLAY = {
    "stock_swing":          "Stock Swing",
    "stock_day":            "Stock Day",
    "stock_lt":             "Stock Long-Term",
    "crypto_swing":         "Crypto Swing",
    "crypto_day":           "Crypto Day",
    "crypto_lt":            "Crypto Long-Term",
    "crypto_onchain":       "Crypto On-Chain",
    "options_income":       "Options Income",
    "options_directional":  "Options Directional",
}

_STOCKS_BOTS  = {"stock_swing", "stock_day", "stock_lt"}
_CRYPTO_BOTS  = {"crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain"}
_OPTIONS_BOTS = {"options_income", "options_directional"}


def _cfg():
    from app.config import settings
    return settings


def _channel_ids_for_bot(bot_name: str) -> list[str]:
    cfg = _cfg()
    channels = []
    if cfg.discord_channel_all_signals:
        channels.append(cfg.discord_channel_all_signals)
    if bot_name in _STOCKS_BOTS and cfg.discord_channel_stocks:
        channels.append(cfg.discord_channel_stocks)
    if bot_name in _CRYPTO_BOTS and cfg.discord_channel_crypto:
        channels.append(cfg.discord_channel_crypto)
    if bot_name in _OPTIONS_BOTS and cfg.discord_channel_options:
        channels.append(cfg.discord_channel_options)
    return list(dict.fromkeys(channels))  # dedup, preserve order


def _build_embed(signal: dict) -> dict:
    bot = signal.get("bot", "")
    symbol = signal.get("symbol", "")
    side = (signal.get("side") or "").upper()
    arrow = "🟢" if side == "BUY" else ("🔴" if side == "SELL" else "🟡")
    color = _COLOR_BUY if side == "BUY" else (_COLOR_SELL if side == "SELL" else _COLOR_REBALANCE)
    bot_name = BOT_DISPLAY.get(bot, bot)
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)

    fields = [
        {"name": "Strategy",   "value": signal.get("strategy") or "—",     "inline": True},
        {"name": "Confidence", "value": f"{conf_pct}%",                    "inline": True},
    ]
    if signal.get("size_pct") is not None:
        fields.append({"name": "Size",   "value": f"{signal['size_pct']:.1f}%",    "inline": True})
    if signal.get("price") is not None:
        fields.append({"name": "Price",  "value": f"${signal['price']:,.2f}",      "inline": True})
    if signal.get("stop"):
        fields.append({"name": "Stop",   "value": f"${signal['stop']:,.2f}",       "inline": True})
    if signal.get("target"):
        fields.append({"name": "Target", "value": f"${signal['target']:,.2f}",     "inline": True})

    return {
        "author": {"name": "BMG Capital — Paper Trading"},
        "title": f"{arrow} {bot_name} {side} {symbol}",
        "description": (signal.get("reason") or "")[:2000],
        "color": color,
        "fields": fields,
        "footer": {"text": "Paper only · Not investment advice · bmgcapital.com"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _post_to_channel(channel_id: str, embed: dict, token: str) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    with httpx.Client(timeout=8) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"embeds": [embed]},
        )
        if resp.status_code == 429:
            logger.warning("Discord rate limited on channel %s", channel_id)
        elif not resp.is_success:
            logger.warning("Discord post failed channel=%s status=%s: %s",
                           channel_id, resp.status_code, resp.text[:200])


def post_signal(signal: dict) -> None:
    """Post signal to all relevant public channels. Fire-and-forget."""
    cfg = _cfg()
    if not cfg.discord_bot_token:
        return

    bot_name = signal.get("bot", "")
    channel_ids = _channel_ids_for_bot(bot_name)
    if not channel_ids:
        return

    embed = _build_embed(signal)
    for cid in channel_ids:
        try:
            _post_to_channel(cid, embed, cfg.discord_bot_token)
        except Exception as exc:
            logger.debug("public discord post skipped channel=%s: %s", cid, exc)


def post_daily_digest(digest: dict) -> None:
    """Post the daily recap embed to #daily-digest."""
    cfg = _cfg()
    if not cfg.discord_bot_token or not cfg.discord_channel_daily_digest:
        return

    pnl = digest.get("realized_pnl_cents", 0) / 100
    pnl_pos = pnl >= 0
    signals = digest.get("total_signals", 0)
    top_syms = ", ".join(digest.get("top_symbols", [])[:5]) or "—"

    bot_lines = "\n".join(
        f"• {BOT_DISPLAY.get(k, k)}: **{v}** signals"
        for k, v in sorted((digest.get("by_bot") or {}).items(), key=lambda x: -x[1])
    ) or "No signals today."

    embed = {
        "title": "📊 Daily Bot Digest",
        "color": _COLOR_BUY if pnl_pos else _COLOR_SELL,
        "fields": [
            {"name": "Total Signals",   "value": str(signals),                              "inline": True},
            {"name": "Realized P&L",   "value": f"{'+'if pnl_pos else ''}{pnl:,.2f}",      "inline": True},
            {"name": "Top Symbols",     "value": top_syms,                                  "inline": True},
            {"name": "By Bot",          "value": bot_lines,                                 "inline": False},
        ],
        "footer": {"text": "Paper only · Not investment advice · bmgcapital.com"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _post_to_channel(cfg.discord_channel_daily_digest, embed, cfg.discord_bot_token)
    except Exception as exc:
        logger.warning("daily digest Discord post failed: %s", exc)


def post_weekly_leaderboard(leaderboard: list[dict]) -> None:
    """Post weekly leaderboard to #weekly-leaderboard."""
    cfg = _cfg()
    if not cfg.discord_bot_token or not cfg.discord_channel_weekly_leaderboard:
        return

    rows = []
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(leaderboard[:8]):
        medal = medals[i] if i < 3 else f"{i+1}."
        ret = entry.get("return_30d_pct", 0)
        sign = "+" if ret >= 0 else ""
        rows.append(f"{medal} **{BOT_DISPLAY.get(entry['profile'], entry['profile'])}** — {sign}{ret:.2f}%")

    embed = {
        "title": "🏆 Weekly Bot Leaderboard",
        "description": "\n".join(rows) or "No data yet.",
        "color": _COLOR_BUY,
        "footer": {"text": "Paper only · Not investment advice · bmgcapital.com"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _post_to_channel(cfg.discord_channel_weekly_leaderboard, embed, cfg.discord_bot_token)
    except Exception as exc:
        logger.warning("weekly leaderboard Discord post failed: %s", exc)
