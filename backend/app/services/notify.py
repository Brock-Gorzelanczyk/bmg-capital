"""
Notification dispatcher — fires when a bot signal is accepted.

dispatch_signal(signal_data, db) is called by the runner for every accepted signal.
It finds all matching subscriptions, checks quiet hours + confidence filter,
enforces rate limits, then hands off to channel-specific send functions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, time as dtime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Per-channel rate limit: 1 notification per bot per 60 seconds
_LAST_SENT: dict[tuple[int, str], float] = {}   # (channel_id, bot_name) → epoch
_BOT_THROTTLE_SECONDS = 60

BOT_DISPLAY = {
    "stock_swing":          "Stock Swing",
    "stock_day":            "Stock Day",
    "stock_lt":             "Stock Long-Term",
    "crypto_swing":         "Crypto Swing",
    "crypto_day":           "Crypto Day",
    "crypto_lt":            "Crypto Long-Term",
    "options_income":       "Options Income",
    "options_directional":  "Options Directional",
    "crypto_onchain":       "Crypto On-Chain",
}

_COLOR_BUY  = 0x2EC4A1
_COLOR_SELL = 0xEF4444
_COLOR_REBALANCE = 0xF59E0B


# ── Quiet-hours check ─────────────────────────────────────────────────────────

def _in_quiet_hours(start_str: Optional[str], end_str: Optional[str], tz_name: str) -> bool:
    if not start_str or not end_str:
        return False
    try:
        import pytz
        tz = pytz.timezone(tz_name or "America/Chicago")
        now_local = datetime.now(tz).time()
        start = dtime(*map(int, start_str.split(":")))
        end   = dtime(*map(int, end_str.split(":")))
        if start <= end:
            return start <= now_local < end
        else:  # wraps midnight
            return now_local >= start or now_local < end
    except Exception as exc:
        logger.debug("quiet hours check failed: %s", exc)
        return False


# ── Rate limiter ──────────────────────────────────────────────────────────────

def _throttled(channel_id: int, bot_name: str) -> bool:
    key = (channel_id, bot_name)
    now = datetime.now(timezone.utc).timestamp()
    last = _LAST_SENT.get(key, 0.0)
    if now - last < _BOT_THROTTLE_SECONDS:
        return True
    _LAST_SENT[key] = now
    return False


# ── Channel adapters ──────────────────────────────────────────────────────────

def _send_discord(webhook_url: str, signal: dict) -> None:
    bot = signal.get("bot", "")
    symbol = signal.get("symbol", "")
    side = signal.get("side", "").upper()
    arrow = "🟢" if side == "BUY" else ("🔴" if side == "SELL" else "🟡")
    color = _COLOR_BUY if side == "BUY" else (_COLOR_SELL if side == "SELL" else _COLOR_REBALANCE)
    bot_name = BOT_DISPLAY.get(bot, bot)
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)

    fields = [
        {"name": "Strategy",   "value": signal.get("strategy") or "—",     "inline": True},
        {"name": "Confidence", "value": f"{conf_pct}%",                    "inline": True},
    ]
    if signal.get("size_pct") is not None:
        fields.append({"name": "Size",   "value": f"{signal['size_pct']:.1f}%",  "inline": True})
    if signal.get("price") is not None:
        fields.append({"name": "Price",  "value": f"${signal['price']:,.2f}",    "inline": True})
    if signal.get("stop"):
        fields.append({"name": "Stop",   "value": f"${signal['stop']:,.2f}",     "inline": True})
    if signal.get("target"):
        fields.append({"name": "Target", "value": f"${signal['target']:,.2f}",   "inline": True})

    payload = {
        "embeds": [{
            "author": {"name": "BMG Capital"},
            "title": f"{arrow} {bot_name} {side} {symbol}",
            "description": signal.get("reason") or "",
            "color": color,
            "fields": fields,
            "footer": {"text": "Paper trading · Not investment advice"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    with httpx.Client(timeout=8) as client:
        resp = client.post(webhook_url, json=payload)
        resp.raise_for_status()


def _send_telegram(chat_id: str, signal: dict) -> None:
    from app.config import settings
    token = settings.telegram_bot_token
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")

    bot = signal.get("bot", "")
    symbol = signal.get("symbol", "")
    side = (signal.get("side") or "").upper()
    arrow = "🟢" if side == "BUY" else ("🔴" if side == "SELL" else "🟡")
    bot_name = BOT_DISPLAY.get(bot, bot)
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)

    lines = [
        f"{arrow} *{bot_name}* {side} *{symbol}*",
        "",
        signal.get("reason") or "",
        "",
        f"📊 Strategy: {signal.get('strategy') or '—'}",
        f"🎯 Confidence: {conf_pct}%",
    ]
    if signal.get("price"):
        lines.append(f"💰 Price: ${signal['price']:,.2f}")
    if signal.get("stop"):
        lines.append(f"🛑 Stop: ${signal['stop']:,.2f}")
    if signal.get("target"):
        lines.append(f"🎯 Target: ${signal['target']:,.2f}")
    lines += ["", "_Paper trading · Not investment advice_"]

    text = "\n".join(lines)
    with httpx.Client(timeout=8) as client:
        resp = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
        )
        resp.raise_for_status()


def _send_slack(webhook_url: str, signal: dict) -> None:
    bot = signal.get("bot", "")
    symbol = signal.get("symbol", "")
    side = (signal.get("side") or "").upper()
    color = "#2EC4A1" if side == "BUY" else ("#EF4444" if side == "SELL" else "#F59E0B")
    bot_name = BOT_DISPLAY.get(bot, bot)
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)

    fields = [
        {"title": "Strategy",   "value": signal.get("strategy") or "—", "short": True},
        {"title": "Confidence", "value": f"{conf_pct}%",                "short": True},
    ]
    if signal.get("price"):
        fields.append({"title": "Price", "value": f"${signal['price']:,.2f}", "short": True})
    if signal.get("stop"):
        fields.append({"title": "Stop",  "value": f"${signal['stop']:,.2f}",  "short": True})

    payload = {
        "attachments": [{
            "color": color,
            "title": f"{bot_name} {side} {symbol}",
            "text": signal.get("reason") or "",
            "fields": fields,
            "footer": "BMG Capital · Paper trading",
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }]
    }
    with httpx.Client(timeout=8) as client:
        resp = client.post(webhook_url, json=payload)
        resp.raise_for_status()


def _send_email(email_addr: str, signal: dict) -> None:
    from app.config import settings
    api_key = settings.resend_api_key
    if not api_key:
        raise ValueError("RESEND_API_KEY not configured")

    bot_name = BOT_DISPLAY.get(signal.get("bot", ""), signal.get("bot", ""))
    side = (signal.get("side") or "").upper()
    symbol = signal.get("symbol", "")
    conf_pct = round((signal.get("confidence") or 0) * 100, 1)
    subject = f"BMG Signal: {bot_name} {side} {symbol}"

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#{'2EC4A1' if side=='BUY' else 'EF4444'}">{side} {symbol}</h2>
      <p><strong>Bot:</strong> {bot_name}</p>
      <p><strong>Strategy:</strong> {signal.get('strategy') or '—'}</p>
      <p><strong>Confidence:</strong> {conf_pct}%</p>
      {f"<p><strong>Price:</strong> ${signal['price']:,.2f}</p>" if signal.get('price') else ''}
      {f"<p><strong>Stop:</strong> ${signal['stop']:,.2f}</p>" if signal.get('stop') else ''}
      <hr/>
      <p style="font-size:12px;color:#888">{signal.get('reason') or ''}</p>
      <p style="font-size:11px;color:#aaa">Paper trading only. Not investment advice.</p>
    </div>
    """

    with httpx.Client(timeout=10) as client:
        resp = client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": "BMG Capital <signals@bmgcapital.com>",
                "to": [email_addr],
                "subject": subject,
                "html": html,
            },
        )
        resp.raise_for_status()


# ── Main dispatcher ───────────────────────────────────────────────────────────

def dispatch_signal(signal: dict, db: Session) -> None:
    """
    Find all matching NotificationSubscription rows for this signal and send.

    signal dict keys: bot, symbol, side, strategy, reason, confidence,
                      price, stop, target, size_pct
    """
    from app.db.models.notification_channels import (
        NotificationChannel, NotificationSubscription, NotificationLog,
    )

    bot_name = signal.get("bot", "")
    side = signal.get("side", "entry")
    signal_type = "entry" if side in ("buy",) else ("exit" if side == "sell" else "rebalance")
    confidence = signal.get("confidence") or 0.0

    subs = (
        db.query(NotificationSubscription)
        .join(NotificationChannel, NotificationChannel.id == NotificationSubscription.channel_id)
        .filter(
            NotificationSubscription.bot_name == bot_name,
            NotificationChannel.enabled.is_(True),
        )
        .all()
    )

    for sub in subs:
        channel = db.get(NotificationChannel, sub.channel_id)
        if not channel or not channel.enabled:
            continue

        # Confidence gate
        if confidence < (sub.min_confidence or 0.0):
            _log(db, channel.id, None, "rate_limited", f"confidence {confidence:.2f} < min {sub.min_confidence:.2f}")
            continue

        # Signal type gate
        if sub.signal_types and signal_type not in sub.signal_types:
            continue

        # Quiet hours gate
        if _in_quiet_hours(sub.quiet_hours_start, sub.quiet_hours_end, sub.quiet_hours_tz or "America/Chicago"):
            _log(db, channel.id, None, "rate_limited", "quiet hours")
            continue

        # Rate limit
        if _throttled(channel.id, bot_name):
            _log(db, channel.id, None, "rate_limited", "throttled 60s")
            continue

        _dispatch_to_channel(channel, signal, db)


def _dispatch_to_channel(channel, signal: dict, db: Session) -> None:
    from app.db.models.notification_channels import NotificationLog
    try:
        if channel.type == "discord" and channel.webhook_url:
            _send_discord(channel.webhook_url, signal)
        elif channel.type == "slack" and channel.webhook_url:
            _send_slack(channel.webhook_url, signal)
        elif channel.type == "telegram" and channel.telegram_chat_id:
            _send_telegram(channel.telegram_chat_id, signal)
        elif channel.type == "email" and channel.email:
            _send_email(channel.email, signal)
        else:
            return
        _log(db, channel.id, None, "sent", None)
    except Exception as exc:
        logger.warning("notify failed channel=%d type=%s: %s", channel.id, channel.type, exc)
        _log(db, channel.id, None, "failed", str(exc)[:500])


def _log(db: Session, channel_id: int, signal_id, status: str, error: Optional[str]) -> None:
    from app.db.models.notification_channels import NotificationLog
    try:
        db.add(NotificationLog(channel_id=channel_id, signal_id=signal_id, status=status, error_msg=error))
        db.commit()
    except Exception:
        pass


# ── Test signal payload ───────────────────────────────────────────────────────

TEST_SIGNAL = {
    "bot": "crypto_swing",
    "symbol": "BTC/USD",
    "side": "buy",
    "strategy": "crypto_rsi_mean_reversion",
    "reason": "This is a test notification from BMG Capital. RSI crossed below 30 on the 4h chart.",
    "confidence": 0.95,
    "price": 67_500.00,
    "stop": 64_000.00,
    "target": 74_000.00,
    "size_pct": 10.0,
}
