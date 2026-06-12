"""
Queen Agent — hierarchical coordinator for the BMG Capital strategy system.

Runs daily at 7:00 AM ET (Mon-Fri). Orchestrates two sub-agents and
synthesizes their output into a single Discord embed posted to #dev-log:

  strategy_monitor  → system health (bot windows, Alpaca, signal rate)
  researcher        → market regime, signal IC, WFA candidates, directives

One embed, one channel, zero noise. The Queen is the daily pulse.

Required env var: DISCORD_CH_DEV_LOG (channel ID for #dev-log).
Falls back to logging if not set.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_STATUS_COLOR = {"GREEN": 0x16A34A, "YELLOW": 0xF59E0B, "RED": 0xDC2626}
_STATUS_ICON  = {"GREEN": "✅",      "YELLOW": "⚠️",     "RED": "🚨"}
_REGIME_EMOJI = {
    "bull_trending": "📈",
    "bear_trending": "📉",
    "choppy":        "〰️",
    "crisis":        "🔥",
    "complacency":   "😴",
    "neutral":       "⚖️",
    "unknown":       "❓",
}


def _post_embed(channel_id: str, token: str, embed: dict) -> bool:
    """HTTP POST a single Discord embed. Returns True on success."""
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


def _build_embed(health: dict, research: dict, now: datetime) -> dict:
    """Compose the Queen's daily brief Discord embed."""
    status  = health.get("status", "UNKNOWN")
    color   = _STATUS_COLOR.get(status, 0x6B7280)
    s_icon  = _STATUS_ICON.get(status, "❓")

    # ── Regime ──────────────────────────────────────────────────────────────────
    regime      = research.get("regime", {})
    regime_name = regime.get("name", "unknown")
    r_emoji     = _REGIME_EMOJI.get(regime_name, "❓")
    vix         = regime.get("vix")
    vix_str     = f"{vix:.1f}" if vix else "N/A"
    trend       = regime.get("trend", "unknown")
    btc_dom     = regime.get("btc_dom")
    btc_str     = f"{btc_dom:.1f}%" if btc_dom else "N/A"

    regime_value = (
        f"{r_emoji} **{regime_name}** | VIX {vix_str} | Trend {trend} | BTC Dom {btc_str}"
    )

    # ── Bot execution ────────────────────────────────────────────────────────────
    bots      = health.get("bots", [])
    ok_bots   = [b["bot"] for b in bots if b.get("status") == "OK"]
    stale     = [b["bot"] for b in bots if b.get("status") == "STALE"]
    disabled  = [b["bot"] for b in bots if b.get("status") == "DISABLED"]
    bot_parts = [f"{len(ok_bots)} healthy"]
    if stale:
        bot_parts.append(f"{len(stale)} stale: {', '.join(stale[:3])}")
    bot_parts.append(f"{len(disabled)} disabled")
    bot_value = " | ".join(bot_parts)

    # ── Signal rate ──────────────────────────────────────────────────────────────
    sr          = health.get("signal_rate", {})
    pct_str     = f" ({sr['pct_of_avg']}% of avg)" if sr.get("pct_of_avg") is not None else ""
    signal_value = (
        f"{sr.get('today', '?')} today | avg {sr.get('daily_avg_7d', '?')}/day"
        f"{pct_str} — **{sr.get('status', '?')}**"
    )

    # ── Alpaca ───────────────────────────────────────────────────────────────────
    def _fmt_usd(val: float) -> str:
        if val >= 1_000_000:
            return f"${val / 1_000_000:.2f}M"
        if val >= 1_000:
            return f"${val / 1_000:.1f}k"
        return f"${val:,.2f}"

    alp = health.get("alpaca", {})
    alp_parts = [f"**{alp.get('status', '?')}**"]
    if alp.get("equity_usd") is not None:
        alp_parts.append(f"equity {_fmt_usd(alp['equity_usd'])}")
        alp_parts.append(f"BP {_fmt_usd(alp.get('buying_power_usd', 0))}")
    alpaca_value = " | ".join(alp_parts)

    # ── Signal IC ────────────────────────────────────────────────────────────────
    ic_data    = research.get("signal_ic", [])
    degrading  = [i["bot"] for i in ic_data if i.get("status") == "degrading"]
    strong     = [i["bot"] for i in ic_data if i.get("status") == "strong"]
    ic_parts   = []
    if degrading:
        ic_parts.append(f"Degrading: {', '.join(degrading[:3])}")
    if strong:
        ic_parts.append(f"Strong: {', '.join(strong[:3])}")
    ic_value = " | ".join(ic_parts) if ic_parts else "All within normal range"

    # ── WFA pipeline ─────────────────────────────────────────────────────────────
    candidates = research.get("candidates", [])
    promoted   = [c for c in candidates if c.get("status") in ("promoted", "gate_passed")]
    cand_value = (
        f"{len(promoted)} ready | {len(candidates)} total in pipeline"
        if candidates else "No candidates in pipeline"
    )

    # ── Research directives ──────────────────────────────────────────────────────
    recs      = research.get("recommendations", [])
    recs_value = "\n".join(f"• {r}" for r in recs[:5]) or "No directives"

    # ── Active alerts ─────────────────────────────────────────────────────────────
    alerts      = health.get("alerts", [])
    alert_value = "\n".join(f"⚠ {a}" for a in alerts[:5]) if alerts else "None"

    fields = [
        {"name": f"{s_icon} System Status", "value": status,        "inline": True},
        {"name": "Market Regime",           "value": regime_value,   "inline": False},
        {"name": "Bot Execution",           "value": bot_value,      "inline": False},
        {"name": "Signals Today",           "value": signal_value,   "inline": False},
        {"name": "Alpaca (stocks sleeve)",   "value": alpaca_value,   "inline": False},
        {"name": "Signal IC Health",        "value": ic_value,       "inline": False},
        {"name": "WFA Pipeline",            "value": cand_value,     "inline": False},
        {"name": "Research Directives",     "value": recs_value,     "inline": False},
    ]
    if alerts:
        fields.append({"name": "Active Alerts", "value": alert_value, "inline": False})

    return {
        "author":    {"name": "BMG Capital — Queen Agent"},
        "title":     f"Daily Intelligence Brief — {now.strftime('%A, %B %-d, %Y')}",
        "color":     color,
        "fields":    fields,
        "footer":    {"text": "Paper trading · Not investment advice · Automated system report"},
        "timestamp": now.isoformat(),
    }


def run_queen_daily(db: Session) -> None:
    """
    Main entry point — called by APScheduler at 7:00 AM ET, Mon-Fri.

    Runs strategy_monitor + researcher, builds embed, posts to #dev-log.
    Never raises — all errors are logged so the scheduler job stays alive.
    """
    now = datetime.now(timezone.utc)
    logger.warning("[queen] daily brief starting — %s", now.isoformat())

    # ── Sub-agent: health check ──────────────────────────────────────────────────
    try:
        from strategy_lab.agents.strategy_monitor import run_strategy_health_check
        health = run_strategy_health_check(db)
    except Exception as exc:
        logger.error("[queen] strategy_monitor failed: %s", exc)
        health = {
            "status": "RED", "bots": [], "alpaca": {},
            "signal_rate": {}, "alerts": [f"monitor error: {exc}"]
        }

    # ── Sub-agent: research ──────────────────────────────────────────────────────
    try:
        from strategy_lab.agents.researcher import run_daily_research
        research = run_daily_research(db)
    except Exception as exc:
        logger.error("[queen] researcher failed: %s", exc)
        research = {
            "regime": {}, "signal_ic": [], "candidates": [],
            "recommendations": [f"research error: {exc}"]
        }

    # ── Build + post embed ───────────────────────────────────────────────────────
    embed = _build_embed(health, research, now)

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
            logger.warning("[queen] daily brief posted to Discord")
        else:
            logger.warning("[queen] Discord post failed — brief logged only")
    except Exception as exc:
        logger.error("[queen] Discord dispatch error: %s", exc)

    # Structured summary log regardless of Discord outcome
    logger.warning(
        "[queen] done status=%s regime=%s stale_bots=%d alerts=%d recs=%d",
        health.get("status"),
        research.get("regime", {}).get("name", "?"),
        sum(1 for b in health.get("bots", []) if b.get("status") == "STALE"),
        len(health.get("alerts", [])),
        len(research.get("recommendations", [])),
    )
