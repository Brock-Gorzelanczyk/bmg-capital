"""Daily 4:15 PM ET autonomy summary.

Per PM Claude 2026-08-07: replaces Brock's manual auditing during the
10-14 day autonomy-readiness window. Format frozen per Claude Code's
proposal — ship as-is.

Runs at 4:15pm ET M-F. Also callable on-demand via
GET /api/admin/daily-report. Persists to
~/Documents/BMG-Capital-Vault/daily-audits/YYYY-MM-DD.md
"""
from __future__ import annotations

import logging
import os
import urllib.request
import json as _json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


def _alp_get(path: str) -> dict:
    kid = os.environ.get("ALPACA_API_KEY", "")
    ks = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        f"https://paper-api.alpaca.markets{path}",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ks},
    )
    return _json.loads(urllib.request.urlopen(req, timeout=10).read())


def _round_trips_by_bot(db) -> dict:
    """FIFO-pair opens with closes per bot to count round trips."""
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile
    allocs = db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()
    profs = {p.id: p.name for p in db.query(BotProfile).all()}
    alloc_to_prof = {a.id: profs.get(a.profile_id) for a in allocs}
    alloc_ids = [a.id for a in allocs]
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id.in_(alloc_ids))
        .filter(BotTrade.quarantined_at.is_(None))
        .filter(BotTrade.alpaca_order_id.isnot(None))
        .order_by(BotTrade.ts.asc())
        .all()
    )
    open_by_key: dict = defaultdict(deque)
    rts_by_bot: dict = defaultdict(int)
    for t in trades:
        bot = alloc_to_prof.get(t.allocation_id, "?")
        key = (bot, t.symbol)
        side = (t.side or "").lower()
        if side in ("buy", "short"):
            open_by_key[key].append((side, float(t.qty or 0)))
        elif side in ("sell", "cover", "close"):
            need = float(t.qty or 0)
            q = open_by_key.get(key)
            while q and need > 0.001:
                open_side, open_qty = q[0]
                take = min(open_qty, need)
                if (open_side == "buy" and side == "sell") or (open_side == "short" and side in ("cover", "close")):
                    rts_by_bot[bot] += 1
                if take >= open_qty - 0.001:
                    q.popleft()
                else:
                    q[0] = (open_side, open_qty - take)
                need -= take
    return dict(rts_by_bot)


def build_daily_report(db) -> str:
    """Produce the 4:15pm ET summary as a formatted markdown string."""
    now = datetime.now(timezone.utc)
    ct_offset = timedelta(hours=-5)  # ET ≈ UTC-5 (approx; DST handled by APScheduler)
    et_now = now + ct_offset
    date_str = et_now.strftime("%b %-d, %Y")

    # Broker (Alpaca)
    try:
        acct = _alp_get("/v2/account")
        pv = float(acct.get("portfolio_value") or 0)
        last_eq = float(acct.get("last_equity") or 0)
        eq = float(acct.get("equity") or 0)
        cash = float(acct.get("cash") or 0)
        bp = float(acct.get("buying_power") or 0)
        today_delta = eq - last_eq
        today_pct = (today_delta / last_eq * 100) if last_eq else 0.0
    except Exception as exc:
        logger.error("[daily-report] alpaca account fetch failed: %s", exc)
        pv = last_eq = eq = cash = bp = today_delta = today_pct = 0.0

    try:
        alp_pos = _alp_get("/v2/positions")
        pos_count = len(alp_pos)
        long_mv = sum(float(p.get("market_value") or 0) for p in alp_pos if float(p.get("qty") or 0) > 0)
        short_mv = sum(float(p.get("market_value") or 0) for p in alp_pos if float(p.get("qty") or 0) < 0)
    except Exception:
        pos_count = 0; long_mv = 0.0; short_mv = 0.0

    # Invariants
    try:
        from app.services.invariant_engine import run_all_invariants
        inv = run_all_invariants(db)
        s = inv.get("summary", {})
        red = int(s.get("red", 0))
        amber = int(s.get("amber", 0))
        green = int(s.get("green", 0))
        red_details = [(r["check_id"], r.get("detail", "")[:70]) for r in inv.get("red", [])]
        amber_details = [(r["check_id"], r.get("detail", "")[:70]) for r in inv.get("amber", [])]
        green_ids = [r["check_id"] for r in inv.get("all", []) if r.get("level") == "green"]
    except Exception as exc:
        logger.error("[daily-report] invariants fetch failed: %s", exc)
        red = amber = green = 0
        red_details = amber_details = []
        green_ids = []

    # 24h trade counts
    try:
        from sqlalchemy import text as _t
        cut = (now - timedelta(hours=24)).isoformat()
        row = db.execute(_t(
            "SELECT COUNT(*) AS total, "
            "  SUM(CASE WHEN t.alpaca_order_id IS NOT NULL THEN 1 ELSE 0 END) AS real_ct, "
            "  SUM(CASE WHEN t.alpaca_order_id IS NULL THEN 1 ELSE 0 END) AS sim_ct "
            "FROM bot_trades t "
            "JOIN bot_allocations a ON a.id = t.allocation_id "
            "WHERE a.user_id = 1 AND t.ts >= :cut AND t.quarantined_at IS NULL"
        ), {"cut": cut}).fetchone()
        trades_24h = int(row[0] or 0) if row else 0
        trades_real = int(row[1] or 0) if row else 0
        trades_sim = int(row[2] or 0) if row else 0
        sig_row = db.execute(_t(
            "SELECT COUNT(*) FROM bot_signals bs "
            "JOIN bot_allocations a ON a.id = bs.allocation_id "
            "WHERE a.user_id = 1 AND bs.ts >= :cut"
        ), {"cut": cut}).fetchone()
        signals_24h = int(sig_row[0] or 0) if sig_row else 0
    except Exception as exc:
        logger.error("[daily-report] trades_24h fetch failed: %s", exc)
        trades_24h = trades_real = trades_sim = signals_24h = 0
    conv = (trades_24h / signals_24h * 100) if signals_24h else 0.0

    # Round trips per bot
    try:
        rts = _round_trips_by_bot(db)
        at_50_plus = sum(1 for v in rts.values() if v >= 50)
        rt_10_49 = sum(1 for v in rts.values() if 10 <= v < 50)
        rt_1_9 = sum(1 for v in rts.values() if 1 <= v < 10)
        # Enabled user-1 bots not in rts dict = 0-RT bots
        from app.db.models.bots import BotAllocation
        n_enabled = db.query(BotAllocation).filter(BotAllocation.user_id == 1).filter(BotAllocation.enabled == True).count()
        rt_0 = max(0, n_enabled - (at_50_plus + rt_10_49 + rt_1_9))
    except Exception as exc:
        logger.error("[daily-report] rts fetch failed: %s", exc)
        rts = {}; at_50_plus = rt_10_49 = rt_1_9 = rt_0 = 0

    # Unattributed
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        unattr = round((agg.get("unattributed_cents") or 0) / 100, 2)
    except Exception:
        unattr = 0.0

    # Format
    lines = []
    lines.append(f"BMG FUND • {date_str} • 4:15 PM ET")
    lines.append("")

    # ── HALT / ACK BANNER (Brock 2026-08-10): lead with halt state + unacked items ─
    try:
        from app.services.scans_gate import status_summary as _scan_status
        from app.services.human_ack import list_unacked
        _scans = _scan_status()
        _eff = _scans.get("effective", {})
        _st = _scans.get("state", {})
        _global_paused = _st.get("global") is False
        _paused_sleeves = [s for s, v in _eff.items() if not v]
        _unacked = list_unacked(db)
        if _global_paused or _paused_sleeves or _unacked:
            lines.append("⚠ HALT / ACK REQUIRED — leads all downstream sections ⚠")
            if _global_paused:
                lines.append(f"  TRADING HALTED (global pause) since {_st.get('muted_at')} "
                             f"by {_st.get('muted_by')} — reason: {_st.get('muted_reason')}")
            elif _paused_sleeves:
                lines.append(f"  Sleeves paused: {', '.join(_paused_sleeves)}")
            if _unacked:
                lines.append(f"  UNACKED items ({len(_unacked)}): resume blocked until AUTO_PAUSE acks cleared")
                for a in _unacked[:5]:
                    lines.append(f"    - [{a['category']}] {a['title']}  (id={a['id']}, {a['created_at'][:19]})")
                if len(_unacked) > 5:
                    lines.append(f"    ... +{len(_unacked)-5} more; GET /admin/pending-acks")
            lines.append("")
    except Exception as _halt_exc:
        lines.append(f"  (HALT banner check raised: {_halt_exc})")

    lines.append("BROKER (Alpaca, single-source-of-truth):")
    lines.append(f"  PV: ${pv:,.2f}     (Δ today: {'+' if today_delta >= 0 else ''}${today_delta:,.2f} / {'+' if today_pct >= 0 else ''}{today_pct:.2f}%)")
    lines.append(f"  Cash: ${cash:,.2f}    Buying power: ${bp:,.2f}")
    lines.append(f"  Positions: {pos_count}     Longs: ${long_mv:,.0f}  Shorts: ${short_mv:,.0f}")
    lines.append("")
    bar_filled = green
    bar_total = red + amber + green
    bar = "▮" * bar_filled + "▯" * (bar_total - bar_filled)
    lines.append(f"INVARIANTS:  {bar} {bar_filled}/{bar_total} green")
    if red_details:
        rd_str = " · ".join(f"{cid} {d}" for cid, d in red_details[:3])
        lines.append(f"  RED ({red}):    {rd_str}")
    if amber_details:
        ad_str = " · ".join(f"{cid} {d}" for cid, d in amber_details[:3])
        lines.append(f"  AMBER ({amber}):  {ad_str}")
    if green_ids:
        lines.append(f"  GREEN:      {' '.join(green_ids)}")
    lines.append("")
    lines.append("BOT ACTIVITY (24h):")
    sim_marker = "  *see I3 breach" if trades_sim > 0 else ""
    lines.append(f"  Trades: {trades_24h} ({trades_real} real, {trades_sim} sim){sim_marker}")
    lines.append(f"  Signals: {signals_24h:,}  Fills: {trades_24h}  Conversion: {conv:.1f}%")
    lines.append("")
    lines.append("TRACK RECORD PROGRESS (target: 50 RTs / Sharpe > 1.0 / win > 55%):")
    lines.append(f"  At 50 RTs: {at_50_plus} bots" +
                 (" (" + ", ".join(k for k, v in rts.items() if v >= 50) + ")" if at_50_plus else ""))
    lines.append(f"  10-49 RTs: {rt_10_49} bots")
    lines.append(f"  1-9 RTs:   {rt_1_9} bots")
    lines.append(f"  0 RTs:     {rt_0} bots")
    lines.append("")
    lines.append(f"UNATTRIBUTED: ${unattr:,.2f} (target < $1,000)")
    lines.append("")
    # Cost line (Brock 2026-08-12 — was invisible, treat like every other
    # invariant: if nobody measures it, it drifts until something breaks).
    lines.append("")
    lines.append("RAILWAY COST (last 24h):")
    try:
        import os as _os
        if _os.path.exists("/tmp/bmg_cost.log"):
            with open("/tmp/bmg_cost.log") as _f:
                _cost_lines = _f.readlines()[-24:]  # last 24 hourly samples
            if _cost_lines:
                lines.append(f"  {len(_cost_lines)} hourly samples logged")
                lines.append(f"  latest: {_cost_lines[-1].strip()[:80]}")
            else:
                lines.append("  no samples yet — bmg_cost_watch.sh may still be starting")
        else:
            lines.append("  /tmp/bmg_cost.log missing — start scripts/bmg_cost_watch.sh")
    except Exception as _cost_exc:
        lines.append(f"  cost read failed: {_cost_exc}")
    lines.append("")

    # Auto-action status (Brock 2026-08-10 — replaces stale "until #22 ships" line).
    lines.append("AUTO-ACTIONS ACTIVE:")
    lines.append("  I2 (P&L drift > $500 → pause all scans)")
    lines.append("  I3 (sim fill in 24h → pause offending alloc via paused_reason)")
    lines.append("  I18 (/data > 90% → auto-prune backups keep=1)")
    lines.append("  Alerts route via critical_alert (CRITICAL_ALERTS_ENABLED, independent of DISCORD_OPS_ALERTS_ENABLED)")
    lines.append("  Resume blocked while any AUTO_PAUSE ack is unacked (GET /admin/pending-acks)")
    return "\n".join(lines)


def run_daily_report_job(db=None) -> str:
    """APScheduler callable. Builds the report, writes to vault daily-audits/."""
    from app.db.session import SessionLocal
    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True
    try:
        report = build_daily_report(db)
    finally:
        if close_after:
            db.close()
    # Ledger #22 audit sink: /data/audits (persistent Railway volume).
    # Prior version wrote to ~/Documents/BMG-Capital-Vault/daily-audits
    # which only exists on Brock's laptop, not Railway.
    try:
        audit_dir = os.getenv("BMG_AUDIT_DIR", "/data/audits")
        os.makedirs(audit_dir, exist_ok=True)
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"{audit_dir}/close-{d}.md"
        with open(path, "a") as f:
            f.write("\n\n---\n\n")
            f.write(report)
            f.write("\n")
        logger.warning("[daily-report] wrote %s (%d bytes)", path, len(report))
    except Exception as exc:
        logger.warning("[daily-report] audit write failed (non-fatal): %s", exc)
    return report


def setup_daily_report_scheduler(scheduler) -> None:
    """Register the 4:15pm ET M-F cron."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        scheduler.add_job(
            run_daily_report_job,
            CronTrigger(day_of_week="mon-fri", hour=16, minute=15,
                        timezone="America/New_York"),
            id="daily_report_415pm_et",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=600,
            coalesce=True,
        )
        logger.warning("[daily-report] scheduled 4:15 PM ET M-F")
    except Exception as exc:
        logger.error("[daily-report] scheduler wiring failed: %s", exc)
