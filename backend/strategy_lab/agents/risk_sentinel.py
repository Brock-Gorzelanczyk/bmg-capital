"""
Risk Sentinel — Deploy 2 Tier A autonomous risk watchdog.

Monitors drawdown, fleet health, and position concentration.
Holds veto power over Portfolio Manager.
Runs every 30 minutes — posts to #risk-alerts when YELLOW or RED.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Risk thresholds
DRAWDOWN_WARN_PCT     = 8.0   # YELLOW — 30d drawdown %
DRAWDOWN_HALT_PCT     = 15.0  # RED — 30d drawdown %
CONSEC_LOSS_WARN      = 4     # YELLOW — consecutive losing days
CONSEC_LOSS_HALT      = 7     # RED — consecutive losing days
CONSEC_LOSS_RED       = 3     # RED — 3+ consecutive losses is active P&L damage
STALE_BOT_WARN        = 2     # YELLOW if 2+ bots stale
STALE_BOT_RED         = 3     # YELLOW with scanner note — stale ≠ losing; stays YELLOW unless combined with losses
STALE_BOT_CRITICAL    = 5     # CRITICAL+@here if 5+ bots stale
CRITICAL_DRAWDOWN_PCT = -4.0  # 24h drawdown worse than this → CRITICAL
DRAWDOWN_24H_RED_PCT  = -2.0  # 24h drawdown worse than -2% → RED
FLEET_PAUSE_24H_PCT   = -3.0  # 24h pct required before "fleet pause" language is used
FLEET_AUM_PAUSE_PCT   = -1.0  # 30d P&L as % of fleet AUM — below this, no pause language

_ALERT_COOLDOWN_HOURS = 6

# In-memory dedup: level → (last_fired_at, trigger_frozenset)
# Replaces DB-backed sentinel_cooldown table which silently failed on SQLite.
_alert_state: dict[str, tuple[datetime, frozenset]] = {}

# Hash-key dedup: (severity, top-3-triggers-tuple) → last_fired_at
# Suppresses re-posts for identical (severity, trigger) combos within cooldown window.
_alert_hash_state: dict[tuple, datetime] = {}


def _get_sentinel_state(db: Session, level: str) -> tuple[Optional[datetime], frozenset]:
    entry = _alert_state.get(level)
    if entry:
        return entry
    return None, frozenset()


def _set_sentinel_state(db: Session, level: str, ts: datetime, triggers: frozenset) -> None:
    _alert_state[level] = (ts, triggers)


def _get_channel() -> tuple[str, str]:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = (
        os.getenv("DISCORD_CH_RISK_ALERTS", "")
        or os.getenv("DISCORD_CH_DEV_LOG", "")
    )
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return token, channel_id


def _post(channel_id: str, token: str, embed: dict, content: str = "") -> bool:
    if not channel_id or not token:
        return False
    import httpx
    try:
        payload: dict = {"embeds": [embed]}
        if content:
            payload["content"] = content
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
            },
            json=payload,
            timeout=10,
        )
        return resp.is_success
    except Exception as exc:
        logger.warning("[risk_sentinel] Discord post failed: %s", exc)
        return False


def _get_fleet_drawdown(db: Session) -> dict:
    """Compute max drawdown across all active bots from bot_daily_pnl."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        rows = db.execute(text("""
            SELECT bp.name, SUM(bdp.realized_cents + COALESCE(bdp.unrealized_cents, 0)) as total_pnl,
                   MIN(bdp.realized_cents + COALESCE(bdp.unrealized_cents, 0)) as worst_day
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON ba.id = bdp.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bdp.date >= :cutoff AND ba.enabled = 1
            GROUP BY bp.name
        """), {"cutoff": cutoff}).fetchall()

        _raw_total = sum((r[1] or 0) for r in rows) / 100 if rows else 0
        logger.warning("[risk_sentinel] 30d pnl fetch result: %d rows, value=%s", len(rows), f"${_raw_total:+,.2f}" if rows else "None")

        bots = []
        total_pnl = 0
        for row in rows:
            pnl_usd = (row[1] or 0) / 100
            bots.append({"bot": row[0], "pnl_usd": round(pnl_usd, 2), "worst_day_usd": round((row[2] or 0) / 100, 2)})
            total_pnl += pnl_usd

        aum_row = db.execute(text(
            "SELECT SUM(allocated_cents) FROM bot_allocations WHERE enabled = 1"
        )).fetchone()
        fleet_aum_usd = round((aum_row[0] or 0) / 100, 2) if aum_row and aum_row[0] else 50_000.0

        return {"bots": bots, "total_pnl_usd": round(total_pnl, 2), "fleet_aum_usd": fleet_aum_usd}
    except Exception as exc:
        logger.warning("[risk_sentinel] drawdown query failed: %s", exc)
        return {"bots": [], "total_pnl_usd": 0, "fleet_aum_usd": 50_000.0}


def _get_consecutive_losses(db: Session) -> dict[str, int]:
    """Count consecutive losing days per bot."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
        rows = db.execute(text("""
            SELECT bp.name, bdp.date,
                   (bdp.realized_cents + COALESCE(bdp.unrealized_cents, 0)) as day_pnl
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON ba.id = bdp.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bdp.date >= :cutoff AND ba.enabled = 1
            ORDER BY bp.name, bdp.date DESC
        """), {"cutoff": cutoff}).fetchall()

        streaks: dict[str, int] = {}
        by_bot: dict[str, list] = {}
        for r in rows:
            by_bot.setdefault(r[0], []).append(r[2])

        for bot, pnls in by_bot.items():
            streak = 0
            for p in pnls:  # already sorted desc (most recent first)
                if p < 0:
                    streak += 1
                else:
                    break
            streaks[bot] = streak

        return streaks
    except Exception as exc:
        logger.warning("[risk_sentinel] consec_loss query failed: %s", exc)
        return {}


def _get_stale_bots(db: Session) -> list[str]:
    """Return names of bots that haven't fired a signal recently."""
    try:
        from strategy_lab.agents.strategy_monitor import run_strategy_health_check
        health = run_strategy_health_check(db)
        return [b["bot"] for b in health.get("bots", []) if b.get("status") == "STALE"]
    except Exception:
        return []


def _get_fleet_drawdown_24h(db: Session) -> float:
    """
    Compute the fleet's 24h P&L as a percentage of starting capital.
    Returns a negative float (e.g. -5.2 means -5.2%) when losing, 0.0 on error.
    Starting capital is estimated as the sum of all active allocation amounts.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = db.execute(text("""
            SELECT SUM(bt.pnl_cents) as pnl_24h,
                   SUM(ba.allocated_cents) as starting_capital
            FROM bot_trades bt
            JOIN bot_allocations ba ON ba.id = bt.allocation_id
            WHERE bt.closed_at >= :since AND ba.enabled = 1
        """), {"since": since}).fetchone()

        if not row or not row[1] or row[1] == 0:
            return 0.0

        pnl_24h = (row[0] or 0) / 100.0
        starting_capital = row[1] / 100.0
        return round(pnl_24h / starting_capital * 100, 4)
    except Exception as exc:
        logger.warning("[risk_sentinel] 24h drawdown query failed: %s", exc)
        return 0.0


def _classify(drawdown_pct: float, consec_losses: int, stale_count: int,
              drawdown_24h_pct: float = 0.0, circuit_breaker_tripped: bool = False,
              triggers: list[str] | None = None) -> str:
    """
    Escalation matrix (stale bots ≠ losing bots):
      CRITICAL: 24h dd ≤ -4%, or circuit breaker, or 5+ stale, or stale + losing combo
      RED:      3+ consecutive losses, or 24h dd ≤ -2%, or 30d dd ≥ 15%, or 7+ consec losses
      YELLOW:   3+ stale bots (technical issue — investigate scanners), or warn thresholds
      GREEN:    everything else
    """
    t = triggers if triggers is not None else []

    if drawdown_24h_pct <= CRITICAL_DRAWDOWN_PCT:
        t.append("critical_24h_drawdown")
        return "CRITICAL"
    if circuit_breaker_tripped:
        t.append("circuit_breaker")
        return "CRITICAL"
    if stale_count >= STALE_BOT_CRITICAL:
        t.append("critical_stale_count")
        return "CRITICAL"
    # Stale + actively losing = CRITICAL (two failure modes simultaneously)
    if stale_count >= STALE_BOT_RED and consec_losses >= CONSEC_LOSS_RED:
        t.append("stale_and_losing")
        return "CRITICAL"

    # RED: actual P&L damage only
    if drawdown_pct >= DRAWDOWN_HALT_PCT or consec_losses >= CONSEC_LOSS_HALT:
        t.append("pnl_halt_threshold")
        return "RED"
    if consec_losses >= CONSEC_LOSS_RED:
        t.append("consecutive_losses")
        return "RED"
    if drawdown_24h_pct <= DRAWDOWN_24H_RED_PCT:
        t.append("drawdown_24h")
        return "RED"

    # YELLOW: stale bots are a technical issue, not a P&L event
    if stale_count >= STALE_BOT_RED:
        t.append("stale_bots_only")
        return "YELLOW"
    if drawdown_pct >= DRAWDOWN_WARN_PCT or consec_losses >= CONSEC_LOSS_WARN or stale_count >= STALE_BOT_WARN:
        t.append("warn_threshold")
        return "YELLOW"

    return "GREEN"


def _build_embed(level: str, summary: dict, now: datetime) -> dict:
    colors = {
        "GREEN":    0x16A34A,
        "YELLOW":   0xF59E0B,
        "RED":      0xDC2626,
        "CRITICAL": 0x7F1D1D,
    }
    icons = {
        "GREEN":    "✅",
        "YELLOW":   "⚠️",
        "RED":      "🚨",
        "CRITICAL": "🔴",
    }
    titles = {
        "GREEN":    f"Risk Health Check — {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "YELLOW":   f"Risk Health Check — {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "RED":      "🚨 Dick (CRO) — RED ALERT",
        "CRITICAL": "🔴 Dick (CRO) — CRITICAL ALERT",
    }
    pnl_value = (
        f"${summary['total_pnl_usd']:+,.2f}"
        if summary.get("pnl_data_available", True)
        else "DATA_MISSING — could not compute fleet P&L"
    )
    fields = [
        {"name": f"{icons[level]} Risk Level", "value": level, "inline": True},
        {"name": "Fleet P&L (30d)",            "value": pnl_value, "inline": True},
        {"name": "Stale Bots",                 "value": str(summary["stale_count"]), "inline": True},
    ]
    if summary.get("fleet_drawdown_24h_pct") is not None and summary["fleet_drawdown_24h_pct"] != 0.0:
        fields.append({
            "name":   "Fleet Drawdown (24h)",
            "value":  f"{summary['fleet_drawdown_24h_pct']:.2f}%",
            "inline": True,
        })
    if summary.get("worst_consec"):
        bot, n = summary["worst_consec"]
        fields.append({"name": "Consecutive Losses", "value": f"{bot}: {n} days", "inline": True})
    if summary.get("red_bots"):
        fields.append({"name": "⚠️ Bots at Risk", "value": ", ".join(summary["red_bots"][:5]), "inline": False})
    if level in ("YELLOW", "RED") and "stale_bots_only" in summary.get("triggers", []):
        fields.append({
            "name":   "INVESTIGATE — NOT A P&L EVENT",
            "value":  f"{summary.get('stale_count', 0)} bots stale — scanner health issue, not trading losses. "
                      "Review scanner logs and restart processes. No trading action warranted.",
            "inline": False,
        })
    elif level == "RED":
        triggers   = summary.get("triggers", [])
        dd24       = summary.get("fleet_drawdown_24h_pct", 0.0)
        total_pnl  = summary.get("total_pnl_usd", 0.0)
        fleet_aum  = summary.get("fleet_aum_usd", 50_000.0)
        pnl_30d_pct = (total_pnl / fleet_aum * 100) if fleet_aum else 0.0

        if dd24 <= FLEET_PAUSE_24H_PCT:
            action = (f"Fleet pause warranted — 24h drawdown {dd24:.2f}% exceeds -{abs(FLEET_PAUSE_24H_PCT):.0f}% threshold. "
                      "Halt all trading and review open positions immediately.")
        elif "consecutive_losses" in triggers and pnl_30d_pct <= FLEET_AUM_PAUSE_PCT:
            action = ("Pause underperforming bots — 30d P&L below -1% AUM threshold with "
                      f"{summary.get('worst_consec', ('?', '?'))[1]}+ consecutive losses. "
                      "Review individual bot allocations before re-enabling.")
        elif "drawdown_24h" in triggers:
            action = (f"24h drawdown elevated ({dd24:.2f}%). Review allocations and monitor closely. "
                      "No pause warranted yet — reassess in 4h.")
        else:
            action = ("Review and monitor. 30d P&L above pause threshold — "
                      "track for 24h before taking any trading action.")
        fields.append({"name": "ACTION REQUIRED", "value": action, "inline": False})
    if level == "CRITICAL":
        reason_parts = []
        dd24 = summary.get("fleet_drawdown_24h_pct", 0.0)
        if dd24 <= CRITICAL_DRAWDOWN_PCT:
            reason_parts.append(f"24h drawdown {dd24:.2f}% exceeds threshold ({CRITICAL_DRAWDOWN_PCT}%)")
        if summary.get("circuit_breaker_tripped"):
            reason_parts.append("Circuit breaker tripped")
        stale_ct = len(summary.get("stale_bots", []))
        if stale_ct >= STALE_BOT_CRITICAL:
            reason_parts.append(f"{stale_ct} bots stale ≥{STALE_BOT_CRITICAL} threshold — trading layer may be down")
        fields.append({
            "name":   "🔴 CRITICAL TRIGGER",
            "value":  " | ".join(reason_parts) if reason_parts else "Threshold exceeded",
            "inline": False,
        })
        triggers_set = set(summary.get("triggers", []))
        if "stale_and_losing" in triggers_set and abs(summary.get("total_pnl_usd", 0)) < 500:
            critical_action = (
                "Stale scanners + losing streak detected. Investigate scanner health and "
                "review crypto_meanrev allocation. P&L impact minimal — no trading halt warranted."
            )
        elif "critical_stale_count" in triggers_set:
            critical_action = (
                "5+ bots stale — trading layer may be down. Check APScheduler logs and "
                "verify Alpaca/exchange connectivity. Pause new entries until resolved."
            )
        else:
            critical_action = "Review and halt trading if drawdown exceeds -4% of AUM. Verify positions immediately."
        fields.append({
            "name":   "IMMEDIATE ACTION REQUIRED",
            "value":  critical_action,
            "inline": False,
        })
    return {
        "author":    {"name": "BMG Capital — Dick (Chief Risk Officer)"},
        "title":     titles[level],
        "color":     colors[level],
        "fields":    fields,
        "footer":    {"text": "Dick (CRO) · Tier A autonomous · Every 30 min"},
        "timestamp": now.isoformat(),
    }


def run_risk_health_check(db: Session) -> dict:
    """
    Main entry point — called every 30 min by APScheduler.
    Posts to #risk-alerts on YELLOW or RED. Returns risk dict.
    """
    now = datetime.now(timezone.utc)

    try:
        from agents.bus import heartbeat as _hb
        _hb(db, agent_id="risk_sentinel")
    except Exception:
        pass

    drawdown      = _get_fleet_drawdown(db)
    streaks       = _get_consecutive_losses(db)
    stale         = _get_stale_bots(db)
    drawdown_24h  = _get_fleet_drawdown_24h(db)

    # Find worst drawdown as percentage of starting capital
    worst_dd_pct = 0.0
    total_pnl_usd = drawdown["total_pnl_usd"]
    if total_pnl_usd < 0:
        # rough estimate: fleet ~$50k starting → %drawdown
        worst_dd_pct = abs(total_pnl_usd) / 50_000 * 100

    worst_consec = max(streaks.items(), key=lambda x: x[1]) if streaks else None
    consec_max   = worst_consec[1] if worst_consec else 0

    red_bots = [b for b, n in streaks.items() if n >= CONSEC_LOSS_WARN]
    triggers: list[str] = []
    level = _classify(
        worst_dd_pct, consec_max, len(stale),
        drawdown_24h_pct=drawdown_24h,
        circuit_breaker_tripped=False,
        triggers=triggers,
    )

    fleet_aum_usd = drawdown.get("fleet_aum_usd", 50_000.0)
    pnl_data_available = bool(drawdown.get("bots"))
    if not pnl_data_available:
        logger.warning("[risk_sentinel] bot_daily_pnl has no rows in last 30d — P&L shown as DATA_MISSING")
    summary = {
        "level":                  level,
        "triggers":               triggers,
        "total_pnl_usd":          total_pnl_usd,
        "pnl_data_available":     pnl_data_available,
        "fleet_aum_usd":          fleet_aum_usd,
        "worst_dd_pct":           round(worst_dd_pct, 2),
        "fleet_drawdown_24h_pct": drawdown_24h,
        "stale_count":            len(stale),
        "stale_bots":             stale,
        "worst_consec":           worst_consec,
        "red_bots":               red_bots,
        "circuit_breaker_tripped": False,
    }

    logger.info(
        "[risk_sentinel] level=%s dd=%.1f%% dd_24h=%.2f%% stale=%d consec=%d",
        level, worst_dd_pct, drawdown_24h, len(stale), consec_max,
    )

    # Post to Discord: skip GREEN; YELLOW posts embed only; RED adds @CIO mention;
    # CRITICAL adds @CIO @here mention. All respect the cooldown + trigger dedup.
    if level in ("YELLOW", "RED", "CRITICAL"):
        last_ts, last_trigger = _get_sentinel_state(db, level)
        current_trigger = frozenset(triggers)
        elapsed = (now - last_ts).total_seconds() if last_ts else float("inf")

        # Build content-based hash key: (severity, top-3 triggers sorted)
        # This suppresses identical alerts even if minor trigger details shift.
        top_3_triggers = sorted(triggers)[:3]
        hash_key = (level, tuple(top_3_triggers))
        hash_last_ts = _alert_hash_state.get(hash_key)
        hash_elapsed = (now - hash_last_ts).total_seconds() if hash_last_ts else float("inf")

        # Suppress if same hash_key posted within cooldown window,
        # OR same full trigger fingerprint within cooldown (legacy path).
        _same_hash = hash_elapsed < _ALERT_COOLDOWN_HOURS * 3600
        _same_trigger = elapsed < _ALERT_COOLDOWN_HOURS * 3600 and current_trigger == last_trigger

        if _same_hash or _same_trigger:
            logger.info("[risk-dedup] suppressed: %s", hash_key)
            logger.info(
                "[risk_sentinel] %s suppressed — same trigger %s within %dh cooldown (%.1fh elapsed)",
                level, sorted(current_trigger), _ALERT_COOLDOWN_HOURS, elapsed / 3600,
            )
        else:
            _alert_hash_state[hash_key] = now
            _set_sentinel_state(db, level, now, current_trigger)
            token, ch = _get_channel()
            cio_id = os.getenv("CIO_DISCORD_USER_ID", "")
            embed = _build_embed(level, summary, now)

            try:
                from agents.plain_english import translate_for_brock, make_plain_english_field
                _pe_text = " | ".join(f"{f['name']}: {f['value']}" for f in embed.get("fields", []) if not f['name'].startswith("💬"))
                _pe = translate_for_brock(_pe_text, db=db, channel_id=ch, charge_agent="risk_sentinel")
                if _pe:
                    embed["fields"].append(make_plain_english_field(_pe))
            except Exception as _e:
                logger.debug("[risk_sentinel] plain_english failed: %s", _e)

            mentions = os.getenv("DISCORD_CIO_MENTIONS", f"<@{cio_id}>" if cio_id else "").strip()
            content = ""
            if level == "RED":
                content = mentions
            elif level == "CRITICAL":
                content = f"{mentions} @here".strip()

            if _post(ch, token, embed, content=content):
                logger.warning("[risk_sentinel] %s alert posted to Discord", level)
            else:
                logger.warning("[risk_sentinel] %s alert — Discord post failed", level)

    # Publish to bus
    try:
        from agents.bus import publish as _bus_publish
        from agents.channels import SENTINEL_HEALTH, SENTINEL_BREACH
        bus_priority = 10 if level == "CRITICAL" else (8 if level == "RED" else 5)
        _bus_publish(db, channel=SENTINEL_HEALTH, from_agent="risk_sentinel",
                     msg_type="health", subject=f"Risk check: {level}",
                     payload=summary, priority=bus_priority)
        if level in ("RED", "CRITICAL"):
            _bus_publish(db, channel=SENTINEL_BREACH, from_agent="risk_sentinel",
                         to_agent="queen", msg_type="breach",
                         subject=f"RISK BREACH: {level}", payload=summary,
                         priority=10 if level == "CRITICAL" else 9)
    except Exception as exc:
        logger.debug("[risk_sentinel] bus publish skipped: %s", exc)

    # Proactive observation: if any metric is within 20% of a threshold, observe
    try:
        from agents.bus import observe as _obs
        fleet_pnl = summary.get("fleet_pnl_30d_pct", 0)
        WARN_THRESHOLD = -0.4  # 80% of the -0.5% alert threshold
        if fleet_pnl <= WARN_THRESHOLD and level == "GREEN":
            _obs(db, agent_id="risk_sentinel",
                 content=f"Fleet P&L approaching threshold: {fleet_pnl:.2f}% (alert at -0.5%). No action needed yet — monitoring.",
                 context={"fleet_pnl_30d_pct": fleet_pnl})
    except Exception:
        pass

    # Daily check-in to #fund-team-chat
    try:
        from agents.bus import post_daily_checkin as _checkin
        dd = abs(summary.get("worst_dd_pct", 0))
        _checkin(db, "risk_sentinel",
                 f"Dick (CRO): Risk check {level} — Fleet 30d P&L ${summary['total_pnl_usd']:+,.0f}, "
                 f"max drawdown {dd:.1f}%, {summary['stale_count']} stale bots. "
                 f"{'No flags raised.' if level == 'GREEN' else 'Elevated — see #risk-alerts.'}")
    except Exception:
        pass

    # Post paste-ready demotion requests to #fund-updates for bots with 7+ consecutive losses
    _DEMOTION_THRESHOLD = 7
    try:
        from agents.bus import post_update_request as _upd
        severe_losers = [(b, n) for b, n in streaks.items() if n >= _DEMOTION_THRESHOLD]
        for bot_name, loss_count in severe_losers:
            date_str = now.strftime("%Y-%m-%d")
            date_compact = now.strftime("%Y%m%d")
            _upd(
                from_agent="risk_sentinel",
                title=f"{bot_name} — {loss_count} consecutive losses, tier demotion needed",
                body=(
                    f"{bot_name} has logged {loss_count} consecutive losing days with no recovery. "
                    f"Routing and config checks already passed. This is a strategy failure, not a plumbing issue. "
                    f"Recommend demoting one tier to pull it off live capital."
                ),
                paste_ready=(
                    f"Demote {bot_name} one tier (e.g. T2 → T1 or T1 → T0) to take it off live capital. "
                    f"It has {loss_count} consecutive losing days as of {date_str}. "
                    f"Check bot_allocations in the DB and set tier = 'T1' (or T0 if already T1). "
                    f"Also set paused_reason = 'consecutive_loss_demotion_{date_compact}' so it shows as paused in the UI."
                ),
                priority="high" if loss_count >= CONSEC_LOSS_HALT else "normal",
            )
    except Exception as exc:
        logger.debug("[risk_sentinel] update_request post failed: %s", exc)

    return summary
