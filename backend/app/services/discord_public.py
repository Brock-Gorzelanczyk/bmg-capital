"""
Public Discord signal feed — posts every accepted bot signal to the public
BMG Capital Discord server using the bot token + channel IDs.

Channel routing:
  all-signals  ← every bot
  stocks       ← stock_swing | stock_day | stock_lt
  crypto       ← crypto_swing | crypto_day | crypto_lt | crypto_onchain
  options      ← options_income | options_directional

Env vars (DISCORD_CH_* names match Railway config):
  DISCORD_BOT_TOKEN
  DISCORD_CH_ALL_SIGNALS, DISCORD_CH_STOCKS_SIGNALS,
  DISCORD_CH_CRYPTO_SIGNALS, DISCORD_CH_OPTIONS_SIGNALS
  DISCORD_CH_DAILY_DIGEST, DISCORD_CH_WEEKLY_LEADERBOARD,
  DISCORD_CH_MONTHLY_RECAP
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COMPLIANCE_FOOTER = "Paper trading. Not investment advice. Not a registered investment adviser."

_COLOR_BUY       = 0x2EC4A1
_COLOR_SELL      = 0xE5484D
_COLOR_REBALANCE = 0xF59E0B

BOT_DISPLAY = {
    "stock_swing":               "Stock Swing",
    "stock_day":                 "Stock Day",
    "stock_lt":                  "Stock Long-Term",
    "crypto_swing":              "Crypto Swing",
    "crypto_day":                "Crypto Day",
    "crypto_lt":                 "Crypto Long-Term",
    "crypto_onchain":            "Crypto On-Chain",
    "crypto_quant_aggressive":   "Crypto Quant Aggressive",
    "options_income":            "Options Income",
    "options_directional":       "Options Directional",
}

_STOCKS_BOTS  = {"stock_swing", "stock_day", "stock_lt"}
_CRYPTO_BOTS  = {"crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain", "crypto_quant_aggressive"}
_OPTIONS_BOTS = {"options_income", "options_directional"}


def _cfg():
    from app.config import settings
    return settings


def _channel_ids_for_bot(bot_name: str) -> list[str]:
    """Return ordered, deduped list of channel IDs for this bot."""
    cfg = _cfg()
    # Prefer new DISCORD_CH_* names, fall back to legacy DISCORD_CHANNEL_* names.
    ch_all     = cfg.discord_ch_all_signals     or cfg.discord_channel_all_signals
    ch_stocks  = cfg.discord_ch_stocks_signals  or cfg.discord_channel_stocks
    ch_crypto  = cfg.discord_ch_crypto_signals  or cfg.discord_channel_crypto
    ch_options = cfg.discord_ch_options_signals or cfg.discord_channel_options

    channels = []
    if ch_all:                              channels.append(ch_all)
    if bot_name in _STOCKS_BOTS  and ch_stocks:  channels.append(ch_stocks)
    if bot_name in _CRYPTO_BOTS  and ch_crypto:  channels.append(ch_crypto)
    if bot_name in _OPTIONS_BOTS and ch_options: channels.append(ch_options)
    return list(dict.fromkeys(channels))


def _build_signal_embed(signal: dict) -> dict:
    bot    = signal.get("bot", "")
    symbol = signal.get("symbol", "")
    side   = (signal.get("side") or "").upper()
    arrow  = "🟢" if side == "BUY" else ("🔴" if side == "SELL" else "🟡")
    color  = _COLOR_BUY if side == "BUY" else (_COLOR_SELL if side == "SELL" else _COLOR_REBALANCE)
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)

    fields = [
        {"name": "Strategy",   "value": signal.get("strategy") or "—", "inline": True},
        {"name": "Confidence", "value": f"{conf_pct}%",                "inline": True},
    ]
    if signal.get("size_pct") is not None:
        fields.append({"name": "Size",   "value": f"{signal['size_pct']:.1f}%",   "inline": True})
    if signal.get("price") is not None:
        fields.append({"name": "Entry",  "value": f"${signal['price']:,.2f}",     "inline": True})
    if signal.get("stop") is not None:
        fields.append({"name": "Stop",   "value": f"${signal['stop']:,.2f}",      "inline": True})
    if signal.get("target") is not None:
        fields.append({"name": "Target", "value": f"${signal['target']:,.2f}",    "inline": True})

    return {
        "author": {"name": f"{BOT_DISPLAY.get(bot, bot)} bot"},
        "title":  f"{arrow} {side} {symbol}",
        "description": (signal.get("reason") or "")[:2000],
        "color":  color,
        "fields": fields,
        "footer": {"text": COMPLIANCE_FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _post_to_channel(channel_id: str, embed: dict, token: str) -> Optional[str]:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    with httpx.Client(timeout=8) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"embeds": [embed]},
        )
        if resp.status_code == 429:
            logger.warning("Discord rate limited on channel %s", channel_id)
            return None
        elif not resp.is_success:
            logger.warning("Discord post failed channel=%s status=%s: %s",
                           channel_id, resp.status_code, resp.text[:200])
            return None
        try:
            return str(resp.json().get("id", ""))
        except Exception:
            return None


def post_signal(signal: dict, db=None, signal_id: Optional[int] = None) -> None:
    """Post signal embed to all relevant channels.

    If `db` and `signal_id` are provided, sets discord_posted_at on the
    bot_signals row after posting (deduplication guard for the Node.js worker).
    """
    cfg = _cfg()
    if not cfg.discord_bot_token:
        return

    # Skip if the Node.js worker already posted this signal.
    if db is not None and signal_id is not None:
        from app.db.models.bots import BotSignal
        row = db.get(BotSignal, signal_id)
        if row and row.discord_posted_at is not None:
            return

    bot_name    = signal.get("bot", "")
    channel_ids = _channel_ids_for_bot(bot_name)
    if not channel_ids:
        return

    embed = _build_signal_embed(signal)
    message_id: Optional[str] = None
    posted = False
    for cid in channel_ids:
        try:
            mid = _post_to_channel(cid, embed, cfg.discord_bot_token)
            if mid and not message_id:
                message_id = mid
            posted = True
        except Exception as exc:
            logger.debug("discord signal post skipped channel=%s: %s", cid, exc)

    # Mark as posted + store message_id so the Node.js worker won't double-post.
    if posted and db is not None and signal_id is not None:
        try:
            from app.db.models.bots import BotSignal
            row = db.get(BotSignal, signal_id)
            if row:
                row.discord_posted_at = datetime.now(timezone.utc)
                if message_id:
                    row.discord_message_id = message_id
                db.commit()
        except Exception as exc:
            logger.debug("discord_posted_at update failed: %s", exc)


def post_daily_digest(digest: dict) -> None:
    """Post the daily recap embed to #daily-digest."""
    cfg = _cfg()
    channel_id = cfg.discord_ch_daily_digest or cfg.discord_channel_daily_digest
    if not cfg.discord_bot_token or not channel_id:
        return

    pnl     = digest.get("realized_pnl_cents", 0) / 100
    pnl_pos = pnl >= 0
    signals  = digest.get("total_signals", 0)
    top_syms = ", ".join(digest.get("top_symbols", [])[:5]) or "—"

    bot_lines = "\n".join(
        f"• {BOT_DISPLAY.get(k, k)}: **{v}** signals"
        for k, v in sorted((digest.get("by_bot") or {}).items(), key=lambda x: -x[1])
    ) or "No signals today."

    embed = {
        "title": "📊 Daily Bot Digest",
        "color": _COLOR_BUY if pnl_pos else _COLOR_SELL,
        "fields": [
            {"name": "Total Signals", "value": str(signals),                              "inline": True},
            {"name": "Realized P&L",  "value": f"{'+'if pnl_pos else ''}{pnl:,.2f}",    "inline": True},
            {"name": "Top Symbols",   "value": top_syms,                                  "inline": True},
            {"name": "By Bot",        "value": bot_lines,                                 "inline": False},
        ],
        "footer": {"text": COMPLIANCE_FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _post_to_channel(channel_id, embed, cfg.discord_bot_token)
    except Exception as exc:
        logger.warning("daily digest Discord post failed: %s", exc)


def post_weekly_leaderboard(leaderboard: list[dict]) -> None:
    """Post weekly leaderboard to #weekly-leaderboard."""
    cfg = _cfg()
    channel_id = cfg.discord_ch_weekly_leaderboard or cfg.discord_channel_weekly_leaderboard
    if not cfg.discord_bot_token or not channel_id:
        return

    medals = ["🥇", "🥈", "🥉"]
    rows = []
    for i, entry in enumerate(leaderboard[:8]):
        medal = medals[i] if i < 3 else f"{i+1}."
        ret   = entry.get("return_30d_pct", 0)
        sign  = "+" if ret >= 0 else ""
        rows.append(f"{medal} **{BOT_DISPLAY.get(entry['profile'], entry['profile'])}** — {sign}{ret:.2f}%")

    embed = {
        "title":       "🏆 Weekly Bot Leaderboard",
        "description": "\n".join(rows) or "No data yet.",
        "color":       _COLOR_BUY,
        "footer":      {"text": COMPLIANCE_FOOTER},
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }
    try:
        _post_to_channel(channel_id, embed, cfg.discord_bot_token)
    except Exception as exc:
        logger.warning("weekly leaderboard Discord post failed: %s", exc)


def post_first_live_signal_announcement(bot_name: str, strategy: str, symbol: str) -> None:
    """One-shot plain-text alert to #announcements: first real crypto signal fired."""
    cfg = _cfg()
    channel_id = cfg.discord_ch_announcements
    if not cfg.discord_bot_token or not channel_id:
        logger.info(
            "first_live_signal_announcement: no token/channel configured — would have posted "
            "bot=%s strategy=%s symbol=%s", bot_name, strategy, symbol,
        )
        return

    display = BOT_DISPLAY.get(bot_name, bot_name)
    content = (
        f"🎉 First live strategy signal fired! **{display}** · {strategy} · {symbol}. "
        f"Real-time validation has begun. From here, every signal will post to "
        f"#crypto-signals automatically."
    )
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    try:
        with httpx.Client(timeout=8) as http:
            resp = http.post(
                url,
                headers={"Authorization": f"Bot {cfg.discord_bot_token}", "Content-Type": "application/json"},
                json={"content": content},
            )
            if resp.is_success:
                logger.info("first_live_signal_announcement posted to #announcements")
            else:
                logger.warning(
                    "first_live_signal_announcement failed: status=%s body=%s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        logger.warning("first_live_signal_announcement HTTP error: %s", exc)


def post_monthly_recap(summary: dict) -> None:
    """Post the monthly recap embed to #monthly-recap."""
    cfg = _cfg()
    channel_id = cfg.discord_ch_monthly_recap or cfg.discord_channel_monthly_recap
    if not cfg.discord_bot_token or not channel_id:
        return

    pnl     = summary.get("pnl_cents", 0) / 100
    pnl_pos = pnl >= 0
    month   = summary.get("month_name", "")

    embed = {
        "title": f"📊 {month} — Monthly Recap",
        "description": "Here's the month in numbers across the paper-trading bots.",
        "color": _COLOR_BUY if pnl_pos else _COLOR_SELL,
        "fields": [
            {"name": "Signals fired",   "value": str(summary.get("signals", 0)),  "inline": True},
            {"name": "Trades executed", "value": str(summary.get("trades", 0)),   "inline": True},
            {"name": "Net P&L",         "value": f"{'+'if pnl_pos else ''}{pnl:,.2f}", "inline": True},
        ],
        "footer":    {"text": COMPLIANCE_FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _post_to_channel(channel_id, embed, cfg.discord_bot_token)
    except Exception as exc:
        logger.warning("monthly recap Discord post failed: %s", exc)
