"""
Daily Briefing Email — sends at 8am ET weekdays.

Subject: "BMG Daily — Yesterday ±$X across 6 bots"

Content:
  - Yesterday's combined P&L across all active bots
  - Today's regime snapshot (VIX level, trend, BTC dominance)
  - Per-bot section for each active allocation:
    - Bot name + status
    - Yesterday's P&L + open position count
    - Top 5 watchlist names
    - Any anomalies or health alerts
  - Today's catalyst calendar (FOMC, CPI, NFP, earnings)
  - "Questions for you" count
  - CTAs: Open Command Center | Pause All | Ask Co-Pilot

Uses Resend (already in deps) if RESEND_API_KEY set.
Falls back to print/log if not configured.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://bmgcapital.app")


def _format_pnl(cents: int) -> str:
    """Format cents into a signed dollar string like '+$1,234.56' or '-$45.00'."""
    usd = cents / 100
    sign = "+" if usd >= 0 else "-"
    return f"{sign}${abs(usd):,.2f}"


def _pnl_color(cents: int) -> str:
    return "#16a34a" if cents >= 0 else "#dc2626"


def generate_briefing_html(user_id: int, db: Session) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    from app.db.models.bots import (
        BotAllocation,
        BotProfile,
        BotDailyPnL,
        BotWatchlist,
        BotHealth,
        BotPosition,
        RegimeSnapshot,
        AnomalyEvent,
        CatalystEvent,
    )

    yesterday = date.today() - timedelta(days=1)
    yesterday_start = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
    yesterday_end = yesterday_start + timedelta(days=1)

    # ── Active allocations for this user ─────────────────────────────────────
    allocations = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == user_id,
            BotAllocation.enabled.is_(True),
        )
        .all()
    )

    # ── Combined yesterday P&L ────────────────────────────────────────────────
    total_pnl_cents = 0
    bot_sections: list[dict] = []

    for alloc in allocations:
        profile = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        bot_name = profile.name if profile else f"bot_{alloc.profile_id}"

        # Yesterday's P&L
        pnl_row = (
            db.query(BotDailyPnL)
            .filter(
                BotDailyPnL.allocation_id == alloc.id,
                BotDailyPnL.date >= yesterday,
                BotDailyPnL.date < date.today(),
            )
            .first()
        )
        bot_pnl_cents = 0
        if pnl_row:
            bot_pnl_cents = (
                (pnl_row.realized_cents or 0)
                + (pnl_row.unrealized_cents or 0)
                - (pnl_row.fees_cents or 0)
            )
        total_pnl_cents += bot_pnl_cents

        # Open position count
        open_positions = (
            db.query(BotPosition)
            .filter(
                BotPosition.allocation_id == alloc.id,
                BotPosition.closed_at.is_(None),
            )
            .count()
        )

        # Top 5 watchlist symbols
        watchlist = (
            db.query(BotWatchlist)
            .filter(
                BotWatchlist.profile_id == alloc.profile_id,
                BotWatchlist.status == "active",
            )
            .order_by(BotWatchlist.score.desc())
            .limit(5)
            .all()
        )
        watchlist_symbols = [w.symbol for w in watchlist]

        # Latest health record
        health = (
            db.query(BotHealth)
            .filter(BotHealth.allocation_id == alloc.id)
            .order_by(BotHealth.date.desc())
            .first()
        )
        health_ok = (health is None) or (not health.paused_by_health)

        # Recent anomaly (last 24h)
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        anomaly = None
        try:
            anomaly = (
                db.query(AnomalyEvent)
                .filter(
                    AnomalyEvent.allocation_id == alloc.id,
                    AnomalyEvent.detected_at >= cutoff_24h,
                )
                .order_by(AnomalyEvent.detected_at.desc())
                .first()
            )
        except Exception:
            pass

        bot_sections.append({
            "name": bot_name,
            "pnl_cents": bot_pnl_cents,
            "open_positions": open_positions,
            "watchlist_symbols": watchlist_symbols,
            "health_ok": health_ok,
            "anomaly": anomaly.anomaly_type if anomaly else None,
            "enabled": alloc.enabled,
        })

    # ── Regime snapshot ───────────────────────────────────────────────────────
    regime = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).first()
    vix_value = regime.vix_value if regime else None
    vix_regime = regime.vix_regime if regime else "unknown"
    trend_regime = regime.trend_regime if regime else "unknown"
    btc_dominance = regime.btc_dominance if regime else None

    # ── Upcoming catalysts (next 24h) ─────────────────────────────────────────
    catalyst_events: list[dict] = []
    horizon_24h = datetime.now(timezone.utc) + timedelta(hours=24)
    try:
        catalyst_rows = (
            db.query(CatalystEvent)
            .filter(CatalystEvent.event_ts >= datetime.now(timezone.utc))
            .filter(CatalystEvent.event_ts <= horizon_24h)
            .order_by(CatalystEvent.event_ts.asc())
            .limit(10)
            .all()
        )
        catalyst_events = [
            {"event_type": r.event_type, "symbol": r.symbol, "event_ts": r.event_ts.isoformat()}
            for r in catalyst_rows
        ]
    except Exception:
        # Fall back to in-memory catalyst calendar
        try:
            from strategy_lab.core.catalyst_calendar import get_upcoming_catalysts
            catalyst_events = get_upcoming_catalysts(symbol="", hours_ahead=24)
        except Exception as exc:
            logger.debug("[briefing] Could not fetch catalysts: %s", exc)

    # ── Build subject ─────────────────────────────────────────────────────────
    pnl_str = _format_pnl(total_pnl_cents)
    bot_count = len(allocations)
    subject = f"BMG Daily — Yesterday {pnl_str} across {bot_count} bot{'s' if bot_count != 1 else ''}"

    # ── Build HTML ────────────────────────────────────────────────────────────
    # Per-bot rows
    bot_rows_html = ""
    for s in bot_sections:
        pnl_color = _pnl_color(s["pnl_cents"])
        pnl_fmt = _format_pnl(s["pnl_cents"])
        watchlist_str = ", ".join(s["watchlist_symbols"]) if s["watchlist_symbols"] else "—"
        status_badge = (
            '<span style="color:#dc2626;font-weight:600">⚠ Alert</span>'
            if not s["health_ok"] or s["anomaly"]
            else '<span style="color:#16a34a;font-weight:600">Healthy</span>'
        )
        anomaly_note = (
            f'<br><span style="color:#dc2626;font-size:12px">Anomaly: {s["anomaly"]}</span>'
            if s["anomaly"]
            else ""
        )
        bot_rows_html += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #e2e8f0;font-weight:600">{s["name"]}</td>
          <td style="padding:10px;border-bottom:1px solid #e2e8f0;color:{pnl_color};font-weight:600">{pnl_fmt}</td>
          <td style="padding:10px;border-bottom:1px solid #e2e8f0">{s["open_positions"]}</td>
          <td style="padding:10px;border-bottom:1px solid #e2e8f0;font-size:13px">{watchlist_str}</td>
          <td style="padding:10px;border-bottom:1px solid #e2e8f0">{status_badge}{anomaly_note}</td>
        </tr>
        """

    # Catalyst calendar rows
    catalyst_html = ""
    if catalyst_events:
        for evt in catalyst_events[:5]:
            ts_str = evt.get("event_ts", "")[:16].replace("T", " ")
            sym = evt.get("symbol") or ""
            label = f'{evt.get("event_type", "").upper()}{" — " + sym if sym else ""}'
            catalyst_html += f'<li style="margin:4px 0">{ts_str} UTC — <strong>{label}</strong></li>'
    else:
        catalyst_html = '<li style="color:#64748b">No major catalysts in next 24h</li>'

    # Regime section
    vix_display = f"{vix_value:.1f}" if vix_value is not None else "N/A"
    btc_dom_display = f"{btc_dominance:.1f}%" if btc_dominance is not None else "N/A"
    regime_html = f"""
    <p style="margin:4px 0">VIX: <strong>{vix_display}</strong>
      &nbsp;|&nbsp; Regime: <strong>{vix_regime} / {trend_regime}</strong>
      &nbsp;|&nbsp; BTC Dominance: <strong>{btc_dom_display}</strong></p>
    """

    total_pnl_color = _pnl_color(total_pnl_cents)
    total_pnl_fmt = _format_pnl(total_pnl_cents)

    # Build bot table outside the outer f-string — nested f"""...""" is only
    # valid in Python 3.12+; extracting avoids the SyntaxError on 3.11.
    if bot_sections:
        bot_table_html = (
            '<table style="width:100%;border-collapse:collapse;font-size:14px">'
            "<thead><tr style=\"background:#f8fafc\">"
            "<th style=\"padding:10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#374151\">Bot</th>"
            "<th style=\"padding:10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#374151\">P&amp;L</th>"
            "<th style=\"padding:10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#374151\">Positions</th>"
            "<th style=\"padding:10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#374151\">Top Watchlist</th>"
            "<th style=\"padding:10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#374151\">Health</th>"
            f"</tr></thead><tbody>{bot_rows_html}</tbody></table>"
        )
    else:
        bot_table_html = "<p style='color:#64748b;font-style:italic'>No active bot allocations found.</p>"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <div style="max-width:640px;margin:32px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)">

    <!-- Header -->
    <div style="background:#0f172a;padding:28px 32px">
      <p style="margin:0;color:#94a3b8;font-size:13px;letter-spacing:.05em">STRATEGY LAB</p>
      <h1 style="margin:8px 0 0;color:#ffffff;font-size:24px;font-weight:700">BMG Daily Briefing</h1>
      <p style="margin:6px 0 0;color:#94a3b8;font-size:14px">{yesterday.strftime("%A, %B %-d, %Y")}</p>
    </div>

    <!-- Combined P&L banner -->
    <div style="padding:20px 32px;background:#f0fdf4;border-bottom:1px solid #dcfce7">
      <p style="margin:0;font-size:15px;color:#374151">Yesterday's combined P&L across all active bots:</p>
      <p style="margin:4px 0 0;font-size:32px;font-weight:800;color:{total_pnl_color}">{total_pnl_fmt}</p>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px">

      <!-- Regime snapshot -->
      <h2 style="margin:0 0 8px;font-size:16px;font-weight:700;color:#0f172a">Today's Regime Snapshot</h2>
      {regime_html}

      <!-- Bot table -->
      <h2 style="margin:24px 0 12px;font-size:16px;font-weight:700;color:#0f172a">Active Bots — Yesterday Performance</h2>
      {bot_table_html}

      <!-- Catalyst calendar -->
      <h2 style="margin:24px 0 8px;font-size:16px;font-weight:700;color:#0f172a">Today's Catalyst Calendar</h2>
      <ul style="margin:0;padding-left:20px;font-size:14px;color:#374151">{catalyst_html}</ul>

      <!-- CTAs -->
      <div style="margin-top:28px;display:flex;gap:12px;flex-wrap:wrap">
        <a href="{FRONTEND_URL}/command-center"
           style="display:inline-block;padding:10px 20px;background:#0f172a;color:#ffffff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">
          Open Command Center
        </a>
        <a href="{FRONTEND_URL}/api/bots/pause-all"
           style="display:inline-block;padding:10px 20px;background:#fef2f2;color:#dc2626;border:1px solid #fecaca;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">
          Pause All Bots
        </a>
        <a href="{FRONTEND_URL}/copilot"
           style="display:inline-block;padding:10px 20px;background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">
          Ask Co-Pilot
        </a>
      </div>

    </div>

    <!-- Footer -->
    <div style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0">
      <p style="margin:0;font-size:12px;color:#94a3b8">
        BMG Capital Strategy Lab &bull; Paper trading mode &bull;
        <a href="{FRONTEND_URL}/settings/notifications" style="color:#94a3b8">Manage preferences</a>
      </p>
    </div>

  </div>
</body>
</html>"""

    return subject, html


def send_daily_briefing(user_id: int, email: str, db: Session) -> bool:
    """Send the briefing. Returns True if sent (via Resend), False if logged only."""
    try:
        subject, html = generate_briefing_html(user_id, db)
        resend_api_key = os.getenv("RESEND_API_KEY")
        if resend_api_key:
            import resend
            resend.api_key = resend_api_key
            resend.Emails.send({
                "from": "BMG Capital <briefing@bmgcapital.app>",
                "to": [email],
                "subject": subject,
                "html": html,
            })
            logger.info("[briefing] Sent to %s: %s", email, subject)
            return True
        else:
            logger.info("[briefing] RESEND_API_KEY not set. Briefing for %s:\n%s", email, subject)
            return False
    except Exception as e:
        logger.error("[briefing] Failed to send: %s", e)
        return False


def build_discord_digest(db: Session) -> dict:
    """Build the daily digest payload for Discord #daily-digest.

    Returns a dict consumed by discord_public.post_daily_digest().
    Aggregates across ALL users (portfolio-wide view).
    """
    from app.db.models.bots import (
        BotAllocation, BotProfile, BotSignal, BotTrade, BotPosition,
    )

    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

    # Today's signals count by bot
    allocs = db.query(BotAllocation).filter(BotAllocation.enabled.is_(True)).all()
    alloc_ids = [a.id for a in allocs]

    signals_today = (
        db.query(BotSignal.allocation_id)
        .filter(BotSignal.allocation_id.in_(alloc_ids), BotSignal.ts >= today_start)
        .all()
    ) if alloc_ids else []

    # Build by_bot signal count
    alloc_id_to_name: dict[int, str] = {}
    for alloc in allocs:
        bp = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
        if bp:
            alloc_id_to_name[alloc.id] = bp.name

    by_bot: dict[str, int] = {}
    for (aid,) in signals_today:
        name = alloc_id_to_name.get(aid, str(aid))
        by_bot[name] = by_bot.get(name, 0) + 1

    # Today's closed trades for P&L + top winners/losers
    trades_today = (
        db.query(BotTrade)
        .filter(
            BotTrade.allocation_id.in_(alloc_ids),
            BotTrade.side == "sell",
            BotTrade.ts >= today_start,
        )
        .all()
    ) if alloc_ids else []

    realized_cents = 0
    trade_pnl: list[tuple[int, str]] = []  # (pnl_cents, symbol)
    for trade in trades_today:
        pnl_c = int(getattr(trade, "pnl_cents", None) or 0)
        realized_cents += pnl_c
        trade_pnl.append((pnl_c, trade.symbol or "?"))

    trade_pnl.sort(key=lambda x: -x[0])
    top_winners = [{"symbol": s, "pnl_cents": p} for p, s in trade_pnl[:3]]
    top_losers  = [{"symbol": s, "pnl_cents": p} for p, s in sorted(trade_pnl, key=lambda x: x[0])[:3]]
    top_symbols = list(dict.fromkeys(s for _, s in trade_pnl))[:5]

    # Open position count for deployment level
    open_count = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .count()
    ) if alloc_ids else 0

    return {
        "realized_pnl_cents": realized_cents,
        "total_signals": len(signals_today),
        "top_symbols": top_symbols,
        "by_bot": by_bot,
        "top_winners": top_winners,
        "top_losers": top_losers,
        "open_positions": open_count,
        "date": date.today().isoformat(),
    }


def run_daily_briefing_job(db: Session) -> None:
    """Called by APScheduler at 8am ET weekdays. Sends to all active users."""
    from app.db.models.users import User
    from app.db.models.bots import BotAllocation

    # Find all users with at least one enabled allocation
    user_ids_with_allocs = (
        db.query(BotAllocation.user_id)
        .filter(BotAllocation.enabled.is_(True))
        .distinct()
        .all()
    )
    user_ids = [row[0] for row in user_ids_with_allocs]

    if not user_ids:
        logger.info("[briefing] No active allocations found — skipping daily briefing")
        return

    users = (
        db.query(User)
        .filter(User.id.in_(user_ids), User.is_active.is_(True))
        .all()
    )

    logger.info("[briefing] Sending daily briefing to %d user(s)", len(users))
    for user in users:
        try:
            send_daily_briefing(user.id, user.email, db)
        except Exception as exc:
            logger.error("[briefing] Failed for user %d (%s): %s", user.id, user.email, exc)
