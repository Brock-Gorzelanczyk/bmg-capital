"""
Queen Agent — hierarchical coordinator for the BMG Capital strategy system.

Posts 4 updates per day to #dev-log (DISCORD_CH_DEV_LOG):

  07:00 AM ET  morning  — Intelligence brief: regime, IC, research directives
  12:00 PM ET  midday   — Intraday pulse: P&L so far, signals, bot health
  04:30 PM ET  close    — EOD report: full day P&L, winners/losers, overnight positions
  09:00 PM ET  evening  — Crypto/overnight watch: BTC dominance, open positions
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

Session_t = Literal["morning", "midday", "close", "evening"]

_STATUS_ICON  = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}
_SESSION_COLOR = {
    "morning": 0x0F172A,
    "midday":  0x1D4ED8,
    "close":   0x16A34A,
    "evening": 0x7C3AED,
}
_SESSION_LABEL = {
    "morning": "Morning Brief",
    "midday":  "Midday Pulse",
    "close":   "EOD Report",
    "evening": "Evening Crypto Watch",
}
_SESSION_FOOTER = {
    "morning": "7 AM ET",
    "midday":  "12 PM ET",
    "close":   "4:30 PM ET",
    "evening": "9 PM ET",
}
_REGIME_EMOJI = {
    "bull_trending": "📈", "bear_trending": "📉", "choppy": "〰️",
    "crisis": "🔥", "complacency": "😴", "neutral": "⚖️", "unknown": "❓",
}


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
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
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
    if dis:
        parts.append(f"{dis} disabled")
    return " | ".join(parts)


def _signal_line(health: dict) -> str:
    sr  = health.get("signal_rate", {})
    pct = f" ({sr['pct_of_avg']}% of avg)" if sr.get("pct_of_avg") is not None else ""
    return f"{sr.get('today','?')} today | avg {sr.get('daily_avg_7d','?')}/day{pct} — **{sr.get('status','?')}**"


def _pnl_fields(pnl: dict) -> list[dict]:
    total    = pnl.get("total_cents", 0)
    realized = pnl.get("realized_cents", 0)
    unrealiz = pnl.get("unrealized_cents", 0)
    fees     = pnl.get("fees_cents", 0)
    trades   = pnl.get("trade_count", 0)
    open_pos = pnl.get("open_positions", 0)
    dot      = "🟢" if total >= 0 else "🔴"
    pnl_val  = (
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


def _build_morning_embed(health: dict, research: dict, now: datetime) -> dict:
    status = health.get("status", "UNKNOWN")
    s_icon = _STATUS_ICON.get(status, "❓")
    ic_data   = research.get("signal_ic", [])
    degrading = [i["bot"] for i in ic_data if i.get("status") == "degrading"]
    strong    = [i["bot"] for i in ic_data if i.get("status") == "strong"]
    ic_parts  = []
    if degrading: ic_parts.append(f"Degrading: {', '.join(degrading[:3])}")
    if strong:    ic_parts.append(f"Strong: {', '.join(strong[:3])}")
    ic_val     = " | ".join(ic_parts) if ic_parts else "All within normal range"
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
        {"name": f"{s_icon} System Status",   "value": status,                "inline": True},
        {"name": "Market Regime",             "value": _regime_line(research), "inline": False},
        {"name": "Bot Execution",             "value": _bot_summary(health),   "inline": False},
        {"name": "Signals",                   "value": _signal_line(health),   "inline": False},
        {"name": "Alpaca (stocks sleeve)",    "value": alp_val,                "inline": False},
        {"name": "Signal IC Health",        "value": ic_val,                 "inline": False},
        {"name": "WFA Pipeline",            "value": cand_val,               "inline": False},
        {"name": "Research Directives",     "value": recs_val,               "inline": False},
    ]
    if alerts:
        fields.append({"name": "Active Alerts", "value": "\n".join(f"⚠ {a}" for a in alerts[:5]), "inline": False})
    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"Morning Brief — {now.strftime('%A, %B %-d, %Y')}",
        "color":     _SESSION_COLOR["morning"],
        "fields":    fields,
        "footer":    {"text": "Paper trading · Not investment advice · 7 AM ET"},
        "timestamp": now.isoformat(),
    }


def _build_pnl_embed(session: Session_t, health: dict, research: dict, pnl: dict, now: datetime) -> dict:
    status = health.get("status", "UNKNOWN")
    s_icon = _STATUS_ICON.get(status, "❓")
    alerts = health.get("alerts", [])
    fields = [
        {"name": f"{s_icon} System", "value": status,                "inline": True},
        {"name": "Regime",           "value": _regime_line(research), "inline": False},
        *_pnl_fields(pnl),
        {"name": "Bot Execution",    "value": _bot_summary(health),   "inline": False},
        {"name": "Signals",          "value": _signal_line(health),   "inline": False},
    ]
    if alerts:
        fields.append({"name": "Alerts", "value": "\n".join(f"⚠ {a}" for a in alerts[:4]), "inline": False})
    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"{_SESSION_LABEL[session]} — {now.strftime('%A, %B %-d, %Y')}",
        "color":     _SESSION_COLOR[session],
        "fields":    fields,
        "footer":    {"text": f"Paper trading · Not investment advice · {_SESSION_FOOTER[session]}"},
        "timestamp": now.isoformat(),
    }


def run_queen_daily(db: Session, session: Session_t = "morning") -> None:
    """
    Called by APScheduler 4× per day: morning (7AM), midday (12PM), close (4:30PM), evening (9PM).
    Never raises — errors are logged so the scheduler job stays alive.
    """
    now = datetime.now(timezone.utc)
    logger.warning("[queen] %s brief starting — %s", session, now.isoformat())

    try:
        from strategy_lab.agents.strategy_monitor import run_strategy_health_check, get_pnl_snapshot
        health = run_strategy_health_check(db)
        pnl    = get_pnl_snapshot(db) if session != "morning" else {}
    except Exception as exc:
        logger.error("[queen] strategy_monitor failed: %s", exc)
        health = {"status": "RED", "bots": [], "alpaca": {}, "signal_rate": {}, "alerts": [str(exc)[:80]]}
        pnl    = {}

    try:
        from strategy_lab.agents.researcher import run_daily_research
        research = run_daily_research(db)
    except Exception as exc:
        logger.error("[queen] researcher failed: %s", exc)
        research = {"regime": {}, "signal_ic": [], "candidates": [], "recommendations": [str(exc)[:80]]}

    embed = (
        _build_morning_embed(health, research, now)
        if session == "morning"
        else _build_pnl_embed(session, health, research, pnl, now)
    )

    try:
        from app.config import settings
        token      = settings.discord_bot_token
        channel_id = (
            settings.discord_ch_dev_log
            or os.getenv("DISCORD_CH_DEV_LOG", "")
            or os.getenv("DISCORD_CH_SENTINEL_OPS", "")
        )
        if not channel_id:
            logger.warning("[queen] DISCORD_CH_DEV_LOG not set — embed logged only")
        elif _post_embed(channel_id, token, embed):
            logger.warning("[queen] %s brief posted to Discord", session)
        else:
            logger.warning("[queen] Discord post failed — %s brief logged", session)
    except Exception as exc:
        logger.error("[queen] Discord dispatch error: %s", exc)

    logger.warning(
        "[queen] %s done status=%s pnl=%s stale=%d alerts=%d",
        session,
        health.get("status"),
        _fmt_pnl(pnl.get("total_cents", 0)) if pnl else "n/a",
        sum(1 for b in health.get("bots", []) if b.get("status") == "STALE"),
        len(health.get("alerts", [])),
    )
