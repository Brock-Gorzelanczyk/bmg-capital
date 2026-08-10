"""Pre-market validation report. Runs before 9:30 AM ET as a standing
ritual per PM Claude 2026-08-07.

Checks 1-5 (6 held until #22 kill switch ships):
1. Dry-run scan — placeholder (runner has no dry-run mode; reports 24h
   signal counts + gate config as proxy). Future work.
2. State snapshot — recon drift, fund PV, invariants, options exposure,
   cash/BP.
3. Confirm schedulers — every APScheduler job with next_run_time.
4. Verify enabled bots — enumerate by name; flag any retired/paused.
5. Residual drift — identify each mismatched row before market open.
6. Kill switch test — held until #22 ships.

Companion to daily_report.py (4:15 PM close report). Morning = will
it behave. Evening = did it behave.

Persists to ~/Documents/BMG-Capital-Vault/daily-audits/premarket-YYYY-MM-DD.md
"""
from __future__ import annotations

import logging
import os
import urllib.request
import json as _json
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def _alp_get(path: str) -> dict:
    kid = os.environ.get("ALPACA_API_KEY", "")
    ks = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        f"https://paper-api.alpaca.markets{path}",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ks},
    )
    return _json.loads(urllib.request.urlopen(req, timeout=10).read())


def _scheduler_jobs() -> list:
    """Return every APScheduler job with next fire time."""
    try:
        from app.main import scheduler as _sched  # populated at startup
    except Exception:
        # Fallback: get from any running module's scheduler singleton
        try:
            from apscheduler.schedulers.base import BaseScheduler
            import gc
            for obj in gc.get_objects():
                if isinstance(obj, BaseScheduler):
                    _sched = obj
                    break
            else:
                return []
        except Exception:
            return []
    out = []
    try:
        for job in _sched.get_jobs():
            out.append({
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
    except Exception as exc:
        logger.error("[premarket] scheduler introspection failed: %s", exc)
    out.sort(key=lambda x: x.get("next_run_time") or "9999")
    return out


def build_premarket_report(db) -> str:
    """Build the pre-market check report as markdown."""
    now = datetime.now(timezone.utc)
    et_now = now - timedelta(hours=5)  # ET approx
    date_str = et_now.strftime("%b %-d, %Y")

    lines = []
    lines.append(f"BMG PRE-MARKET • {date_str} • {et_now.strftime('%H:%M')} ET")
    lines.append("=" * 60)

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
            lines.append("")
            lines.append("⚠ HALT / ACK REQUIRED — leads all downstream sections ⚠")
            if _global_paused:
                lines.append(f"  TRADING HALTED (global pause) since {_st.get('muted_at')} "
                             f"by {_st.get('muted_by')} — reason: {_st.get('muted_reason')}")
            elif _paused_sleeves:
                lines.append(f"  Sleeves paused: {', '.join(_paused_sleeves)}")
            if _unacked:
                lines.append(f"  UNACKED items ({len(_unacked)}): scans_gate resume BLOCKED until AUTO_PAUSE acks cleared")
                for a in _unacked[:5]:
                    lines.append(f"    - [{a['category']}] {a['title']}  (id={a['id']}, {a['created_at'][:19]})")
                if len(_unacked) > 5:
                    lines.append(f"    ... +{len(_unacked)-5} more; GET /admin/pending-acks")
            lines.append("=" * 60)
    except Exception as _halt_exc:
        lines.append(f"  (HALT banner check raised: {_halt_exc})")

    # ── CHECK 1: Dry-run scan (proxy) ─────────────────────────────────────
    lines.append("")
    lines.append("CHECK 1 — DRY-RUN OPEN (proxy: 24h signals + gate config)")
    try:
        from sqlalchemy import text as _t
        cut = (now - timedelta(hours=24)).isoformat()
        for asset in ("equity", "options", "crypto"):
            sig_row = db.execute(_t(
                "SELECT COUNT(*) FROM bot_signals bs "
                "JOIN bot_allocations a ON a.id = bs.allocation_id "
                "JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE a.user_id = 1 AND bs.ts >= :cut "
                "AND (p.asset_class = :ac OR (:ac = 'crypto' AND p.asset_class = 'quant'))"
            ), {"cut": cut, "ac": "stock" if asset == "equity" else asset}).fetchone()
            sig_ct = int(sig_row[0] or 0) if sig_row else 0
            trade_row = db.execute(_t(
                "SELECT COUNT(*) FROM bot_trades t "
                "JOIN bot_allocations a ON a.id = t.allocation_id "
                "JOIN bot_profiles p ON p.id = a.profile_id "
                "WHERE a.user_id = 1 AND t.ts >= :cut AND t.quarantined_at IS NULL "
                "AND (p.asset_class = :ac OR (:ac = 'crypto' AND p.asset_class = 'quant'))"
            ), {"cut": cut, "ac": "stock" if asset == "equity" else asset}).fetchone()
            trade_ct = int(trade_row[0] or 0) if trade_row else 0
            conv = (trade_ct / sig_ct * 100) if sig_ct else 0.0
            lines.append(f"  {asset:8s}: signals_24h={sig_ct:>4}  fills_24h={trade_ct:>3}  conversion={conv:.1f}%")
    except Exception as exc:
        lines.append(f"  ERR: {exc}")
    lines.append("  Enforced gates (running env):")
    for k, default in [("OPTIONS_MAX_CONTRACTS_PER_TRADE", "5"),
                        ("OPTIONS_MAX_NOTIONAL_PCT", "0.20"),
                        ("OPTIONS_SLEEVE_MAX_PCT", "1.0"),
                        ("LEAPS_MIN_DTE", "180"),
                        ("OPTIONS_RISK_GATES_ENABLED", "true"),
                        ("MAX_LOSS_MAX_PCT_NAV", "1.0"),
                        ("BOT_EXECUTOR_LEGACY_SIM_ENABLED", "false")]:
        val = os.getenv(k, default) + (" (default)" if os.getenv(k) is None else "")
        lines.append(f"    {k}: {val}")
    lines.append("  NOTE: true runner dry-run mode not yet implemented — see roadmap.")

    # ── CHECK 2: State snapshot ────────────────────────────────────────────
    lines.append("")
    lines.append("CHECK 2 — STATE SNAPSHOT")
    try:
        acct = _alp_get("/v2/account")
        alp_pv = float(acct.get("portfolio_value") or 0)
        cash = float(acct.get("cash") or 0)
        bp = float(acct.get("buying_power") or 0)
        crypto_bp = float(acct.get("crypto_buying_power") or 0)
        opts_bp = float(acct.get("options_buying_power") or 0)
        non_marg = float(acct.get("non_marginable_buying_power") or 0)
    except Exception as exc:
        alp_pv = cash = bp = crypto_bp = opts_bp = non_marg = 0.0
        lines.append(f"  Alpaca fetch err: {exc}")
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(user_id=1, db=db) or {}
        fund_pv = (agg.get("total_value_cents") or 0) / 100
        unattr = agg.get("unattributed_usd") or 0
    except Exception:
        fund_pv = 0.0; unattr = 0.0
    lines.append(f"  Fund PV: ${fund_pv:,.2f}   Alpaca: ${alp_pv:,.2f}   gap: ${abs(fund_pv - alp_pv):,.2f}")
    lines.append(f"  Cash: ${cash:,.2f}   BP: ${bp:,.2f}   crypto_BP: ${crypto_bp:,.2f}   options_BP: ${opts_bp:,.2f}   non_marg: ${non_marg:,.2f}")
    lines.append(f"  Unattributed: ${unattr:,.2f}")
    try:
        alp_pos = _alp_get("/v2/positions")
        opts = [p for p in alp_pos if len((p.get("symbol") or "")) > 10]
        opts_gross = sum(abs(float(p.get("market_value") or 0)) for p in opts)
        biggest = max(alp_pos, key=lambda p: abs(float(p.get("market_value") or 0))) if alp_pos else None
        big_sym = biggest.get("symbol") if biggest else "-"
        big_mv = abs(float(biggest.get("market_value") or 0)) if biggest else 0
        big_pct = (big_mv / alp_pv * 100) if alp_pv else 0
        lines.append(f"  Options exposure: ${opts_gross:,.0f} across {len(opts)} legs")
        lines.append(f"  Biggest position: {big_sym} = ${big_mv:,.0f} = {big_pct:.1f}% NAV  (cap 20%)")
    except Exception as exc:
        lines.append(f"  Positions fetch err: {exc}")

    # Invariants
    try:
        from app.services.invariant_engine import run_all_invariants
        inv = run_all_invariants(db)
        s = inv.get("summary", {})
        lines.append(f"  Invariants: red={s.get('red',0)} amber={s.get('amber',0)} green={s.get('green',0)} of {sum(s.values())}")
        for r in inv.get("red", []):
            lines.append(f"    RED   {r['check_id']}: {r.get('detail','')[:80]}")
        for r in inv.get("amber", []):
            lines.append(f"    AMBER {r['check_id']}: {r.get('detail','')[:80]}")
    except Exception as exc:
        lines.append(f"  Invariants err: {exc}")

    # ── CHECK 3: Schedulers ────────────────────────────────────────────────
    lines.append("")
    lines.append("CHECK 3 — SCHEDULERS (next fire time each)")
    jobs = _scheduler_jobs()
    if not jobs:
        lines.append("  (none introspected — scheduler singleton not accessible)")
    else:
        want_ids = {"daily_report_415pm_et", "invariant_engine_intraday",
                    "invariant_engine_nightly", "option_close_sync_intraday",
                    "pr_daily_mark_intraday", "pr_daily_mark_nightly"}
        found = {j["id"] for j in jobs}
        for j in jobs:
            highlight = " *KEY*" if j["id"] in want_ids else ""
            lines.append(f"  {j['id']:40s} next={j.get('next_run_time','?')}{highlight}")
        missing = want_ids - found
        if missing:
            lines.append(f"  MISSING KEY JOBS: {sorted(missing)}")
        else:
            lines.append(f"  ✓ All key jobs registered")

    # ── CHECK 4: Enabled bots by name ──────────────────────────────────────
    lines.append("")
    lines.append("CHECK 4 — ENABLED USER-1 BOTS")
    try:
        from app.db.models.bots import BotAllocation, BotProfile
        profs = {p.id: p.name for p in db.query(BotProfile).all()}
        allocs = db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()
        enabled = [a for a in allocs if a.enabled]
        paused = [a for a in allocs if not a.enabled]
        lines.append(f"  Enabled: {len(enabled)} bots")
        for a in sorted(enabled, key=lambda x: profs.get(x.profile_id, "")):
            name = profs.get(a.profile_id, f"alloc_{a.id}")
            starting = (a.starting_capital_cents or 0) / 100
            # SSRN-flagged junk list — expand as needed
            flag = ""
            if name in ("crypto_quant_scalp_1m",):
                flag = " ⚠ SSRN-FLAGGED (should be retired)"
            lines.append(f"    {name:32s} alloc_id={a.id:>3}  start=${starting:>9,.0f}{flag}")
        lines.append(f"  Paused/tombstoned: {len(paused)} allocs")
        # Crypto BP starvation check
        if 'crypto_bp' in dir():
            crypto_enabled = [profs.get(a.profile_id) for a in enabled if profs.get(a.profile_id, "").startswith("crypto")]
            if crypto_enabled and crypto_bp < 500:
                lines.append(f"  ⚠ WARNING: {len(crypto_enabled)} crypto bots enabled but crypto_buying_power < $500 (starved)")
    except Exception as exc:
        lines.append(f"  ERR: {exc}")

    # ── CHECK 5: Residual drift IDs ────────────────────────────────────────
    lines.append("")
    lines.append("CHECK 5 — RESIDUAL POSITION DRIFT")
    try:
        alp_positions = _alp_get("/v2/positions")
        alp_keys = set()
        for p in alp_positions:
            q = float(p.get("qty") or 0)
            side = "short" if q < 0 else "long"
            alp_keys.add((p.get("symbol"), side))
        from app.db.models.bots import BotPosition, BotAllocation
        u1 = [a.id for a in db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()]
        bmg = (
            db.query(BotPosition)
            .filter(BotPosition.allocation_id.in_(u1))
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .all()
        )
        from collections import defaultdict
        bmg_by_key = defaultdict(list)
        for p in bmg:
            bmg_by_key[(p.symbol, (p.side or "long").lower())].append(p)
        bmg_keys = set(bmg_by_key.keys())
        only_bmg = sorted(bmg_keys - alp_keys)
        only_alp = sorted(alp_keys - bmg_keys)
        lines.append(f"  User1 rows: {len(bmg)}   Alpaca positions: {len(alp_keys)}")
        lines.append(f"  Only in BMG (phantom): {len(only_bmg)}")
        for k in only_bmg[:8]:
            g = bmg_by_key[k]
            lines.append(f"    {k[0]:20s} {k[1]:5s}  ids={[p.id for p in g]}")
        lines.append(f"  Only in Alpaca (missing from BMG): {len(only_alp)}")
        for k in only_alp[:8]:
            lines.append(f"    {k[0]:20s} {k[1]:5s}")
    except Exception as exc:
        lines.append(f"  ERR: {exc}")

    # ── CHECK 6: Kill switch test ──────────────────────────────────────────
    lines.append("")
    lines.append("CHECK 6 — KILL SWITCH LIVE TEST")
    lines.append("  #22 SCANS_ENABLED not shipped yet — check held.")
    lines.append("  When it lands: pause all, confirm 0 writes for 15 min, resume.")

    return "\n".join(lines)


def run_premarket_report_job(db=None) -> str:
    from app.db.session import SessionLocal
    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True
    try:
        report = build_premarket_report(db)
    finally:
        if close_after:
            db.close()
    # Ledger #22 audit sink: /data/audits (persistent Railway volume).
    # Prior versions wrote to ~/Documents/BMG-Capital-Vault/daily-audits
    # which only exists on Brock's laptop, not on Railway. On Railway ~ is
    # /root and there's no vault mount, so reports vanished. Retrieval via
    # GET /admin/audits/list + GET /admin/audits/{filename}.
    try:
        audit_dir = os.getenv("BMG_AUDIT_DIR", "/data/audits")
        os.makedirs(audit_dir, exist_ok=True)
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"{audit_dir}/premarket-{d}.md"
        with open(path, "w") as f:
            f.write(report)
        logger.warning("[premarket-report] wrote %s (%d bytes)", path, len(report))
    except Exception as exc:
        logger.warning("[premarket-report] audit write failed: %s", exc)
    return report


def setup_premarket_report_scheduler(scheduler) -> None:
    try:
        from apscheduler.triggers.cron import CronTrigger
        scheduler.add_job(
            run_premarket_report_job,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=15,
                        timezone="America/New_York"),
            id="premarket_report_915am_et",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=600,
            coalesce=True,
        )
        logger.warning("[premarket-report] scheduled 9:15 AM ET M-F")
    except Exception as exc:
        logger.error("[premarket-report] scheduler wiring failed: %s", exc)
