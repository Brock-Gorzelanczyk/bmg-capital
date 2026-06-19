"""
Public Discord signal feed — posts every accepted bot signal to the public
BMG Capital Discord server using the bot token + channel IDs.

Channel routing:
  all-signals  ← every bot
  stocks       ← stock_swing | stock_day | stock_lt
  crypto       ← crypto_swing | crypto_day | crypto_lt | crypto_onchain
  options      ← options_income | options_directional
  quant        ← crypto_quant_aggressive (dedicated channel, not crypto)

Env vars (DISCORD_CH_* names match Railway config):
  DISCORD_BOT_TOKEN
  DISCORD_CH_ALL_SIGNALS, DISCORD_CH_STOCKS_SIGNALS,
  DISCORD_CH_CRYPTO_SIGNALS, DISCORD_CH_OPTIONS_SIGNALS,
  DISCORD_CH_QUANT_SIGNALS (BMG_QUANT_SIGNALS_CHANNEL_ID)
  DISCORD_CH_DAILY_DIGEST, DISCORD_CH_WEEKLY_LEADERBOARD,
  DISCORD_CH_MONTHLY_RECAP
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_channel_log_done = False


def _log_channel_config() -> None:
    """Log resolved Discord channel IDs once at startup for env-var diagnosis."""
    global _channel_log_done
    if _channel_log_done:
        return
    _channel_log_done = True
    cfg = _cfg()
    ch_all     = cfg.discord_ch_all_signals     or cfg.discord_channel_all_signals
    ch_stocks  = cfg.discord_ch_stocks_signals  or cfg.discord_channel_stocks
    ch_crypto  = cfg.discord_ch_crypto_signals  or cfg.discord_channel_crypto
    ch_options = cfg.discord_ch_options_signals or cfg.discord_channel_options
    ch_quant   = cfg.discord_ch_quant_signals   or os.getenv("BMG_QUANT_SIGNALS_CHANNEL_ID", "")
    logger.warning(
        "[discord-channels] all=%s stocks=%s crypto=%s options=%s quant=%s",
        ch_all or "MISSING", ch_stocks or "MISSING", ch_crypto or "MISSING",
        ch_options or "MISSING", ch_quant or "MISSING",
    )
    # Per-bot routing map — any MISSING line means that bot's signals will only hit #all-signals
    routing = [
        ("stock_day",                   ch_stocks,  "DISCORD_CH_STOCKS_SIGNALS"),
        ("stock_swing",                 ch_stocks,  "DISCORD_CH_STOCKS_SIGNALS"),
        ("stock_lt",                    ch_stocks,  "DISCORD_CH_STOCKS_SIGNALS"),
        ("options_directional",         ch_options, "DISCORD_CH_OPTIONS_SIGNALS"),
        ("options_income",              ch_options, "DISCORD_CH_OPTIONS_SIGNALS"),
        ("crypto_day",                  ch_crypto,  "DISCORD_CH_CRYPTO_SIGNALS"),
        ("crypto_swing",                ch_crypto,  "DISCORD_CH_CRYPTO_SIGNALS"),
        ("crypto_lt",                   ch_crypto,  "DISCORD_CH_CRYPTO_SIGNALS"),
        ("crypto_onchain",              ch_crypto,  "DISCORD_CH_CRYPTO_SIGNALS"),
        ("crypto_quant_scalper",        ch_quant,   "DISCORD_CH_QUANT_SIGNALS"),
        ("crypto_quant_aggressive",     ch_quant,   "DISCORD_CH_QUANT_SIGNALS"),
        ("crypto_quant_mean_reversion", ch_quant,   "DISCORD_CH_QUANT_SIGNALS"),
    ]
    logger.warning("[discord-routing-map]")
    for bot, ch, env_name in routing:
        logger.warning("  %-32s → %s  (%s)", bot, ch or "MISSING", env_name)

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
    "crypto_quant_aggressive":      "Crypto Quant Aggressive",
    "crypto_quant_scalper":         "Crypto Quant Scalper",
    "crypto_quant_mean_reversion":  "Crypto Quant Mean Reversion",
    "options_income":               "Options Income",
    "options_directional":          "Options Directional",
}

_STOCKS_BOTS  = {"stock_swing", "stock_day", "stock_lt"}
_CRYPTO_BOTS  = {"crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain"}
_OPTIONS_BOTS = {"options_income", "options_directional"}
_QUANT_BOTS   = {"crypto_quant_aggressive", "crypto_quant_scalper", "crypto_quant_mean_reversion"}


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
    ch_quant   = cfg.discord_ch_quant_signals or os.getenv("BMG_QUANT_SIGNALS_CHANNEL_ID", "")

    if bot_name in _QUANT_BOTS and not ch_quant:
        logger.warning(
            "BMG_QUANT_SIGNALS_CHANNEL_ID not set — "
            "Crypto Quant Aggressive signals will not post to Discord"
        )

    channels = []
    if ch_all:                                           channels.append(ch_all)
    if bot_name in _STOCKS_BOTS  and ch_stocks:         channels.append(ch_stocks)
    if bot_name in _CRYPTO_BOTS  and ch_crypto:         channels.append(ch_crypto)
    if bot_name in _OPTIONS_BOTS and ch_options:        channels.append(ch_options)
    if bot_name in _QUANT_BOTS   and ch_quant:          channels.append(ch_quant)
    return list(dict.fromkeys(channels))


def _fmt_price(price: float) -> str:
    abs_p = abs(price)
    if abs_p >= 1000: return f"${price:,.2f}"
    if abs_p >= 1:    return f"${price:.4f}"
    if abs_p >= 0.01: return f"${price:.5f}"
    return f"${price:.8f}"


def _fmt_qty(qty: float, symbol: str) -> str:
    base = symbol.split("/")[0] if "/" in symbol else symbol
    abs_q = abs(qty)
    if abs_q >= 100_000: return f"{qty:.0f} {base}"
    if abs_q >= 100:     return f"{qty:.2f} {base}"
    if abs_q >= 1:       return f"{qty:.4f} {base}"
    return f"{qty:.8f} {base}"


def _build_scout_embed(signal: dict) -> dict:
    """Embed for Strategy Scout and Custom Bot personal signals."""
    symbol   = signal.get("symbol", "")
    raw_side = (signal.get("side") or "buy").lower()
    is_buy   = raw_side in ("buy", "cover")
    direction = "LONG" if is_buy else "SHORT"
    arrow  = "🟢" if is_buy else "🔴"
    color  = _COLOR_BUY if is_buy else _COLOR_SELL
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)
    source   = signal.get("source", "scout")
    strategy = signal.get("strategy") or "—"
    entry    = signal.get("price")

    notional_usd = signal.get("notional_usd")
    if notional_usd and entry and entry > 0:
        qty = notional_usd / entry
        size_value = f"${notional_usd:,.2f} / {_fmt_qty(qty, symbol)}"
    elif notional_usd:
        size_value = f"${notional_usd:,.2f}"
    else:
        size_value = "—"

    if source == "custom_bot":
        bot_name = signal.get("bot_name") or signal.get("bot") or "Custom Bot"
        author_name = f"Custom: {bot_name}"
    else:
        author_name = "Strategy Scout — Personal Setup"

    fields = [
        {"name": "Strategy",   "value": strategy,       "inline": True},
        {"name": "Direction",  "value": direction,       "inline": True},
        {"name": "Confidence", "value": f"{conf_pct}%",  "inline": True},
        {"name": "Notional",   "value": size_value,      "inline": True},
    ]
    if entry is not None:
        fields.append({"name": "Entry",       "value": _fmt_price(entry),           "inline": True})
    if signal.get("stop") is not None:
        fields.append({"name": "Stop",        "value": _fmt_price(signal["stop"]),  "inline": True})
    if signal.get("target") is not None:
        fields.append({"name": "Take Profit", "value": _fmt_price(signal["target"]),"inline": True})
    if signal.get("triggering_strategies"):
        fields.append({"name": "Triggered by", "value": signal["triggering_strategies"], "inline": False})

    return {
        "author":      {"name": author_name},
        "title":       f"{arrow} {direction} {symbol}",
        "description": (signal.get("reason") or "")[:2000],
        "color":       color,
        "fields":      fields,
        "footer":      {"text": COMPLIANCE_FOOTER},
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }


def _build_signal_embed(signal: dict) -> dict:
    bot    = signal.get("bot", "")
    symbol = signal.get("symbol", "")
    raw_side = (signal.get("side") or "buy").lower()
    is_buy   = raw_side in ("buy", "cover")
    direction = "LONG" if is_buy else "SHORT"
    arrow  = "🟢" if is_buy else "🔴"
    color  = _COLOR_BUY if is_buy else _COLOR_SELL
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)

    # Dollar amount: prefer explicit notional_usd (set by deployment sizer), else fallback
    entry        = signal.get("price")
    notional_usd = signal.get("notional_usd")
    size_pct     = signal.get("size_pct")
    cap_cents    = signal.get("starting_capital_cents")
    dollar_label = "Invested" if is_buy else "Notional"

    # Options-specific fields (resolved early so size_value can use it)
    option_type = signal.get("option_type")
    _is_options_signal = bool(option_type or signal.get("is_options"))

    if notional_usd is not None and notional_usd > 0:
        # For options: never show "N.NNNN SYMBOL" (that's share qty, meaningless for contracts)
        if _is_options_signal:
            size_value = f"${notional_usd:,.2f}"
        else:
            qty = notional_usd / entry if entry and entry > 0 else None
            size_value = (
                f"${notional_usd:,.2f} / {_fmt_qty(qty, symbol)}"
                if qty is not None
                else f"${notional_usd:,.2f}"
            )
    elif size_pct is not None and cap_cents is not None and cap_cents > 0:
        invested = (cap_cents / 100) * (size_pct / 100)
        if _is_options_signal:
            size_value = f"${invested:,.2f}"
        else:
            qty = invested / entry if entry and entry > 0 else None
            size_value = (
                f"${invested:,.2f} / {_fmt_qty(qty, symbol)}"
                if qty is not None
                else f"${invested:,.2f}"
            )
    else:
        dollar_label = "Size"
        size_value = f"{size_pct:.1f}%" if size_pct is not None else "—"

    fields = [
        {"name": "Strategy",    "value": signal.get("strategy") or "—", "inline": True},
        {"name": "Direction",   "value": direction,                      "inline": True},
        {"name": "Confidence",  "value": f"{conf_pct}%",                 "inline": True},
        {"name": dollar_label,  "value": size_value,                     "inline": True},
    ]
    # Equity price levels — omit for options signals (options use their own fields below)
    if not option_type:
        if entry is not None:
            fields.append({"name": "Entry",       "value": _fmt_price(entry),              "inline": True})
        if signal.get("stop") is not None:
            fields.append({"name": "Stop",        "value": _fmt_price(signal["stop"]),     "inline": True})
        if signal.get("target") is not None:
            fields.append({"name": "Take Profit", "value": _fmt_price(signal["target"]),   "inline": True})

    if option_type:
        ot_lower = option_type.lower()
        if ot_lower == "call":
            type_badge = "📞 CALL"
        elif ot_lower == "put":
            type_badge = "🔻 PUT"
        else:
            # e.g. "call/put spread" → "📞/🔻 CALL / PUT SPREAD"
            type_label = option_type.upper().replace("/", " / ")
            type_badge = f"📞/🔻 {type_label}"
        fields.append({"name": "Type", "value": type_badge, "inline": True})
        # Specific contract details (populated when yfinance resolves chain)
        if signal.get("strike_price") is not None:
            fields.append({"name": "Strike",    "value": _fmt_price(float(signal["strike_price"])),     "inline": True})
        if signal.get("expiration_date") is not None:
            fields.append({"name": "Expiry",    "value": str(signal["expiration_date"]),                "inline": True})
        if signal.get("contract_count") is not None:
            fields.append({"name": "Contracts", "value": str(signal["contract_count"]),                 "inline": True})
        if signal.get("premium") is not None:
            fields.append({"name": "Premium/Contract", "value": _fmt_price(float(signal["premium"])),   "inline": True})
        # Setup description from strategy reason JSON (always available for options signals)
        if signal.get("options_strikes"):
            fields.append({"name": "Setup",   "value": signal["options_strikes"],                       "inline": False})
        if signal.get("options_spot"):
            fields.append({"name": "Spot",    "value": _fmt_price(float(signal["options_spot"])),       "inline": True})

    return {
        "author": {"name": f"{BOT_DISPLAY.get(bot, bot)} bot"},
        "title":  f"{arrow} {direction} {symbol}",
        "description": (signal.get("reason") or "")[:2000],
        "color":  color,
        "fields": fields,
        "footer": {"text": COMPLIANCE_FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _post_to_channel(channel_id: str, embed: dict, token: str) -> Optional[str]:
    """POST embed to a Discord channel with exponential backoff retry on 429.

    Returns the message ID string on success, or None if all attempts fail.
    Up to 3 total attempts: waits retry_after (or 1s) then 2s then 4s.
    """
    import time

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    max_attempts = 3
    for attempt in range(max_attempts):
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"embeds": [embed]},
            )
        if resp.status_code == 429:
            try:
                retry_after = float(resp.json().get("retry_after", 1.0))
            except Exception:
                retry_after = 1.0
            wait = retry_after if attempt == 0 else retry_after * (2 ** attempt)
            logger.warning(
                "Discord rate limited on channel %s (attempt %d/%d) — sleeping %.2fs",
                channel_id, attempt + 1, max_attempts, wait,
            )
            if attempt < max_attempts - 1:
                time.sleep(wait)
            else:
                logger.error(
                    "Discord rate limit: gave up after %d attempts on channel %s",
                    max_attempts, channel_id,
                )
                return None
        elif not resp.is_success:
            logger.warning("Discord post failed channel=%s status=%s: %s",
                           channel_id, resp.status_code, resp.text[:200])
            return None
        else:
            try:
                return str(resp.json().get("id", ""))
            except Exception:
                return None
    return None


def post_signal(
    signal: dict,
    db=None,
    signal_id: Optional[int] = None,
    source: str = "bot",
) -> None:
    """Post signal embed to all relevant channels.

    source: "bot" (default) | "scout" | "custom_bot"

    If `db` and `signal_id` are provided and source="bot", sets
    discord_posted_at on the bot_signals row (deduplication guard for the
    Node.js worker).
    """
    cfg = _cfg()
    if not cfg.discord_bot_token:
        return

    _log_channel_config()

    # Personal signals (scout / custom_bot) go to #my-signals only.
    if source in ("scout", "custom_bot"):
        my_signals_ch = os.getenv("DISCORD_CHANNEL_ID_MY_SIGNALS", "")
        if not my_signals_ch:
            logger.warning("[discord] DISCORD_CHANNEL_ID_MY_SIGNALS not set — scout/custom-bot signal dropped")
            return
        embed = _build_scout_embed({**signal, "source": source})
        _post_to_channel(my_signals_ch, embed, cfg.discord_bot_token)
        return

    # Standard bot path — dedup guard.
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
            if mid:
                if not message_id:
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
