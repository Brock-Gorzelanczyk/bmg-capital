"""
Queen Agent — hierarchical coordinator for the BMG Capital strategy system.

Scheduled sessions (all to DISCORD_CH_DEV_LOG):
  07:00 AM ET  morning        Intelligence brief: regime, IC, directives
  12:00 PM ET  midday         Intraday pulse: P&L so far, signals, bot health
  04:30 PM ET  close          EOD report: full day P&L, winners/losers, open positions
  09:00 PM ET  evening        Crypto/overnight watch + after-hours P&L annotation
  06:00 AM ET  weekend_recap  Monday only — Sat+Sun crypto P&L recap
  08:00 PM ET  weekly         Sunday only — full week digest

Event-driven:
  run_regime_alert_check()  — called every 30 min; posts immediately when signal fires
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

Session_t = Literal["morning", "midday", "close", "evening", "weekend_recap", "weekly"]

_STATUS_ICON  = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}
_SESSION_COLOR = {
    "morning":       0x0F172A,  # navy
    "midday":        0x1D4ED8,  # blue
    "close":         0x16A34A,  # green
    "evening":       0x7C3AED,  # purple
    "weekend_recap": 0x0E7490,  # teal
    "weekly":        0xB45309,  # amber
}
_SESSION_LABEL = {
    "morning":       "Morning Brief",
    "midday":        "Midday Pulse",
    "close":         "EOD Report",
    "evening":       "Evening Crypto Watch",
    "weekend_recap": "Weekend Crypto Recap",
    "weekly":        "Weekly Digest",
}
_SESSION_FOOTER = {
    "morning":       "7 AM ET · Mon–Fri",
    "midday":        "12 PM ET · Mon–Fri",
    "close":         "4:30 PM ET · Mon–Fri",
    "evening":       "9 PM ET · Daily",
    "weekend_recap": "6 AM ET · Monday",
    "weekly":        "8 PM ET · Sunday",
}
_REGIME_EMOJI = {
    "bull_trending": "📈", "bear_trending": "📉", "choppy": "〰️",
    "crisis": "🔥", "complacency": "😴", "neutral": "⚖️", "unknown": "❓",
}

# In-memory cooldown: signal_key → last fired UTC datetime (24h dedup)
_alert_last_fired: dict[str, datetime] = {}
_ALERT_COOLDOWN_HOURS = 24


def _fmt_pnl(cents: int) -> str:
    usd  = cents / 100
    sign = "+" if usd >= 0 else "-"
    return f"{sign}${abs(usd):,.2f}"


def _fmt_usd(val: float) -> str:
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}k"
    return f"${val:,.2f}"


def _post_embed(channel_id: str, token: str, embed: dict) -> bool:
    if not channel_id or not token:
        return False
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bot {token}",
                    "Content-Type":  "application/json",
                    "User-Agent":    "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
                },
                json={"embeds": [embed]},
            )
        if resp.status_code == 429:
            logger.warning("[queen] Discord rate-limited on channel %s", channel_id)
            return False
        if not resp.is_success:
            logger.warning("[queen] Discord post failed: %s — %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.error("[queen] Discord HTTP error: %s", exc)
        return False


def _get_discord_channel() -> tuple[str, str]:
    """Return (token, channel_id) or ("", "") if not configured."""
    try:
        from app.config import settings
        token      = settings.discord_bot_token or ""
        channel_id = (
            settings.discord_ch_dev_log
            or os.getenv("QUEEN_BRIEF_CHANNEL_ID", "")
            or os.getenv("DISCORD_CH_DEV_LOG", "")
            or os.getenv("DISCORD_CH_SENTINEL_OPS", "")
        )
        return token, channel_id
    except Exception:
        return os.getenv("DISCORD_BOT_TOKEN", ""), os.getenv("DISCORD_CH_DEV_LOG", "")


# ── Shared field builders ─────────────────────────────────────────────────────

def _regime_line(research: dict) -> str:
    r     = research.get("regime", {})
    name  = r.get("name", "unknown")
    emoji = _REGIME_EMOJI.get(name, "❓")
    vix   = r.get("vix")
    btc   = r.get("btc_dom")
    return (
        f"{emoji} **{name}** | VIX {f'{vix:.1f}' if vix else 'N/A'} "
        f"| Trend {r.get('trend', 'unknown')} | BTC Dom {f'{btc:.1f}%' if btc else 'N/A'}"
    )


def _bot_summary(health: dict) -> str:
    bots  = health.get("bots", [])
    ok    = sum(1 for b in bots if b.get("status") == "OK")
    stale = [b["bot"] for b in bots if b.get("status") == "STALE"]
    dis   = sum(1 for b in bots if b.get("status") == "DISABLED")
    parts = [f"{ok} healthy"]
    if stale:
        parts.append(f"{len(stale)} stale: {', '.join(stale[:3])}")
    parts.append(f"{dis} disabled")
    return " | ".join(parts)


def _signal_line(health: dict) -> str:
    sr  = health.get("signal_rate", {})
    pct = f" ({sr['pct_of_avg']}% of avg)" if sr.get("pct_of_avg") is not None else ""
    return f"{sr.get('today','?')} today | avg {sr.get('daily_avg_7d','?')}/day{pct} — **{sr.get('status','?')}**"


def _pnl_fields(pnl: dict, *, evening: bool = False) -> list[dict]:
    total    = pnl.get("total_cents", 0)
    realized = pnl.get("realized_cents", 0)
    unrealiz = pnl.get("unrealized_cents", 0)
    fees     = pnl.get("fees_cents", 0)
    trades   = pnl.get("trade_count", 0)
    open_pos = pnl.get("open_positions", 0)
    dot      = "🟢" if total >= 0 else "🔴"

    if evening:
        # Realized = stable after RTH close; unrealized = live AH moves
        pnl_val = (
            f"{dot} **{_fmt_pnl(total)}** total\n"
            f"RTH close (realized): {_fmt_pnl(realized)} | "
            f"AH unrealized: {_fmt_pnl(unrealiz)} | Fees: {_fmt_pnl(-fees)}"
        )
    else:
        pnl_val = (
            f"{dot} **{_fmt_pnl(total)}** total\n"
            f"Realized: {_fmt_pnl(realized)} | Unrealized: {_fmt_pnl(unrealiz)} | Fees: {_fmt_pnl(-fees)}"
        )

    winners = pnl.get("top_winners", [])
    losers  = pnl.get("top_losers", [])
    win_str = "\n".join(f"  {w['symbol']} {_fmt_pnl(w['pnl_cents'])}" for w in winners[:3]) or "—"
    los_str = "\n".join(f"  {l['symbol']} {_fmt_pnl(l['pnl_cents'])}" for l in losers[:3]) or "—"
    return [
        {"name": "P&L Today",     "value": pnl_val,                                        "inline": False},
        {"name": "Closed Trades", "value": f"{trades} trades | {open_pos} open positions",  "inline": True},
        {"name": "Top Winners",   "value": win_str,                                         "inline": True},
        {"name": "Top Losers",    "value": los_str,                                         "inline": True},
    ]


# ── Per-session embed builders ────────────────────────────────────────────────

def _build_morning_embed(health: dict, research: dict, now: datetime) -> dict:
    status = health.get("status", "UNKNOWN")
    s_icon = _STATUS_ICON.get(status, "❓")
    ic_data   = research.get("signal_ic", [])
    degrading = [i["bot"] for i in ic_data if i.get("status") == "degrading"]
    strong    = [i["bot"] for i in ic_data if i.get("status") == "strong"]
    ic_parts  = []
    if degrading: ic_parts.append(f"Degrading: {', '.join(degrading[:3])}")
    if strong:    ic_parts.append(f"Strong: {', '.join(strong[:3])}")
    ic_val   = " | ".join(ic_parts) if ic_parts else "All within normal range"
    candidates = research.get("candidates", [])
    promoted   = [c for c in candidates if c.get("status") in ("promoted", "gate_passed")]
    cand_val   = f"{len(promoted)} ready | {len(candidates)} in pipeline" if candidates else "No candidates"
    recs_val   = "\n".join(f"• {r}" for r in research.get("recommendations", [])[:5]) or "No directives"
    alp        = health.get("alpaca", {})
    alp_val    = f"**{alp.get('status','?')}**"
    if alp.get("equity_usd") is not None:
        alp_val += f" | equity {_fmt_usd(alp['equity_usd'])} | BP {_fmt_usd(alp.get('buying_power_usd', 0))}"
    alerts = health.get("alerts", [])
    fields = [
        {"name": f"{s_icon} System Status",  "value": status,                "inline": True},
        {"name": "Market Regime",            "value": _regime_line(research), "inline": False},
        {"name": "Bot Execution",            "value": _bot_summary(health),   "inline": False},
        {"name": "Signals",                  "value": _signal_line(health),   "inline": False},
        {"name": "Alpaca (stocks sleeve)",   "value": alp_val,                "inline": False},
        {"name": "Signal IC Health",         "value": ic_val,                 "inline": False},
        {"name": "WFA Pipeline",             "value": cand_val,               "inline": False},
        {"name": "Research Directives",      "value": recs_val,               "inline": False},
    ]
    if alerts:
        fields.append({"name": "⚠️ Alerts", "value": "\n".join(f"⚠ {a}" for a in alerts[:5]), "inline": False})
    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"Morning Brief — {now.strftime('%A, %B %-d, %Y')}",
        "color":     _SESSION_COLOR["morning"],
        "fields":    fields,
        "footer":    {"text": f"Paper trading · Not investment advice · {_SESSION_FOOTER['morning']}"},
        "timestamp": now.isoformat(),
    }


def _build_pnl_embed(session: Session_t, health: dict, research: dict, pnl: dict, now: datetime) -> dict:
    status = health.get("status", "UNKNOWN")
    s_icon = _STATUS_ICON.get(status, "❓")
    alerts = health.get("alerts", [])
    fields = [
        {"name": f"{s_icon} System", "value": status,                "inline": True},
        {"name": "Regime",           "value": _regime_line(research), "inline": False},
        *_pnl_fields(pnl, evening=(session == "evening")),
        {"name": "Bot Execution",    "value": _bot_summary(health),   "inline": False},
        {"name": "Signals",          "value": _signal_line(health),   "inline": False},
    ]
    if alerts:
        fields.append({"name": "⚠️ Alerts", "value": "\n".join(f"⚠ {a}" for a in alerts[:4]), "inline": False})
    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"{_SESSION_LABEL[session]} — {now.strftime('%A, %B %-d, %Y')}",
        "color":     _SESSION_COLOR[session],
        "fields":    fields,
        "footer":    {"text": f"Paper trading · Not investment advice · {_SESSION_FOOTER[session]}"},
        "timestamp": now.isoformat(),
    }


def _build_weekend_recap_embed(health: dict, weekend_pnl: dict, now: datetime) -> dict:
    total   = weekend_pnl.get("total_cents", 0)
    sleeves = weekend_pnl.get("by_sleeve", {})
    sat     = weekend_pnl.get("saturday", "Sat")
    sun     = weekend_pnl.get("sunday", "Sun")
    dot     = "🟢" if total >= 0 else "🔴"

    sleeve_lines = "\n".join(
        f"  {sleeve.capitalize()}: {_fmt_pnl(cents)}"
        for sleeve, cents in sleeves.items()
        if cents != 0
    ) or "  No P&L recorded"

    bots      = health.get("bots", [])
    crypto_ok = sum(1 for b in bots if b.get("status") == "OK" and "crypto" in b.get("bot", ""))

    fields = [
        {"name": f"{dot} Weekend P&L ({sat} – {sun})", "value": f"**{_fmt_pnl(total)}** total\n{sleeve_lines}", "inline": False},
        {"name": "Crypto Bots Active",                 "value": f"{crypto_ok} healthy over weekend",            "inline": True},
        {"name": "Bot Execution",                      "value": _bot_summary(health),                           "inline": False},
    ]
    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"Weekend Crypto Recap — {now.strftime('%A, %B %-d, %Y')}",
        "color":     _SESSION_COLOR["weekend_recap"],
        "fields":    fields,
        "footer":    {"text": f"Paper trading · Not investment advice · {_SESSION_FOOTER['weekend_recap']}"},
        "timestamp": now.isoformat(),
    }


def _build_weekly_embed(health: dict, research: dict, weekly_pnl: dict, now: datetime) -> dict:
    total   = weekly_pnl.get("total_cents", 0)
    sleeves = weekly_pnl.get("by_sleeve", {})
    dot     = "🟢" if total >= 0 else "🔴"

    sleeve_lines = "\n".join(
        f"  {sleeve.capitalize()}: {_fmt_pnl(cents)}"
        for sleeve, cents in sleeves.items()
    ) or "  No P&L recorded"

    top_bots  = weekly_pnl.get("top_bots", [])
    bot_bots  = weekly_pnl.get("bottom_bots", [])
    top_str   = "\n".join(f"  {b['bot']} {_fmt_pnl(b['pnl_cents'])}" for b in top_bots) or "—"
    bot_str   = "\n".join(f"  {b['bot']} {_fmt_pnl(b['pnl_cents'])}" for b in bot_bots) or "—"

    candidates = research.get("candidates", [])
    promoted   = [c["strategy"] for c in candidates if c.get("status") in ("promoted", "gate_passed")]
    cand_str   = f"{len(promoted)} promoted: {', '.join(promoted[:3])}" if promoted else f"{len(candidates)} in pipeline, none promoted"

    recs_val = "\n".join(f"• {r}" for r in research.get("recommendations", [])[:4]) or "No directives"

    fields = [
        {"name": f"{dot} 7-Day P&L", "value": f"**{_fmt_pnl(total)}** total\n{sleeve_lines}",       "inline": False},
        {"name": "Top Bots",          "value": top_str,                                               "inline": True},
        {"name": "Bottom Bots",       "value": bot_str,                                               "inline": True},
        {"name": "Bot Execution",     "value": _bot_summary(health),                                  "inline": False},
        {"name": "Candidate Pipeline","value": cand_str,                                              "inline": False},
        {"name": "Research Directives","value": recs_val,                                             "inline": False},
    ]
    alerts = health.get("alerts", [])
    if alerts:
        fields.append({"name": "⚠️ Alerts", "value": "\n".join(f"⚠ {a}" for a in alerts[:4]), "inline": False})
    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"Weekly Digest — Week of {now.strftime('%B %-d, %Y')}",
        "color":     _SESSION_COLOR["weekly"],
        "fields":    fields,
        "footer":    {"text": f"Paper trading · Not investment advice · {_SESSION_FOOTER['weekly']}"},
        "timestamp": now.isoformat(),
    }


def _build_regime_alert_embed(alert: dict, now: datetime) -> dict:
    severity = alert.get("severity", "MEDIUM")
    color    = 0xDC2626 if severity == "HIGH" else 0xF59E0B
    icon     = "🚨" if severity == "HIGH" else "⚠️"
    return {
        "author":    {"name": "BMG Capital — Regime Alert"},
        "title":     f"{icon} Regime Signal: {alert['signal'].replace('_', ' ').title()}",
        "color":     color,
        "description": alert["description"],
        "fields": [
            {"name": "Severity", "value": severity,                "inline": True},
            {"name": "Signal",   "value": alert["signal"],         "inline": True},
            {"name": "Action",   "value": "Review open positions and regime routing.", "inline": False},
        ],
        "footer":    {"text": "Paper trading · Not investment advice · Event-driven alert"},
        "timestamp": now.isoformat(),
    }


# ── Entry points ──────────────────────────────────────────────────────────────

def run_queen_daily(db: Session, session: Session_t = "morning") -> None:
    """
    Called by APScheduler for all 6 scheduled sessions.
    Never raises — errors are logged so the scheduler job stays alive.
    """
    now = datetime.now(timezone.utc)
    logger.warning("[queen] %s session starting — %s", session, now.isoformat())

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="queen")
    except Exception:
        pass

    try:
        from strategy_lab.agents.strategy_monitor import (
            run_strategy_health_check, get_pnl_snapshot,
            get_weekend_pnl, get_weekly_pnl,
        )
        health = run_strategy_health_check(db)
        pnl    = {}
        weekend_pnl = {}
        weekly_pnl  = {}

        if session in ("midday", "close", "evening"):
            pnl = get_pnl_snapshot(db)
        elif session == "weekend_recap":
            weekend_pnl = get_weekend_pnl(db)
        elif session == "weekly":
            weekly_pnl = get_weekly_pnl(db)
    except Exception as exc:
        logger.error("[queen] strategy_monitor failed: %s", exc)
        health = {"status": "RED", "bots": [], "alpaca": {}, "signal_rate": {}, "alerts": [str(exc)[:80]]}
        pnl = weekend_pnl = weekly_pnl = {}

    try:
        from strategy_lab.agents.researcher import run_daily_research
        research = run_daily_research(db)
    except Exception as exc:
        logger.error("[queen] researcher failed: %s", exc)
        research = {"regime": {}, "signal_ic": [], "candidates": [], "recommendations": [str(exc)[:80]]}

    if session == "morning":
        embed = _build_morning_embed(health, research, now)
    elif session == "weekend_recap":
        embed = _build_weekend_recap_embed(health, weekend_pnl, now)
    elif session == "weekly":
        embed = _build_weekly_embed(health, research, weekly_pnl, now)
    else:
        embed = _build_pnl_embed(session, health, research, pnl, now)

    token, channel_id = _get_discord_channel()
    if not channel_id:
        logger.warning("[queen] no channel configured — %s embed logged only", session)
    elif _post_embed(channel_id, token, embed):
        logger.warning("[queen] %s posted to Discord", session)
    else:
        logger.warning("[queen] Discord post failed — %s logged only", session)

    logger.warning(
        "[queen] %s done status=%s pnl=%s stale=%d alerts=%d",
        session,
        health.get("status"),
        _fmt_pnl(pnl.get("total_cents", 0)) if pnl else "n/a",
        sum(1 for b in health.get("bots", []) if b.get("status") == "STALE"),
        len(health.get("alerts", [])),
    )

    try:
        from agents.bus import publish as _bus_publish
        from agents import channels as _ch
        _SESSION_CHANNEL = {
            "morning":       _ch.QUEEN_MORNING,
            "midday":        _ch.QUEEN_MIDDAY,
            "close":         _ch.QUEEN_CLOSE,
            "evening":       _ch.QUEEN_EVENING,
            "weekend_recap": _ch.QUEEN_WEEKEND,
            "weekly":        _ch.QUEEN_WEEKLY,
        }
        _bus_publish(
            db,
            channel=_SESSION_CHANNEL.get(session, f"queen.{session}"),
            from_agent="queen",
            msg_type="brief",
            subject=f"Queen {session} brief — {now.strftime('%Y-%m-%d')}",
            payload={
                "session":          session,
                "health_status":    health.get("status"),
                "regime":           research.get("regime", {}),
                "pnl_total_cents":  pnl.get("total_cents", 0) if pnl else None,
                "stale_bots":       [b["bot"] for b in health.get("bots", []) if b.get("status") == "STALE"],
                "alert_count":      len(health.get("alerts", [])),
            },
        )
    except Exception as _exc:
        logger.debug("[queen] bus publish skipped: %s", _exc)


def run_regime_alert_check(db: Session) -> None:
    """
    Event-driven check — called every 30 min.
    Posts immediately to Discord when a regime alert fires.
    24-hour cooldown per signal prevents spam.
    """
    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="queen")
    except Exception:
        pass

    try:
        from strategy_lab.agents.strategy_monitor import check_regime_alert_signals
        alerts = check_regime_alert_signals(db)
    except Exception as exc:
        logger.error("[queen] regime_alert_check failed: %s", exc)
        return

    if not alerts:
        return

    now   = datetime.now(timezone.utc)
    token, channel_id = _get_discord_channel()

    for alert in alerts:
        sig = alert["signal"]
        last = _alert_last_fired.get(sig)
        if last and (now - last).total_seconds() < _ALERT_COOLDOWN_HOURS * 3600:
            continue  # still in cooldown window

        _alert_last_fired[sig] = now
        embed = _build_regime_alert_embed(alert, now)
        if channel_id and _post_embed(channel_id, token, embed):
            logger.warning("[queen] regime alert posted: %s", sig)
        else:
            logger.warning("[queen] regime alert (no Discord): %s — %s", sig, alert["description"])

        try:
            from agents.bus import publish as _bus_publish
            from agents.channels import QUEEN_REGIME_ALERT
            _bus_publish(
                db,
                channel=QUEEN_REGIME_ALERT,
                from_agent="queen",
                msg_type="regime_alert",
                subject=f"Regime alert: {sig}",
                priority=8,
                payload=alert,
            )
        except Exception as _exc:
            logger.debug("[queen] bus regime alert publish skipped: %s", _exc)
