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

import json
import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Literal

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

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

_BOT_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing":                 "Stock Swing",
    "stock_day":                   "Stock Day",
    "stock_lt":                    "Stock Long-Term",
    "crypto_swing":                "Crypto Swing",
    "crypto_day":                  "Crypto Day",
    "crypto_lt":                   "Crypto Long-Term",
    "crypto_onchain":              "Crypto Onchain",
    "options_income":              "Equity Income",
    "options_directional":         "Equity Directional",
    "crypto_quant_aggressive":     "Quant Aggressive",
    "crypto_quant_mean_reversion": "Quant Mean Rev",
    "crypto_quant_scalper":        "Quant Scalper",
    "crypto_meanrev_2163":         "Mean Rev 2163",
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
            os.getenv("DISCORD_CH_QUEEN_BRIEFINGS", "")
            or os.getenv("QUEEN_BRIEF_CHANNEL_ID", "")
            or settings.discord_ch_dev_log
            or os.getenv("DISCORD_CH_DEV_LOG", "")
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
    # Exclude SKIPPED (weekend market-closed bots) from total
    active = [b for b in bots if b.get("status") != "SKIPPED"]
    total  = len(active)
    ok     = sum(1 for b in active if b.get("status") == "OK")
    stale  = [_BOT_DISPLAY_NAMES.get(b["bot"], b["bot"]) for b in active if b.get("status") == "STALE"]
    dis    = sum(1 for b in active if b.get("status") in ("DISABLED", "NO_ALLOC"))
    quiet  = sum(1 for b in active if b.get("status") == "NEVER_RAN")
    parts  = [f"{total} total", f"{ok} healthy"]
    if stale:
        parts.append(f"{len(stale)} stale: {', '.join(stale[:3])}")
    else:
        parts.append("0 stale")
    parts.append(f"{dis} disabled")
    if quiet:
        parts.append(f"{quiet} quiet")
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
    today    = pnl.get("today_cents", 0)
    dot      = "🟢" if total >= 0 else "🔴"

    today_str = f" | Today: {_fmt_pnl(today)}" if today != 0 else ""
    if evening:
        pnl_val = (
            f"{dot} **{_fmt_pnl(total)}** all-time{today_str}\n"
            f"Realized: {_fmt_pnl(realized)} | AH unrealized: {_fmt_pnl(unrealiz)} | Fees: {_fmt_pnl(-fees)}"
        )
    else:
        pnl_val = (
            f"{dot} **{_fmt_pnl(total)}** all-time{today_str}\n"
            f"Realized: {_fmt_pnl(realized)} | Unrealized: {_fmt_pnl(unrealiz)} | Fees: {_fmt_pnl(-fees)}"
        )

    winners = pnl.get("top_winners", [])
    losers  = pnl.get("top_losers", [])
    win_str = "\n".join(f"  {w['symbol']} {_fmt_pnl(w['pnl_cents'])}" for w in winners[:3]) or "—"
    los_str = "\n".join(f"  {l['symbol']} {_fmt_pnl(l['pnl_cents'])}" for l in losers[:3]) or "—"
    return [
        {"name": "Portfolio P&L",  "value": pnl_val,                                        "inline": False},
        {"name": "Closed Trades",  "value": f"{trades} trades | {open_pos} open positions",  "inline": True},
        {"name": "Top Winners",    "value": win_str,                                         "inline": True},
        {"name": "Top Losers",     "value": los_str,                                         "inline": True},
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
        "author":    {"name": "BMG Capital — Brick (Portfolio Manager)"},
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
        "author":    {"name": "BMG Capital — Brick (Portfolio Manager)"},
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
        "author":    {"name": "BMG Capital — Brick (Portfolio Manager)"},
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
        "author":    {"name": "BMG Capital — Brick (Portfolio Manager)"},
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


# ── Tier B Proposal Flow ──────────────────────────────────────────────────────

# Allocation delta used when generating IC-driven proposals
_PROPOSAL_REDUCE_PCT  = 1.5   # reduce by this much when IC degrading
_PROPOSAL_INCREASE_PCT = 1.5  # increase by this much when IC strong + regime favorable

# Proposal cooldowns
_REJECTION_COOLDOWN_HOURS = 24
_APPROVAL_COOLDOWN_HOURS  = 6


def _get_proposals_channel() -> tuple[str, str]:
    """Return (token, channel_id) for #queen-proposals, fall back to dev-log."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    proposals_ch = os.getenv("DISCORD_CH_QUEEN_PROPOSALS", "")
    fallback_ch  = os.getenv("DISCORD_CH_DEV_LOG", "")
    return token, proposals_ch or fallback_ch


def _is_proposals_fallback() -> bool:
    return not os.getenv("DISCORD_CH_QUEEN_PROPOSALS", "").strip()


def _next_proposal_id(db: Session) -> str:
    today = date.today().strftime("%Y%m%d")
    try:
        count = db.execute(
            text("SELECT COUNT(*) FROM proposal_audit WHERE DATE(generated_ts) = :d"),
            {"d": date.today().isoformat()},
        ).scalar() or 0
    except Exception:
        count = 0
    return f"PROP-{today}-{count + 1:03d}"


def _check_proposal_cooldown(db: Session, proposal_class: str) -> tuple[bool, str]:
    """
    Returns (blocked, reason). Blocked if the same class was:
    - rejected/auto_rejected in the last 24h, or
    - approved and executed in the last 6h.
    """
    try:
        rejection_cutoff = (datetime.now(timezone.utc) - timedelta(hours=_REJECTION_COOLDOWN_HOURS)).isoformat()
        approval_cutoff  = (datetime.now(timezone.utc) - timedelta(hours=_APPROVAL_COOLDOWN_HOURS)).isoformat()

        rejected = db.execute(
            text("""
                SELECT 1 FROM proposal_audit
                WHERE proposal_type = :cls
                  AND decision IN ('rejected', 'auto_rejected')
                  AND decision_ts >= :cutoff
                LIMIT 1
            """),
            {"cls": proposal_class, "cutoff": rejection_cutoff},
        ).fetchone()
        if rejected:
            return True, f"24h rejection cooldown active for {proposal_class}"

        approved = db.execute(
            text("""
                SELECT 1 FROM proposal_audit
                WHERE proposal_type = :cls
                  AND decision = 'approved'
                  AND executed_ts >= :cutoff
                LIMIT 1
            """),
            {"cls": proposal_class, "cutoff": approval_cutoff},
        ).fetchone()
        if approved:
            return True, f"6h post-approval cooldown active for {proposal_class}"

        return False, ""
    except Exception:
        return False, ""


def _check_conflict_veto(db: Session, bot_name: str) -> tuple[bool, str]:
    """
    Auto-reject if Risk Sentinel has a RED/YELLOW alert in last 30 min,
    or Data Quality Watcher has a CRITICAL alert in last 2 hours.
    """
    try:
        sentinel_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dq_cutoff       = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        cro_alert = db.execute(
            text("""
                SELECT 1 FROM agent_messages
                WHERE from_agent = 'risk_sentinel'
                  AND msg_type IN ('health', 'breach')
                  AND created_at >= :cutoff
                LIMIT 1
            """),
            {"cutoff": sentinel_cutoff},
        ).fetchone()
        if cro_alert:
            return True, "vetoed by Dick (CRO) — active risk alert"

        dq_alert = db.execute(
            text("""
                SELECT 1 FROM agent_messages
                WHERE from_agent = 'data_quality_watcher'
                  AND msg_type = 'dq_alert'
                  AND created_at >= :cutoff
                LIMIT 1
            """),
            {"cutoff": dq_cutoff},
        ).fetchone()
        if dq_alert:
            return True, "vetoed by DQW — data quality compromise on affected feed"

        return False, ""
    except Exception:
        return False, ""


def _get_bot_allocations(db: Session) -> dict[str, float]:
    """Return {bot_name: capital_pct} for all enabled bots."""
    try:
        rows = db.execute(text("""
            SELECT bp.name, ba.capital_pct
            FROM bot_allocations ba
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE ba.enabled = 1
        """)).fetchall()
        return {r[0]: float(r[1]) for r in rows}
    except Exception:
        return {}


def _get_recent_finding_id(db: Session) -> list[int]:
    """Get IDs of researcher findings from last 24h."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = db.execute(
            text("""
                SELECT id FROM agent_messages
                WHERE from_agent = 'researcher' AND msg_type = 'findings'
                  AND created_at >= :c
                ORDER BY created_at DESC LIMIT 3
            """),
            {"c": cutoff},
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _build_proposal_embed(
    proposal_id: str,
    bot_name: str,
    direction: str,   # "reduce" | "increase"
    current_pct: float,
    proposed_pct: float,
    ic: float | None,
    regime_name: str,
    finding_ids: list[int],
    is_fallback: bool,
) -> dict:
    delta = proposed_pct - current_pct
    delta_str = f"{delta:+.1f}%"
    arrow = "↓" if delta < 0 else "↑"
    color = 0xF59E0B  # amber for pending proposals

    title_prefix = "[QUEUED-PROPOSAL] " if is_fallback else ""
    ic_str = f"{ic:.3f}" if ic is not None else "N/A"

    reduce_rationale = (
        f"IC={ic_str} is below the {0.02} degradation threshold over the 63-day rolling window. "
        f"Regime: {regime_name}. Reducing exposure to protect capital in a degraded signal environment."
    )
    increase_rationale = (
        f"IC={ic_str} exceeds the {0.05} strong-signal threshold. "
        f"Regime: {regime_name} is favourable for this bot. Increasing allocation to capture alpha."
    )
    rationale = reduce_rationale if direction == "reduce" else increase_rationale

    alternative = (
        "Hold current allocation and observe for 7 more days "
        f"(risk: {'continued deployment in degraded signal env' if direction == 'reduce' else 'missed alpha in favourable regime'})"
    )

    fields = [
        {
            "name": "📋 PROPOSAL",
            "value": (
                f"{arrow} {bot_name} `capital_pct`: `{current_pct:.1f}%` → `{proposed_pct:.1f}%` "
                f"(`{delta_str}`)"
            ),
            "inline": False,
        },
        {
            "name": "🧠 RATIONALE",
            "value": rationale,
            "inline": False,
        },
        {
            "name": "📊 DERIVED FROM",
            "value": (
                ", ".join(f"researcher.findings #{fid}" for fid in finding_ids)
                or "researcher.findings (today's run)"
            ),
            "inline": False,
        },
        {
            "name": "🔀 ALTERNATIVES CONSIDERED",
            "value": alternative,
            "inline": False,
        },
        {
            "name": "✅ ON APPROVAL",
            "value": (
                f"1. Execute: `{bot_name}.capital_pct` → `{proposed_pct:.1f}%`\n"
                "2. Notify Dick (CRO)\n3. Log to proposal_audit"
            ),
            "inline": False,
        },
        {
            "name": "❌ ON REJECTION",
            "value": f"24h cooldown on `{bot_name}` allocation proposals. Logged to proposal_audit.",
            "inline": False,
        },
        {
            "name": "React to decide",
            "value": "✅ approve  ❌ reject  🕐 defer",
            "inline": False,
        },
    ]

    return {
        "author":    {"name": f"BMG Capital — Brick · Proposal"},
        "title":     f"{title_prefix}{proposal_id} | {'Reduce' if direction == 'reduce' else 'Increase'} {bot_name} allocation",
        "color":     color,
        "fields":    fields,
        "footer":    {"text": "Tier B · Awaiting CIO approval · Brick"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _write_proposal_audit(
    db: Session,
    proposal_id: str,
    proposal_type: str,
    proposed_change: dict,
    rationale: str,
    finding_ids: list[int],
    decision: str = "pending",
    decision_reason: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            text("""
                INSERT OR IGNORE INTO proposal_audit
                    (proposal_id, proposal_type, generated_ts, proposed_change,
                     rationale, derived_from_finding_ids, decision, decision_reason)
                VALUES (:pid, :ptype, :ts, :change, :rationale, :fids, :decision, :dreason)
            """),
            {
                "pid":      proposal_id,
                "ptype":    proposal_type,
                "ts":       now,
                "change":   json.dumps(proposed_change),
                "rationale": rationale,
                "fids":     json.dumps(finding_ids),
                "decision": decision,
                "dreason":  decision_reason,
            },
        )
        db.commit()
    except Exception as exc:
        logger.warning("[queen] proposal_audit write failed: %s", exc)


def _post_proposal(channel_id: str, token: str, embed: dict) -> str | None:
    """Post proposal embed to Discord, then pre-add ✅ ❌ 🕐 so CIO can one-click react."""
    if not channel_id or not token:
        return None
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
    }
    try:
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers=headers,
            json={"embeds": [embed]},
            timeout=10,
        )
        if not resp.is_success:
            logger.warning("[queen] proposal Discord post failed: %s", resp.status_code)
            return None
        message_id = str(resp.json().get("id", ""))
    except Exception as exc:
        logger.warning("[queen] proposal post error: %s", exc)
        return None

    # Pre-add reactions so CIO just clicks — 0.6s apart to stay under rate limit
    import time, urllib.parse
    for emoji in ["✅", "❌", "🕐"]:
        try:
            encoded = urllib.parse.quote(emoji)
            httpx.put(
                f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
                headers=headers,
                timeout=5,
            )
            time.sleep(0.6)
        except Exception:
            pass

    return message_id


def _generate_synthetic_proposal(db: Session) -> list[dict]:
    """Post one hardcoded test proposal so the full Discord→reaction→executor path can be verified."""
    allocations = _get_bot_allocations(db)
    token, proposals_ch = _get_proposals_channel()
    is_fallback = _is_proposals_fallback()

    # Pick the first available bot; fall back to a placeholder name if none configured.
    bot = next(iter(allocations), "crypto_quant_aggressive")
    current_pct = allocations.get(bot, 10.0)
    proposed_pct = round(min(85.0, current_pct + 2.0), 2)
    direction = "increase"
    ic_val = 0.072  # synthetic IC above strong threshold
    regime_name = "bull_crypto"

    finding_ids = _get_recent_finding_id(db)
    proposal_id = _next_proposal_id(db)

    proposed_change = {
        "type": "allocation_change",
        "bot": bot,
        "field": "capital_pct",
        "current_value": current_pct,
        "proposed_value": proposed_pct,
        "delta": round(proposed_pct - current_pct, 2),
        "synthetic": True,
    }
    rationale = f"[SYNTHETIC TEST] IC={ic_val:.3f} strong; regime={regime_name}; force_synthetic=true"
    _write_proposal_audit(db, proposal_id, "allocation_change_increase", proposed_change, rationale, finding_ids)

    embed = _build_proposal_embed(
        proposal_id, bot, direction, current_pct, proposed_pct,
        ic_val, regime_name, finding_ids, is_fallback,
    )
    try:
        from agents.plain_english import translate_for_brock, make_plain_english_field
        _pe_text = " | ".join(
            f"{f['name']}: {f['value']}" for f in embed.get("fields", [])
            if not f['name'].startswith("💬")
        )
        _pe = translate_for_brock(_pe_text, db=db, channel_id=proposals_ch, charge_agent="queen")
        if _pe:
            embed["fields"].append(make_plain_english_field(_pe))
    except Exception as _pe_exc:
        logger.debug("[queen] plain_english (synthetic proposal) failed: %s", _pe_exc)
    message_id = _post_proposal(proposals_ch, token, embed)

    if message_id:
        try:
            db.execute(
                text("""
                    UPDATE proposal_audit
                    SET posted_message_id = :mid, posted_channel_id = :cid
                    WHERE proposal_id = :pid
                """),
                {"mid": message_id, "cid": proposals_ch, "pid": proposal_id},
            )
            db.commit()
        except Exception as exc:
            logger.warning("[queen] synthetic proposal message_id update failed: %s", exc)

    result = {
        "proposal_id": proposal_id,
        "bot": bot,
        "direction": direction,
        "current_pct": current_pct,
        "proposed_pct": proposed_pct,
        "synthetic": True,
        "posted": message_id is not None,
        "channel": proposals_ch,
    }
    logger.info("[queen] synthetic proposal posted: %s", proposal_id)
    return [result]


def _generate_proposals(db: Session, *, research: dict, health: dict, synthetic: bool = False) -> list[dict]:
    """
    Generate Tier B proposals based on current research findings.
    Called after the morning briefing. Returns list of proposal dicts.
    Pass synthetic=True to bypass IC threshold and post a hardcoded test proposal.
    """
    if synthetic:
        return _generate_synthetic_proposal(db)

    now = datetime.now(timezone.utc)
    ic_summary   = research.get("signal_ic", [])
    regime       = research.get("regime", {})
    regime_name  = regime.get("name", "unknown")
    allocations  = _get_bot_allocations(db)
    finding_ids  = _get_recent_finding_id(db)
    token, proposals_ch = _get_proposals_channel()
    is_fallback  = _is_proposals_fallback()

    proposals_posted: list[dict] = []

    actionable = [e for e in ic_summary if e.get("status") in ("degrading", "strong")]
    threshold_met = len(actionable) > 0
    reason = (
        f"{len(actionable)} bot(s) with actionable IC status (degrading/strong)"
        if threshold_met
        else (
            "no IC entries" if not ic_summary
            else f"all {len(ic_summary)} IC entries have normal status (not degrading/strong)"
        )
    )
    logger.warning(
        "[queen-proposal] check triggered. threshold_met=%s. reason=%s",
        threshold_met, reason,
    )
    logger.warning(
        "[queen] proposal check: %d IC entries total, %d actionable (degrading/strong)",
        len(ic_summary), len(actionable),
    )
    if not actionable:
        logger.warning("[queen] no proposals generated — all bots healthy or insufficient IC data")

    for ic_entry in ic_summary:
        bot      = ic_entry.get("bot", "")
        ic_val   = ic_entry.get("ic")
        status   = ic_entry.get("status", "")
        current_pct = allocations.get(bot)

        if current_pct is None:
            continue  # bot not in active allocations

        direction = None
        if status == "degrading":
            direction = "reduce"
        elif status == "strong":
            from strategy_lab.agents.researcher import _REGIME_BEST_BOTS
            if bot in _REGIME_BEST_BOTS.get(regime_name, []):
                direction = "increase"
            else:
                logger.warning(
                    "[queen-proposal] bot=%s IC strong (ic=%s) but NOT in regime best-bots for regime=%s — skipping increase",
                    bot, ic_val, regime_name,
                )

        if direction is None:
            if status not in ("degrading", "strong"):
                logger.warning(
                    "[queen-proposal] bot=%s skipped — IC status=%s (ic=%s) does not trigger a proposal",
                    bot, status, ic_val,
                )
            continue

        proposed_pct = round(
            current_pct - _PROPOSAL_REDUCE_PCT if direction == "reduce"
            else current_pct + _PROPOSAL_INCREASE_PCT,
            2,
        )
        # Clamp to sane bounds
        proposed_pct = max(0.5, min(85.0, proposed_pct))

        delta = abs(proposed_pct - current_pct)
        proposal_class = f"allocation_change_{direction}"
        proposal_id = _next_proposal_id(db)

        # Pre-flight: Tier C hard cap
        from agents.executors.execute_allocation_change import MAX_SINGLE_CHANGE_PCT
        if delta > MAX_SINGLE_CHANGE_PCT:
            _write_proposal_audit(
                db, proposal_id, proposal_class,
                {"type": "allocation_change", "bot": bot,
                 "current_value": current_pct, "proposed_value": proposed_pct},
                f"Auto-rejected: delta {delta:.2f}% > Tier C cap {MAX_SINGLE_CHANGE_PCT}%",
                finding_ids, decision="auto_rejected",
                decision_reason=f"Tier C hard cap: delta {delta:.2f}% > {MAX_SINGLE_CHANGE_PCT}%",
            )
            logger.info("[queen] proposal auto-rejected (tier_c): %s %s", bot, direction)
            continue

        # Pre-flight: cooldown
        blocked, reason = _check_proposal_cooldown(db, proposal_class)
        if blocked:
            logger.info("[queen] proposal skipped (cooldown): %s — %s", bot, reason)
            continue

        # Pre-flight: conflict veto
        vetoed, veto_reason = _check_conflict_veto(db, bot)
        if vetoed:
            _write_proposal_audit(
                db, proposal_id, proposal_class,
                {"type": "allocation_change", "bot": bot,
                 "current_value": current_pct, "proposed_value": proposed_pct},
                veto_reason, finding_ids,
                decision="auto_rejected", decision_reason=veto_reason,
            )
            logger.info("[queen] proposal auto-rejected (veto): %s — %s", bot, veto_reason)
            continue

        # Write pending record first
        proposed_change = {
            "type": "allocation_change",
            "bot": bot,
            "field": "capital_pct",
            "current_value": current_pct,
            "proposed_value": proposed_pct,
            "delta": round(proposed_pct - current_pct, 2),
        }
        rationale_text = (
            f"IC={ic_val:.3f} degrading (threshold {0.02}); regime={regime_name}" if direction == "reduce"
            else f"IC={ic_val:.3f} strong (threshold {0.05}); regime={regime_name} favours {bot}"
        )
        _write_proposal_audit(
            db, proposal_id, proposal_class, proposed_change,
            rationale_text, finding_ids,
        )

        # Post to Discord
        embed = _build_proposal_embed(
            proposal_id, bot, direction, current_pct, proposed_pct,
            ic_val, regime_name, finding_ids, is_fallback,
        )
        try:
            from agents.plain_english import translate_for_brock, make_plain_english_field
            _pe_text = " | ".join(
                f"{f['name']}: {f['value']}" for f in embed.get("fields", [])
                if not f['name'].startswith("💬")
            )
            _pe = translate_for_brock(_pe_text, db=db, channel_id=proposals_ch, charge_agent="queen")
            if _pe:
                embed["fields"].append(make_plain_english_field(_pe))
        except Exception as _pe_exc:
            logger.debug("[queen] plain_english (proposal) failed: %s", _pe_exc)
        message_id = _post_proposal(proposals_ch, token, embed)

        # Record message_id in audit table
        if message_id:
            try:
                db.execute(
                    text("""
                        UPDATE proposal_audit
                        SET posted_message_id = :mid, posted_channel_id = :cid
                        WHERE proposal_id = :pid
                    """),
                    {"mid": message_id, "cid": proposals_ch, "pid": proposal_id},
                )
                db.commit()
            except Exception as exc:
                logger.warning("[queen] proposal message_id update failed: %s", exc)

        # Publish to bus
        try:
            from agents.bus import publish as _pub
            from agents.channels import PROPOSALS
            _pub(
                db, channel=PROPOSALS, from_agent="queen",
                msg_type="proposal",
                subject=f"{proposal_id}: {direction} {bot} {current_pct:.1f}%→{proposed_pct:.1f}%",
                payload={"proposal_id": proposal_id, "proposed_change": proposed_change},
                priority=7,
            )
        except Exception:
            pass

        proposals_posted.append({
            "proposal_id": proposal_id,
            "bot": bot,
            "direction": direction,
            "current_pct": current_pct,
            "proposed_pct": proposed_pct,
            "posted": message_id is not None,
            "fallback_channel": is_fallback,
        })
        logger.warning(
            "[queen] proposal posted: %s %s %.1f%%→%.1f%% (msg_id=%s)",
            proposal_id, bot, current_pct, proposed_pct, message_id,
        )

    return proposals_posted


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
    try:
        from agents.plain_english import translate_for_brock, make_plain_english_field
        _pe_text = " | ".join(
            f"{f['name']}: {f['value']}" for f in embed.get("fields", [])
            if not f['name'].startswith("💬")
        )
        _pe = translate_for_brock(_pe_text, db=db, channel_id=channel_id, charge_agent="queen")
        if _pe:
            embed["fields"].append(make_plain_english_field(_pe))
    except Exception as _pe_exc:
        logger.debug("[queen] plain_english failed: %s", _pe_exc)
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

    # Proposal generation — morning session only
    if session == "morning":
        try:
            _proposal_capped = False
            try:
                from agents.bus import is_budget_capped as _capped
                if _capped(db):
                    logger.info("[queen] daily budget cap hit — skipping LLM call")
                    _proposal_capped = True
            except Exception:
                pass

            if not _proposal_capped:
                generated = _generate_proposals(db, research=research, health=health)
                if generated:
                    logger.warning("[queen] generated %d proposal(s) this morning", len(generated))
                    try:
                        from agents.bus import charge_api_usage as _charge
                        _charge(db, "queen", 0.001)
                    except Exception:
                        pass
        except Exception as exc:
            logger.error("[queen] proposal generation failed: %s", exc)

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
            subject=f"Brick {session} brief — {now.strftime('%Y-%m-%d')}",
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
    logger.warning("[queen-regime-alert] run_regime_alert_check fired at %s", datetime.now(timezone.utc).isoformat())

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
        logger.warning("[queen-regime-alert] no alerts returned by check_regime_alert_signals — nothing to post")
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
        try:
            from agents.plain_english import translate_for_brock, make_plain_english_field
            _pe_text = " | ".join(
                f"{f['name']}: {f['value']}" for f in embed.get("fields", [])
                if not f['name'].startswith("💬")
            )
            _pe = translate_for_brock(_pe_text, db=db, channel_id=channel_id, charge_agent="queen")
            if _pe:
                embed["fields"].append(make_plain_english_field(_pe))
        except Exception as _pe_exc:
            logger.debug("[queen] plain_english (regime_alert) failed: %s", _pe_exc)
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
