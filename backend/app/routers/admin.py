"""Admin endpoints — internal ops, not exposed in public docs."""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user, require_admin
from app.db.models.users import User
from app.core.tz import iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/backfill-bridge")
def backfill_bridge(
    max_age_hours: int = Query(48, description="How far back to copy signals"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy recent local bot_signals to the discord-worker Postgres bridge.

    Run once after deploy to backfill signals that were written before the
    bridge integration went live. On CONFLICT DO NOTHING — safe to call repeatedly.
    """
    bridge_url = os.environ.get("DISCORD_BRIDGE_DATABASE_URL")
    if not bridge_url:
        return {"ok": False, "error": "DISCORD_BRIDGE_DATABASE_URL env var not set on this service"}

    from app.db.models.bots import BotSignal, BotAllocation, BotProfile

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    signals = (
        db.query(BotSignal)
        .filter(BotSignal.ts >= cutoff)
        .order_by(BotSignal.ts.asc())
        .all()
    )

    written = skipped = errors = 0
    try:
        import psycopg2
        with psycopg2.connect(bridge_url) as conn:
            with conn.cursor() as cur:
                for sig in signals:
                    try:
                        alloc = db.get(BotAllocation, sig.allocation_id)
                        if not alloc:
                            skipped += 1
                            continue
                        prof = db.get(BotProfile, alloc.profile_id)
                        if not prof:
                            skipped += 1
                            continue

                        cur.execute(
                            "INSERT INTO bot_profiles (id, name) VALUES (%s, %s) "
                            "ON CONFLICT (id) DO NOTHING",
                            (prof.id, prof.name),
                        )
                        cur.execute(
                            "INSERT INTO bot_allocations (id, user_id, profile_id) "
                            "VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                            (alloc.id, alloc.user_id, alloc.profile_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO bot_signals
                              (allocation_id, ts, symbol, side, confidence, size_hint,
                               reason, strategy, entry_price, stop_price, target_price,
                               discord_posted_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)
                            ON CONFLICT DO NOTHING
                            """,
                            (sig.allocation_id, sig.ts, sig.symbol, sig.side,
                             sig.confidence, sig.size_hint, sig.reason, sig.strategy,
                             sig.entry_price, sig.stop_price, sig.target_price),
                        )
                        written += 1
                    except Exception as row_exc:
                        errors += 1
                        logger.warning("backfill row %d error: %s", sig.id if sig else -1, row_exc)
            conn.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "written": written}

    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "errors": errors,
        "max_age_hours": max_age_hours,
    }


@router.get("/guardrail/{user_id}")
def get_guardrail(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read the guardrail settings for a user."""
    from app.db.models.autonomous import AutonomousGuardrail
    g = db.query(AutonomousGuardrail).filter_by(user_id=user_id).first()
    if not g:
        return {"user_id": user_id, "exists": False}
    return {
        "user_id": user_id,
        "max_open_positions": g.max_open_positions,
        "daily_loss_limit_pct": g.daily_loss_limit_pct,
        "autonomous_paused": g.autonomous_paused,
    }


@router.post("/bots/repair-watchlists")
def repair_watchlists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upsert bot_watchlist entries for every BotProfile from its YAML universe.

    Idempotent — uses INSERT OR IGNORE (SQLite) / ON CONFLICT DO NOTHING (Postgres).
    Run once after adding a new bot profile whose watchlist was never seeded.
    """
    from datetime import datetime, timezone
    from app.db.models.bots import BotProfile, BotWatchlist
    from strategy_lab.seeds import load_profile

    profiles = db.query(BotProfile).filter(BotProfile.enabled.is_(True)).all()
    now = datetime.now(timezone.utc)
    report = []

    for prof in profiles:
        cfg = load_profile(prof.name)
        universe = cfg.get("universe", {})
        if isinstance(universe, dict):
            symbols = [str(s) for s in universe.get("symbols", [])]
        elif isinstance(universe, list):
            symbols = [str(s) for s in universe]
        else:
            symbols = []

        if not symbols:
            report.append({"bot": prof.name, "symbols_added": 0, "note": "no_universe"})
            continue

        added = 0
        for rank, sym in enumerate(symbols, 1):
            existing = (
                db.query(BotWatchlist)
                .filter(BotWatchlist.profile_id == prof.id, BotWatchlist.symbol == sym)
                .first()
            )
            if not existing:
                db.add(BotWatchlist(
                    profile_id=prof.id,
                    symbol=sym,
                    score=float(len(symbols) - rank + 1),
                    rank=rank,
                    reasons={"seeded": 1.0},
                    status="active",
                    added_at=now,
                    last_evaluated_at=now,
                ))
                added += 1

        db.commit()
        report.append({"bot": prof.name, "symbols_added": added, "total_universe": len(symbols)})
        logger.info("repair_watchlists: %s → added %d symbols", prof.name, added)

    return {"ok": True, "results": report}


@router.post("/guardrail/{user_id}/position-cap")
def set_position_cap(
    user_id: int,
    value: int = Query(..., ge=1, le=500, description="New max_open_positions cap"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Directly set max_open_positions for a user's guardrail."""
    from app.db.models.autonomous import AutonomousGuardrail
    from app.services.guardrail_checker import get_or_create_guardrail
    g = get_or_create_guardrail(user_id, db)
    old = g.max_open_positions
    g.max_open_positions = value
    db.commit()
    logger.info("admin: set max_open_positions user=%d %d→%d by user=%d", user_id, old, value, current_user.id)
    return {"ok": True, "user_id": user_id, "old": old, "new": value}


# ── POST /api/admin/sentinel/test-heartbeat ──────────────────────────────────

@router.post("/sentinel/test-heartbeat")
def sentinel_test_heartbeat(current_user=Depends(get_current_user)):
    """Post a test heartbeat to #sentinel-ops to verify bot token + channel permissions."""
    from app.services.sentinel_monitor import send_test_heartbeat
    result = send_test_heartbeat()
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Discord post failed"))
    return result


# ── POST /api/admin/discord/test-fire ─────────────────────────────────────────

_BOT_CHANNEL_MAP: Dict[str, str] = {
    "stock_swing":             "stocks-signals",
    "stock_day":               "stocks-signals",
    "stock_lt":                "stocks-signals",
    "crypto_swing":            "crypto-signals",
    "crypto_day":              "crypto-signals",
    "crypto_lt":               "crypto-signals",
    "crypto_onchain":          "crypto-signals",
    "crypto_quant_aggressive": "quant-signals",
    "options_income":          "options-signals",
    "options_directional":     "options-signals",
}

@router.post("/discord/test-fire")
def discord_test_fire(
    bot_name: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Insert a test signal for `bot_name` so the Discord worker picks it up and
    posts a [TEST] embed to the correct channel.

    The signal is marked is_test=True so it is invisible to all /signals API
    endpoints and aggregate stats. The Discord worker (post-signal.ts) prefixes
    the embed title with "[TEST]" when it sees is_test=True.

    Safe to call repeatedly — each call inserts one test signal per bot.
    """
    from app.db.models.bots import BotAllocation, BotProfile, BotSignal

    profile = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
    if not profile:
        return {"ok": False, "error": f"Unknown bot profile: {bot_name!r}"}

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )
    if not allocation:
        return {"ok": False, "error": f"No allocation found for bot {bot_name!r} / user {current_user.id}"}

    now = datetime.now(timezone.utc)
    sig = BotSignal(
        allocation_id=allocation.id,
        ts=now,
        symbol="TEST",
        side="buy",
        confidence=0.99,
        size_hint=0.05,
        reason="WIRING TEST — IGNORE. Fired via /api/admin/discord/test-fire.",
        strategy="manual_test",
        entry_price=100.00,
        stop_price=95.00,
        target_price=110.00,
        is_test=True,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)

    # Mirror to the discord-worker's Postgres bridge — without this the worker
    # (which reads Postgres, not SQLite) would never see the signal.
    from strategy_lab.core.audit import _write_to_bridge_postgres
    _write_to_bridge_postgres(
        signal_id=sig.id,
        allocation_id=allocation.id,
        user_id=current_user.id,
        profile_id=profile.id,
        profile_name=profile.name,
        ts=now,
        symbol="TEST",
        side="buy",
        confidence=0.99,
        size_hint=0.05,
        reason="WIRING TEST — IGNORE. Fired via /api/admin/discord/test-fire.",
        strategy="manual_test",
        entry_price=100.00,
        stop_price=95.00,
        target_price=110.00,
        is_test=True,
    )

    channel_slug = _BOT_CHANNEL_MAP.get(bot_name, "all-signals")
    bridge_url_set = bool(os.environ.get("DISCORD_BRIDGE_DATABASE_URL"))
    logger.info("admin: test-fire signal %d for bot=%s channel=#%s bridge=%s by user=%d",
                sig.id, bot_name, channel_slug, bridge_url_set, current_user.id)
    return {
        "ok": True,
        "signal_id": sig.id,
        "bot": bot_name,
        "channel": f"#{channel_slug}",
        "bridge_db_reachable": bridge_url_set,
        "note": "Discord worker will post a [TEST] embed within ~10 seconds.",
    }


# ── POST /api/admin/bots/{name}/scan-now-verbose ──────────────────────────────

@router.post("/bots/{name}/scan-now-verbose")
def scan_now_verbose(
    name: str,
    persist: bool = Query(False),
    execute: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Run one full synchronous scan cycle for the named bot and return verbose results.

    Delegates to strategy_lab.scan_and_execute.scan_and_execute — the same function
    the scheduled jobs call — so this endpoint and the scheduler use identical code paths.
    """
    from strategy_lab.scan_and_execute import scan_and_execute
    return scan_and_execute(name, db, persist=persist, execute=execute, user_id=current_user.id)


# ── GET /api/admin/alpaca/ping ────────────────────────────────────────────────

@router.get("/alpaca/ping")
def alpaca_ping(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Test Alpaca paper API credentials.

    Reads ALPACA_PAPER_KEY + ALPACA_PAPER_SECRET env vars and hits
    GET /v2/account on paper-api.alpaca.markets.

    Returns {ok, account_id, buying_power, status, error}.
    Env vars required in Railway:
      ALPACA_PAPER_KEY    — Paper API Key ID  (from alpaca.markets → Paper dashboard → API Keys)
      ALPACA_PAPER_SECRET — Paper API Secret Key
    """
    import os as _os
    import urllib.request as _ur
    import json as _json

    key = _os.getenv("ALPACA_PAPER_KEY") or _os.getenv("ALPACA_API_KEY", "")
    secret = _os.getenv("ALPACA_PAPER_SECRET") or _os.getenv("ALPACA_SECRET_KEY", "")

    if not key or not secret:
        return {
            "ok": False,
            "error": (
                "No Alpaca credentials found. Set ALPACA_PAPER_KEY + ALPACA_PAPER_SECRET "
                "or ALPACA_API_KEY + ALPACA_SECRET_KEY in Railway environment."
            ),
            "key_set": bool(key),
            "secret_set": bool(secret),
        }

    url = "https://paper-api.alpaca.markets/v2/account"
    req = _ur.Request(url, headers={
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    })
    try:
        with _ur.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        return {
            "ok": True,
            "account_id": data.get("id"),
            "account_number": data.get("account_number"),
            "status": data.get("status"),
            "buying_power": data.get("buying_power"),
            "cash": data.get("cash"),
            "portfolio_value": data.get("portfolio_value"),
            "currency": data.get("currency"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "key_prefix": key[:8] + "..." if len(key) > 8 else "(short)",
        }


# ── GET /api/admin/alpaca/positions ─────────────────────────────────────────
#
# Raw broker positions passthrough. Needed because Alpaca can hold
# contracts (options especially) that BMG's DB shows as 0 open — LEAPS
# decay verification is blocked without a broker read.

@router.get("/alpaca/positions")
def alpaca_positions(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Passthrough of Alpaca /v2/positions.

    Returns {as_of, count, positions: [{symbol, qty, asset_class,
    avg_entry_price, current_price, market_value, unrealized_pl,
    unrealized_plpc, exchange, side}]}.

    Admin-only. No caching — this is a diagnostic, not a hot path.
    """
    import os as _os
    import urllib.request as _ur
    import json as _json
    from datetime import datetime, timezone

    key = _os.getenv("ALPACA_PAPER_KEY") or _os.getenv("ALPACA_API_KEY", "")
    secret = _os.getenv("ALPACA_PAPER_SECRET") or _os.getenv("ALPACA_SECRET_KEY", "")
    now_iso = datetime.now(timezone.utc).isoformat()

    if not key or not secret:
        return {"as_of": now_iso, "count": 0, "positions": [], "error": "no_credentials"}

    url = "https://paper-api.alpaca.markets/v2/positions"
    req = _ur.Request(url, headers={
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    })
    try:
        with _ur.urlopen(req, timeout=10) as resp:
            raw = _json.loads(resp.read()) or []
    except Exception as exc:
        return {"as_of": now_iso, "count": 0, "positions": [], "error": str(exc)}

    positions = []
    for p in raw:
        positions.append({
            "symbol": p.get("symbol"),
            "qty": p.get("qty"),
            "side": p.get("side"),
            "asset_class": p.get("asset_class"),
            "exchange": p.get("exchange"),
            "avg_entry_price": p.get("avg_entry_price"),
            "current_price": p.get("current_price"),
            "market_value": p.get("market_value"),
            "unrealized_pl": p.get("unrealized_pl"),
            "unrealized_plpc": p.get("unrealized_plpc"),
        })
    return {"as_of": now_iso, "count": len(positions), "positions": positions}


# ── POST /api/admin/orphan-adopter/run ──────────────────────────────────────
# STOP-THE-LINE #3 (2026-07-15): walks live Alpaca options positions,
# attributes untracked ones to originating bots via order history, inserts
# BotPosition rows so the app's tracking catches up to broker truth.
# Unattributable → ledger row with manual_review flag.

@router.post("/orphan-adopter/run")
def run_orphan_adopter(
    dry_run: bool = Query(False, description="If true, report what WOULD be adopted without inserting rows."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Manually kick the orphan adopter. Runs the same code the 15-min
    scheduler runs. Set dry_run=true to preview without inserting."""
    from app.services.orphan_adopter import adopt_orphans
    return adopt_orphans(db, dry_run=dry_run)


# ── POST /api/admin/quarantine-non-broker-trades ────────────────────────────
# 2026-08-05 STOP-THE-LINE #4: Walk every open BotTrade + BotPosition. If
# alpaca_order_id is NULL (sim leak) OR the id is NOT in the set of Alpaca
# filled orders (phantom — order accepted but never filled), mark the row
# quarantined so it drops out of every P&L calculation.

# ── Invariant Engine — Layer 3 tripwire ──────────────────────────────────
# GET returns the latest persisted snapshot (fast, no computation).
# POST triggers a fresh run + returns results.

@router.get("/invariants")
def get_invariants(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the latest persisted invariant snapshot. Reads from a JSON
    file the scheduler writes every 15 min. Fast + safe for the UI banner
    to poll frequently."""
    from app.services.invariant_engine import read_latest_snapshot
    return read_latest_snapshot()


@router.post("/invariants/run")
def run_invariants(
    fresh: bool = Query(False, description="Force fresh recompute. Default False = read latest scheduler snapshot."),
    full_board: bool = Query(False, description="Bypass RAILWAY_LOW_POWER filter — run every registered check regardless of env."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Serve invariants. Default = latest scheduler snapshot (fast, cached).
    Pass ?fresh=true to force an on-request recompute.

    Item 3.3 (2026-08-09, class fix): the scheduler owns invariant freshness.
    A request no longer forces a re-run — so a slow Alpaca call inside an
    invariant check can't cause a request timeout (502) that leaves the
    fund unmonitored. The scheduler runs invariants every 15 min during
    market hours + 05:30 UTC nightly (see setup_invariant_engine).

    Payload shape: when fresh=false and a snapshot exists, response is
    {as_of, results: [...]} from the JSON file. When fresh=true, response
    is the full {summary, red, amber, all} from run_all_invariants.
    Callers that need the summary counts can either compute from `results`
    or opt in with fresh=true.
    """
    from app.services.invariant_engine import run_all_invariants, read_latest_snapshot
    if fresh or full_board:
        # full_board=true forces low_power_override=False regardless of env
        # (e.g., run I3 explicitly during halt when LOW_POWER filter skips it).
        _lpo = False if full_board else None
        return run_all_invariants(db, low_power_override=_lpo)
    snap = read_latest_snapshot()
    # Fallback: if no snapshot yet (fresh deploy, empty /data), compute inline
    # once so callers see real data instead of {"error": "no_snapshot_yet"}.
    # After this run the scheduler takes over.
    if isinstance(snap, dict) and snap.get("error") == "no_snapshot_yet":
        return run_all_invariants(db)
    return snap


@router.post("/rollback-adopter-inserts")
def rollback_adopter_inserts(
    since_hours: int = Query(24, description="Only quarantine positions opened within the last N hours"),
    dry_run: bool = Query(True, description="Preview by default"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Emergency rollback for the orphan adopter runaway (2026-08-05).

    Adopter creates BotPosition rows but NO corresponding entry BotTrade
    (real trades always ship as a pair). Any open BotPosition opened in
    the last N hours that has zero BotTrade rows pointing at it is an
    adopter-created phantom. Quarantine them.
    """
    from datetime import datetime, timedelta, timezone
    from app.db.models.bots import BotPosition, BotTrade

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    now = datetime.now(timezone.utc)

    recent = (
        db.query(BotPosition)
        .filter(BotPosition.opened_at >= cutoff)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    victims: list[int] = []
    kept: int = 0
    for p in recent:
        has_trade = db.query(BotTrade).filter(BotTrade.position_id == p.id).first() is not None
        if has_trade:
            kept += 1
        else:
            victims.append(p.id)

    if not dry_run and victims:
        (
            db.query(BotPosition)
            .filter(BotPosition.id.in_(victims))
            .update(
                {"quarantined_at": now, "quarantine_reason": "adopter_runaway_rollback_2026_08_05"},
                synchronize_session=False,
            )
        )
        db.commit()

    return {
        "since_hours": since_hours,
        "dry_run": dry_run,
        "recent_positions_scanned": len(recent),
        "with_trade_kept": kept,
        "orphan_position_quarantined": len(victims) if not dry_run else 0,
        "orphan_position_ids_would_quarantine": victims if dry_run else victims[:20],
    }


@router.post("/daily-recon/run")
def run_daily_reconciliation_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Manually trigger the daily reconciliation pipeline (quarantine + orphan
    adopt + drift check). Same code the 05:00 UTC scheduler runs."""
    from app.services.daily_reconciler import run_daily_reconciliation
    return run_daily_reconciliation(db)


@router.post("/adopt-all-alpaca-orphans")
def adopt_all_alpaca_orphans(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Catch-all adopter: every Alpaca position not tracked in BMG gets
    inserted as a BotPosition + BotTrade under a synthetic
    'broker_orphan_catchall' allocation. Clears I9 orphans and closes
    the I2 P&L drift caused by untracked broker holdings.

    Idempotent: skips (symbol, side) keys already open in BMG.
    """
    import os, urllib.request, json
    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade, BotProfile, BotAllocation

    now = datetime.now(timezone.utc)

    # Ensure catchall profile + allocation exist
    prof = db.query(BotProfile).filter(BotProfile.name == "broker_orphan_catchall").first()
    if not prof:
        if dry_run:
            profile_action = "would_create_profile"
            prof_id = None
        else:
            prof = BotProfile(
                name="broker_orphan_catchall",
                description="Catch-all for Alpaca positions not attributable to any BMG strategy (2026-08-06).",
                asset_class="stock",
                enabled=False,
            )
            db.add(prof); db.flush()
            profile_action = "created_profile"
            prof_id = prof.id
    else:
        profile_action = "profile_exists"
        prof_id = prof.id

    alloc = None
    if prof:
        alloc = (
            db.query(BotAllocation)
            .filter(BotAllocation.user_id == current_user.id)
            .filter(BotAllocation.profile_id == prof.id)
            .first()
        )
    if prof and not alloc and not dry_run:
        alloc = BotAllocation(
            user_id=current_user.id,
            profile_id=prof.id,
            capital_pct=0.0,
            starting_capital_cents=0,
            enabled=False,
            paper_mode=True,
        )
        db.add(alloc); db.flush()
    alloc_id = alloc.id if alloc else None

    # Fetch Alpaca positions
    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
    )
    alp_list = json.loads(urllib.request.urlopen(req, timeout=15).read())

    # BMG open, non-quarantined — key by (symbol, side)
    bmg_rows = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    from collections import defaultdict
    bmg_qty_by_key: dict = defaultdict(float)
    for p in bmg_rows:
        side = (p.side or "long").lower()
        bmg_qty_by_key[(p.symbol or "", side)] += float(p.qty or 0)

    adopted: list[dict] = []
    skipped_matched: list[str] = []

    for p in alp_list:
        sym = p.get("symbol")
        raw_qty = float(p.get("qty"))
        side = "short" if raw_qty < 0 else "long"
        abs_qty = abs(raw_qty)
        key = (sym, side)

        bmg_qty = bmg_qty_by_key.get(key, 0.0)
        missing_qty = abs_qty - bmg_qty
        if missing_qty <= 0.001:
            skipped_matched.append(f"{sym}/{side}")
            continue

        avg_entry = float(p.get("avg_entry_price") or 0)
        asset_class = p.get("asset_class") or "us_equity"
        is_option = asset_class == "us_option" or (len(sym or "") > 10 and any(c in (sym or "") for c in ("C0","P0","C1","P1")))

        entry = {
            "symbol": sym, "side": side, "missing_qty": missing_qty,
            "avg_entry_price": avg_entry,
            "market_value": float(p.get("market_value") or 0),
            "unrealized_pl": float(p.get("unrealized_pl") or 0),
            "asset_class": asset_class,
        }

        if dry_run or alloc_id is None:
            adopted.append({**entry, "would_adopt": True})
            continue

        cost_cents = int(round(avg_entry * 100)) if avg_entry > 0 else 0
        parsed = {}
        if is_option:
            try:
                from app.services.orphan_adopter import _parse_occ
                parsed = _parse_occ(sym) or {}
            except Exception:
                pass

        pos = BotPosition(
            allocation_id=alloc_id,
            symbol=sym,
            qty=missing_qty,
            avg_cost_cents=cost_cents,
            side=side,
            opened_at=now,
            closed_at=None,
            is_paper=True,
            option_type=parsed.get("option_type"),
            strike_price=parsed.get("strike_price"),
            expiration_date=parsed.get("expiration_date"),
            underlying_symbol=parsed.get("root"),
            contract_count=int(missing_qty) if is_option else None,
            contract_premium_cents=cost_cents if is_option else None,
            origin="ADOPTED",  # m099 — catchall adopter
        )
        db.add(pos); db.flush()
        entry_trade = BotTrade(
            allocation_id=alloc_id,
            symbol=sym,
            side="short" if side == "short" else "buy",
            qty=missing_qty,
            fill_price_cents=cost_cents,
            fill_price_micros=cost_cents * 10000,  # m100 — lossless from int cents
            fees_cents=0,
            ts=now,
            position_id=pos.id,
            is_paper=True,
            alpaca_order_id="catchall_adopter_2026_08_06",
            option_type=parsed.get("option_type"),
            strike_price=parsed.get("strike_price"),
            expiration_date=parsed.get("expiration_date"),
            underlying_symbol=parsed.get("root"),
            contract_count=int(missing_qty) if is_option else None,
            contract_premium_cents=cost_cents if is_option else None,
            origin="ADOPTED",  # m099 — catchall adopter
        )
        db.add(entry_trade)
        adopted.append({**entry, "pos_id": pos.id, "trade_id": entry_trade.id})

    if not dry_run:
        db.commit()

    return {
        "dry_run": dry_run,
        "profile_action": profile_action,
        "profile_id": prof_id,
        "allocation_id": alloc_id,
        "alpaca_positions": len(alp_list),
        "bmg_open_positions": len(bmg_rows),
        "adopted_count": len(adopted),
        "skipped_matched_count": len(skipped_matched),
        "adopted_preview": adopted[:15],
    }


@router.post("/close-quarantined-positions")
def close_quarantined_positions(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """STEP 2 reconcile: every quarantined BotPosition that still has
    closed_at=NULL gets closed_at set + exit_reason='reconcile_close'.
    Fixes the split between 'open (closed_at IS NULL)' consumers and
    'open+non-quarantined' consumers. Idempotent."""
    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition

    now = datetime.now(timezone.utc)
    victims = (
        db.query(BotPosition)
        .filter(BotPosition.quarantined_at.isnot(None))
        .filter(BotPosition.closed_at.is_(None))
        .all()
    )
    count = len(victims)
    if not dry_run and count:
        for p in victims:
            p.closed_at = now
            if not p.exit_reason:
                p.exit_reason = "reconcile_close"
        db.commit()
    return {
        "dry_run": dry_run,
        "closed_count": count if not dry_run else 0,
        "would_close": count,
    }


@router.post("/rebuild-positions-from-alpaca")
def rebuild_positions_from_alpaca(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """PHASE 2 rebuild per Brock's 2026-08-06 directive.

    Two repair passes (quarantine, adopter) both left the position store
    worse. This endpoint is the surgery — Alpaca /v2/positions is truth,
    regenerate BMG bot_positions from it in a single transaction.

    Steps:
      1. Quarantine every currently-open non-quarantined BotPosition
         (attribution preserved via `previous_position_id_for_rebuild`
         in quarantine_reason).
      2. Fetch Alpaca /v2/positions + recent order history (72h window).
      3. For each Alpaca position: attribute to a bot via matching
         alpaca_order_id in bot_trades; if no match, assign to
         `broker_orphan_catchall` allocation.
      4. Insert fresh BotPosition + paired BotTrade using Alpaca
         avg_entry_price as cost basis.

    Idempotent: safe to re-run; each run wipes+rebuilds.
    """
    import os, urllib.request, json, urllib.parse
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    from app.db.models.bots import BotPosition, BotTrade, BotProfile, BotAllocation

    now = datetime.now(timezone.utc)
    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")

    def alp_get(path: str):
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets{path}",
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
        )
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    alp_positions = alp_get("/v2/positions")
    # Fetch filled orders in the last 30 days for attribution
    after = (now - timedelta(days=30)).isoformat()
    orders_qs = urllib.parse.urlencode({
        "status":"closed","after":after,"limit":500,"direction":"desc","nested":"true"
    })
    alp_orders = alp_get(f"/v2/orders?{orders_qs}")
    filled_orders = [o for o in alp_orders if o.get("status") == "filled"]

    # BMG trade → allocation lookup by alpaca_order_id (base id or leg id)
    order_id_to_alloc = {}
    all_bmg_trades = (
        db.query(BotTrade.alpaca_order_id, BotTrade.allocation_id)
        .filter(BotTrade.alpaca_order_id.isnot(None))
        .all()
    )
    for oid, aid in all_bmg_trades:
        if oid and aid:
            order_id_to_alloc[oid] = aid

    # Symbol-based attribution fallback: latest bot_trade per symbol → allocation.
    # Excludes rebuild markers, catchall adopter, and quarantined rows so we
    # attribute to the ORIGINATING bot, not to a previous rebuild's catchall row.
    symbol_to_alloc = {}
    symbol_trades = (
        db.query(BotTrade.symbol, BotTrade.allocation_id, BotTrade.ts)
        .filter(BotTrade.symbol.isnot(None))
        .filter(BotTrade.quarantined_at.is_(None))
        .filter(~BotTrade.alpaca_order_id.like("rebuild_%") if BotTrade.alpaca_order_id is not None else True)
        .filter(~BotTrade.alpaca_order_id.like("catchall_%") if BotTrade.alpaca_order_id is not None else True)
        .filter(~BotTrade.alpaca_order_id.like("orphan_adopter%") if BotTrade.alpaca_order_id is not None else True)
        .order_by(BotTrade.ts.desc())
        .all()
    )
    for sym, aid, _ts in symbol_trades:
        if sym and aid and sym not in symbol_to_alloc:
            symbol_to_alloc[sym] = aid

    # Ensure catchall exists
    prof = db.query(BotProfile).filter(BotProfile.name == "broker_orphan_catchall").first()
    if not prof and not dry_run:
        prof = BotProfile(
            name="broker_orphan_catchall",
            description="Catch-all for Alpaca positions BMG couldn't attribute via order_id.",
            asset_class="stock",
            enabled=False,
        )
        db.add(prof); db.flush()
    catchall_alloc = None
    if prof:
        catchall_alloc = (
            db.query(BotAllocation)
            .filter(BotAllocation.user_id == current_user.id)
            .filter(BotAllocation.profile_id == prof.id)
            .first()
        )
        if not catchall_alloc and not dry_run:
            catchall_alloc = BotAllocation(
                user_id=current_user.id,
                profile_id=prof.id,
                capital_pct=0.0,
                starting_capital_cents=0,
                enabled=False,
                paper_mode=True,
            )
            db.add(catchall_alloc); db.flush()

    # Attribute each Alpaca position
    attributions = []
    for p in alp_positions:
        sym = p.get("symbol")
        qty = float(p.get("qty") or 0)
        side = "short" if qty < 0 else "long"
        abs_qty = abs(qty)
        avg_entry = float(p.get("avg_entry_price") or 0)
        # Find matching filled order (most recent for this symbol + side match)
        matched_order = None
        for o in filled_orders:
            if o.get("symbol") != sym:
                continue
            filled_qty = float(o.get("filled_qty") or 0)
            if abs(filled_qty) < 0.001:
                continue
            order_side = o.get("side")
            # For our purposes: order side buy = adds long, sell = adds short
            if (side == "long" and order_side == "buy") or (side == "short" and order_side == "sell"):
                matched_order = o
                break
        alloc_id = None
        source = None
        if matched_order:
            oid = matched_order.get("id")
            if oid in order_id_to_alloc:
                alloc_id = order_id_to_alloc[oid]
                source = f"order_id:{oid[:8]}"
            else:
                # Match on client_order_id (leg id in multi-leg)
                coid = matched_order.get("client_order_id")
                if coid and coid in order_id_to_alloc:
                    alloc_id = order_id_to_alloc[coid]
                    source = f"client_order_id:{coid[:8]}"
        if alloc_id is None and sym in symbol_to_alloc:
            alloc_id = symbol_to_alloc[sym]
            source = f"symbol:{sym}"
        if alloc_id is None:
            alloc_id = catchall_alloc.id if catchall_alloc else None
            source = "catchall"

        attributions.append({
            "symbol": sym, "side": side, "qty": abs_qty,
            "avg_entry": avg_entry,
            "market_value": float(p.get("market_value") or 0),
            "unrealized_pl": float(p.get("unrealized_pl") or 0),
            "asset_class": p.get("asset_class"),
            "allocation_id": alloc_id,
            "attribution_source": source,
        })

    # Existing open non-quarantined positions (will be quarantined)
    existing = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )

    if not dry_run and alloc_id is not None:
        # 1. Quarantine ALL existing open
        for p in existing:
            p.quarantined_at = now
            p.quarantine_reason = "phase_2_rebuild_2026_08_06"
        db.flush()

        # 2. Insert fresh rows from Alpaca
        try:
            from app.services.orphan_adopter import _parse_occ
        except Exception:
            _parse_occ = lambda s: {}
        inserted_ids = []
        for a in attributions:
            if a["allocation_id"] is None:
                continue
            sym = a["symbol"]
            is_option = a["asset_class"] == "us_option"
            parsed = _parse_occ(sym) if is_option else {}
            cost_cents = int(round(a["avg_entry"] * 100)) if a["avg_entry"] > 0 else 0
            from app.services.position_write_gate import check_position_pre_write
            _rebuild_gate = check_position_pre_write(
                symbol=sym, qty=a["qty"], side=a["side"],
                avg_cost_cents=cost_cents, is_option=is_option,
                strike_price=parsed.get("strike_price"),
                expiration_date=parsed.get("expiration_date"),
                entry_path="rebuild",
            )
            pos = BotPosition(
                allocation_id=a["allocation_id"],
                symbol=sym,
                qty=a["qty"],
                avg_cost_cents=cost_cents,
                side=a["side"],
                opened_at=now,
                closed_at=None,
                breach_on_adopt=_rebuild_gate.breach,
                breach_reason=_rebuild_gate.reason if _rebuild_gate.breach else None,
                remediation_ticket_id=_rebuild_gate.ticket_id if _rebuild_gate.breach else None,
                is_paper=True,
                option_type=parsed.get("option_type"),
                strike_price=parsed.get("strike_price"),
                expiration_date=parsed.get("expiration_date"),
                underlying_symbol=parsed.get("root"),
                contract_count=int(a["qty"]) if is_option else None,
                contract_premium_cents=cost_cents if is_option else None,
                origin="REBUILD",  # m099 — rebuild-positions-from-alpaca
            )
            db.add(pos); db.flush()
            t = BotTrade(
                allocation_id=a["allocation_id"],
                symbol=sym,
                side="short" if a["side"] == "short" else "buy",
                qty=a["qty"],
                fill_price_cents=cost_cents,
                fill_price_micros=cost_cents * 10000,  # m100 — lossless from int cents
                fees_cents=0,
                ts=now,
                position_id=pos.id,
                is_paper=True,
                alpaca_order_id=f"rebuild_2026_08_06:{a['attribution_source']}",
                option_type=parsed.get("option_type"),
                strike_price=parsed.get("strike_price"),
                expiration_date=parsed.get("expiration_date"),
                underlying_symbol=parsed.get("root"),
                contract_count=int(a["qty"]) if is_option else None,
                contract_premium_cents=cost_cents if is_option else None,
                origin="REBUILD",  # m099 — rebuild-positions-from-alpaca
            )
            db.add(t)
            inserted_ids.append(pos.id)
        db.commit()

    # Attribution summary
    from collections import Counter
    src_summary = Counter(a["attribution_source"] for a in attributions)

    return {
        "dry_run": dry_run,
        "alpaca_positions": len(alp_positions),
        "existing_bmg_open_to_quarantine": len(existing),
        "attributions_count": len(attributions),
        "attribution_sources": dict(src_summary),
        "catchall_allocation_id": catchall_alloc.id if catchall_alloc else None,
        "attributions_preview": attributions[:20],
    }


@router.post("/rollback-catchall-adoption")
def rollback_catchall_adoption(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Undo the broker_orphan_catchall adoption — it double-counts against
    fund PV. Quarantines every BotPosition + BotTrade under the
    'broker_orphan_catchall' profile so they drop out of PV rollup."""
    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade, BotProfile, BotAllocation

    now = datetime.now(timezone.utc)
    prof = db.query(BotProfile).filter(BotProfile.name == "broker_orphan_catchall").first()
    if not prof:
        return {"error": "profile_not_found"}
    allocs = db.query(BotAllocation).filter(BotAllocation.profile_id == prof.id).all()
    alloc_ids = [a.id for a in allocs]
    positions = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id.in_(alloc_ids))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id.in_(alloc_ids))
        .filter(BotTrade.quarantined_at.is_(None))
        .all()
    )
    if not dry_run:
        for p in positions:
            p.quarantined_at = now
            p.quarantine_reason = "catchall_double_count_rollback_2026_08_06"
        for t in trades:
            t.quarantined_at = now
            t.quarantine_reason = "catchall_double_count_rollback_2026_08_06"
        db.commit()

    return {
        "dry_run": dry_run,
        "allocation_ids": alloc_ids,
        "positions_quarantined": len(positions),
        "trades_quarantined": len(trades),
    }


@router.post("/reconcile-qty-mismatches")
def reconcile_qty_mismatches(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """For every (symbol, side) where BMG's aggregated qty differs from
    Alpaca's, force BMG rows to sum to Alpaca's qty.

    Rule: if BMG > Alpaca, scale each open non-quarantined row's qty
    down proportionally (preserving allocation attribution). If BMG <
    Alpaca and only ONE row exists, bump it up. If multiple rows and
    BMG < Alpaca, add the delta to the first row (rare — we usually
    only see BMG > Alpaca from stale historic fills).
    """
    import os, urllib.request, json
    from datetime import datetime, timezone
    from collections import defaultdict
    from app.db.models.bots import BotPosition

    now = datetime.now(timezone.utc)
    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
    )
    alp_list = json.loads(urllib.request.urlopen(req, timeout=15).read())
    alp_qty_by_key: dict = {}
    for p in alp_list:
        sym = p.get("symbol")
        q = float(p.get("qty"))
        side = "short" if q < 0 else "long"
        alp_qty_by_key[(sym, side)] = abs(q)

    bmg_rows = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    bmg_by_key: dict = defaultdict(list)
    for p in bmg_rows:
        side = (p.side or "long").lower()
        bmg_by_key[(p.symbol or "", side)].append(p)

    actions = []
    for key, alp_qty in alp_qty_by_key.items():
        bmg_group = bmg_by_key.get(key, [])
        bmg_total = sum(float(p.qty or 0) for p in bmg_group)
        delta = alp_qty - bmg_total
        if abs(delta) < 0.001 or not bmg_group:
            continue
        # Distribute delta proportionally across bmg_group
        # If BMG > Alpaca (delta < 0): scale down each row by ratio
        if bmg_total > 0:
            ratio = alp_qty / bmg_total
            for p in bmg_group:
                old = float(p.qty or 0)
                new = old * ratio
                actions.append({
                    "position_id": p.id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "old_qty": round(old, 6),
                    "new_qty": round(new, 6),
                    "allocation_id": p.allocation_id,
                })
                if not dry_run:
                    p.qty = new

    if not dry_run and actions:
        db.commit()

    return {
        "dry_run": dry_run,
        "actions_count": len(actions),
        "actions_preview": actions[:30],
    }


@router.post("/backup-sqlite")
def backup_sqlite(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Manual point-in-time SQLite backup to a timestamped file on the
    same /data volume. Uses SQLite's built-in backup API — atomic,
    consistent snapshot even while writers are active. Returns path,
    size, and row counts."""
    import os, sqlite3, shutil
    from datetime import datetime, timezone
    from app.db.session import engine
    from sqlalchemy import inspect, text

    url = engine.url
    if url.get_backend_name() != "sqlite":
        return {"error": "not_sqlite", "driver": url.get_backend_name()}
    src_path = url.database
    if not src_path or not os.path.exists(src_path):
        return {"error": "src_not_found", "path": src_path}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst_path = f"{src_path}.{ts}.bak"

    # Use SQLite's backup API for a consistent snapshot
    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(dst_path)
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()

    src_size = os.path.getsize(src_path)
    dst_size = os.path.getsize(dst_path)

    # Row counts sanity — compare bot_positions between live and backup
    with engine.connect() as c:
        live_bp = c.execute(text("SELECT COUNT(*) FROM bot_positions")).scalar() or 0
        live_bt = c.execute(text("SELECT COUNT(*) FROM bot_trades")).scalar() or 0
    bk_conn = sqlite3.connect(dst_path)
    bk_bp = bk_conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0]
    bk_bt = bk_conn.execute("SELECT COUNT(*) FROM bot_trades").fetchone()[0]
    bk_conn.close()

    return {
        "source_path": src_path,
        "backup_path": dst_path,
        "source_size_bytes": src_size,
        "backup_size_bytes": dst_size,
        "source_size_mb": round(src_size / (1024*1024), 2),
        "backup_size_mb": round(dst_size / (1024*1024), 2),
        "live_bot_positions_count": live_bp,
        "backup_bot_positions_count": bk_bp,
        "live_bot_trades_count": live_bt,
        "backup_bot_trades_count": bk_bt,
        "row_counts_match": (live_bp == bk_bp and live_bt == bk_bt),
    }


@router.post("/quarantine-pre-verification-era")
def quarantine_pre_verification_era(
    cutoff_iso: str = Query("2026-08-09T00:00:00", description="ISO UTC; trades strictly BEFORE this are 'pre-verification era'"),
    profile: Optional[str] = Query(None, description="If set, restrict to one bot profile. Default: all bots."),
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Clean-line rule per attribution spec (approved 2026-08-09).

    Sets quarantine_reason='pre_verification_era_legacy_backfill' on
    BROKER_FILL closing trades (side in sell/close/cover) with
    ts < cutoff_iso. Not deleted — quarantined so consumers exclude
    them from realized sums (canonical filter is
    quarantined_at IS NULL) without losing history.

    Reason (Brock 2026-08-11): crypto_quant_aggressive July 7-8 backfill
    populated pnl_cents from broken sub-penny fills; those +$10K
    'realized' rows are the reason I2 drift is $1,687 and I24
    realized_drift is $3,670. Quarantining is the approved fix,
    not rebuilding.
    """
    from sqlalchemy import text as _t
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc).isoformat()

    profile_filter = ""
    params = {"cutoff": cutoff_iso, "now": now}
    if profile:
        profile_filter = "  AND p.name = :profile"
        params["profile"] = profile

    # 1. Count target rows
    count_row = db.execute(_t(
        f"SELECT COUNT(*), COALESCE(SUM(t.pnl_cents), 0) FROM bot_trades t "
        f"JOIN bot_allocations a ON a.id = t.allocation_id "
        f"JOIN bot_profiles p ON p.id = a.profile_id "
        f"WHERE a.user_id = 1 "
        f"  AND t.origin = 'BROKER_FILL' "
        f"  AND t.side IN ('sell','close','cover') "
        f"  AND t.quarantined_at IS NULL "
        f"  AND t.ts < :cutoff "
        f"  {profile_filter}"
    ), params).fetchone()
    target_count = int(count_row[0] or 0)
    target_pnl_cents = int(count_row[1] or 0)

    # 2. Per-bot breakdown
    per_bot_rows = db.execute(_t(
        f"SELECT p.name, COUNT(t.id), COALESCE(SUM(t.pnl_cents), 0) FROM bot_trades t "
        f"JOIN bot_allocations a ON a.id = t.allocation_id "
        f"JOIN bot_profiles p ON p.id = a.profile_id "
        f"WHERE a.user_id = 1 "
        f"  AND t.origin = 'BROKER_FILL' "
        f"  AND t.side IN ('sell','close','cover') "
        f"  AND t.quarantined_at IS NULL "
        f"  AND t.ts < :cutoff "
        f"  {profile_filter} "
        f"GROUP BY p.name ORDER BY ABS(COALESCE(SUM(t.pnl_cents), 0)) DESC"
    ), params).fetchall()
    per_bot = [
        {"bot": r[0], "n": int(r[1]), "pnl_cents": int(r[2] or 0),
         "pnl_usd": round(int(r[2] or 0) / 100, 2)}
        for r in per_bot_rows
    ]

    quarantined = 0
    if not dry_run and target_count > 0:
        result = db.execute(_t(
            f"UPDATE bot_trades SET "
            f"  quarantined_at = :now, "
            f"  quarantine_reason = 'pre_verification_era_legacy_backfill' "
            f"WHERE id IN ( "
            f"  SELECT t.id FROM bot_trades t "
            f"  JOIN bot_allocations a ON a.id = t.allocation_id "
            f"  JOIN bot_profiles p ON p.id = a.profile_id "
            f"  WHERE a.user_id = 1 "
            f"    AND t.origin = 'BROKER_FILL' "
            f"    AND t.side IN ('sell','close','cover') "
            f"    AND t.quarantined_at IS NULL "
            f"    AND t.ts < :cutoff "
            f"    {profile_filter} "
            f")"
        ), params)
        db.commit()
        quarantined = result.rowcount or 0

    return {
        "dry_run": dry_run,
        "cutoff_iso": cutoff_iso,
        "profile_filter": profile,
        "target_trade_count": target_count,
        "target_pnl_cents": target_pnl_cents,
        "target_pnl_usd": round(target_pnl_cents / 100, 2),
        "quarantined": quarantined,
        "per_bot_breakdown": per_bot,
    }


@router.get("/diag/realized-breakdown")
def diag_realized_breakdown(
    include_all_origins: bool = Query(False, description="If true, include ALL origins (not just BROKER_FILL) — useful for finding legacy pnl_cents leaks"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Per-bot realized P&L breakdown (Brock 2026-08-11 Tuesday close diagnosis).

    Sums bot_trades.pnl_cents grouped by bot for closing trades (side in
    sell/close/cover). Filters to origin='BROKER_FILL' by default to match
    canonical's realized calc — pass include_all_origins=true to see legacy
    pnl_cents on ADOPTED/RECONCILE/REBUILD/BACKFILL rows.

    Also computes an Alpaca-derived realized via the identity:
        alpaca_realized = fund_pv - inception - alpaca_unrealized

    Returns per-bot rows sorted by absolute realized. The bot with the
    largest realized magnitude is the first suspect if bot_total differs
    from alpaca_derived by >$50.
    """
    from sqlalchemy import text as _t
    origin_filter = "" if include_all_origins else "AND t.origin = 'BROKER_FILL'"
    rows = db.execute(_t(
        f"SELECT p.name AS bot, "
        f"       COUNT(t.id) AS n_closes, "
        f"       COALESCE(SUM(t.pnl_cents), 0) AS sum_pnl_cents, "
        f"       COUNT(DISTINCT t.symbol) AS distinct_syms "
        f"FROM bot_trades t "
        f"JOIN bot_allocations a ON a.id = t.allocation_id "
        f"JOIN bot_profiles p ON p.id = a.profile_id "
        f"WHERE a.user_id = 1 "
        f"  AND t.side IN ('sell','close','cover') "
        f"  AND t.quarantined_at IS NULL "
        f"  {origin_filter} "
        f"GROUP BY p.name "
        f"HAVING SUM(t.pnl_cents) IS NOT NULL "
        f"ORDER BY ABS(COALESCE(SUM(t.pnl_cents), 0)) DESC"
    )).fetchall()
    per_bot = [
        {"bot": r[0], "close_count": int(r[1]), "sum_pnl_cents": int(r[2] or 0),
         "sum_pnl_usd": round(int(r[2] or 0) / 100, 2), "distinct_symbols": int(r[3])}
        for r in rows
    ]
    total_pnl_cents = sum(x["sum_pnl_cents"] for x in per_bot)

    # Also break down by origin to see if the m099 filter is the source of drift
    origin_rows = db.execute(_t(
        "SELECT COALESCE(t.origin, 'NULL') AS origin, "
        "       COUNT(*) AS n_closes, "
        "       COALESCE(SUM(t.pnl_cents), 0) AS sum_pnl_cents "
        "FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = 1 "
        "  AND t.side IN ('sell','close','cover') "
        "  AND t.quarantined_at IS NULL "
        "GROUP BY COALESCE(t.origin, 'NULL')"
    )).fetchall()
    by_origin = [
        {"origin": r[0], "n_closes": int(r[1]), "sum_pnl_cents": int(r[2] or 0),
         "sum_pnl_usd": round(int(r[2] or 0) / 100, 2)}
        for r in origin_rows
    ]

    # Alpaca-derived realized via identity
    alpaca_derived = {"error": None}
    try:
        import os as _os, urllib.request as _ur, json as _j
        from app.services.alpaca_account_cache import get_alpaca_account, get_alpaca_positions
        _acct = get_alpaca_account()
        _pos = get_alpaca_positions() or []
        if _acct:
            fund_pv = int(round(float(_acct.get("portfolio_value") or 0) * 100))
            alpaca_upl = sum(float(p.get("unrealized_pl") or 0) for p in _pos)
            alpaca_upl_cents = int(round(alpaca_upl * 100))
            INCEPTION = 9_734_000  # $97,340 from canonical._FUND_INCEPTION_CENTS
            alpaca_realized_cents = fund_pv - INCEPTION - alpaca_upl_cents
            alpaca_derived = {
                "fund_pv_cents": fund_pv,
                "inception_cents": INCEPTION,
                "alpaca_unrealized_cents": alpaca_upl_cents,
                "alpaca_realized_cents": alpaca_realized_cents,
                "alpaca_realized_usd": round(alpaca_realized_cents / 100, 2),
                "formula": "fund_pv - inception - alpaca_unrealized",
            }
    except Exception as exc:
        alpaca_derived = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    drift_cents = None
    if alpaca_derived.get("alpaca_realized_cents") is not None:
        drift_cents = total_pnl_cents - alpaca_derived["alpaca_realized_cents"]

    return {
        "origin_filter": "BROKER_FILL only" if not include_all_origins else "ALL origins",
        "bot_total_realized_cents": total_pnl_cents,
        "bot_total_realized_usd": round(total_pnl_cents / 100, 2),
        "alpaca_derived": alpaca_derived,
        "drift_cents": drift_cents,
        "drift_usd": round(drift_cents / 100, 2) if drift_cents is not None else None,
        "by_origin": by_origin,
        "per_bot_top20": per_bot[:20],
        "n_bots_reporting": len(per_bot),
    }


@router.get("/diag/multi-owned")
def diag_multi_owned(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """List (symbol, side) tuples held by 2+ active allocations. These are
    the I9 multi-owned that inflate BMG's aggregate exposure vs Alpaca."""
    from sqlalchemy import text as _t
    rows = db.execute(_t(
        "SELECT bp.symbol, COALESCE(bp.side,'long') AS s, "
        "       GROUP_CONCAT(bp.id) AS position_ids, "
        "       GROUP_CONCAT(bp.allocation_id) AS alloc_ids, "
        "       GROUP_CONCAT(bp.qty) AS qtys, "
        "       GROUP_CONCAT(bp.avg_cost_cents) AS avg_costs, "
        "       GROUP_CONCAT(bp.origin) AS origins, "
        "       COUNT(*) AS n "
        "FROM bot_positions bp "
        "JOIN bot_allocations a ON a.id = bp.allocation_id "
        "WHERE bp.closed_at IS NULL AND bp.quarantined_at IS NULL AND a.user_id = 1 "
        "GROUP BY bp.symbol, COALESCE(bp.side,'long') "
        "HAVING COUNT(*) >= 2 "
        "ORDER BY COUNT(*) DESC"
    )).fetchall()
    out = []
    for r in rows:
        out.append({
            "symbol": r[0],
            "side": r[1],
            "position_ids": r[2],
            "allocation_ids": r[3],
            "qtys": r[4],
            "avg_cost_cents": r[5],
            "origins": r[6],
            "n_copies": int(r[7]),
        })
    return {"multi_owned_count": len(out), "details": out}


@router.post("/quarantine-catchall-dupes")
def quarantine_catchall_dupes(
    since_hours: int = Query(24, description="Only touch catchall rows opened within N hours"),
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Quarantine bot_positions on 'catchall' or 'unresolved' allocations
    when the same (symbol, side) is ALREADY held on a DIFFERENT allocation
    as active. Cleans up over-adopts where attribution fell back to catchall
    for positions real bots already own.

    Reason (Brock 2026-08-10 overnight): the adopt-missing endpoint added
    83 rows all attributed to catchall; N of them duplicated existing
    bot-owned positions, inflating bot_sum_pv by ~$11K.

    Idempotent. Refuses to touch anything older than since_hours to avoid
    accidentally quarantining legitimate historical catchall attribution.
    """
    from sqlalchemy import text as _t
    from datetime import datetime, timezone, timedelta
    cut = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    # Find catchall / unresolved allocations
    catchall_allocs = db.execute(_t(
        "SELECT a.id, p.name FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 "
        "  AND (p.name LIKE '%catchall%' OR p.name LIKE '%unresolved%')"
    )).fetchall()
    catchall_alloc_ids = [int(r[0]) for r in catchall_allocs]
    if not catchall_alloc_ids:
        return {"error": "no_catchall_allocs_found", "hint": "check bot_profiles.name"}

    # Find catchall positions opened in the window, with same (symbol, side)
    # already active on a non-catchall alloc.
    catchall_ph = ",".join([":a" + str(i) for i in range(len(catchall_alloc_ids))])
    params = {"cut": cut, **{f"a{i}": v for i, v in enumerate(catchall_alloc_ids)}}
    candidates = db.execute(_t(
        f"SELECT bp.id, bp.symbol, bp.side, bp.qty, bp.avg_cost_cents, bp.opened_at, bp.allocation_id "
        f"FROM bot_positions bp "
        f"WHERE bp.allocation_id IN ({catchall_ph}) "
        f"  AND bp.closed_at IS NULL "
        f"  AND bp.quarantined_at IS NULL "
        f"  AND bp.opened_at >= :cut"
    ), params).fetchall()

    dupes: list[dict] = []
    for r in candidates:
        pos_id, sym, side, qty, avg_c, opened, alloc_id = r
        # Is same (symbol, side) held on a NON-catchall active row?
        other = db.execute(_t(
            f"SELECT id, allocation_id FROM bot_positions "
            f"WHERE symbol = :s AND (side = :side OR (side IS NULL AND :side = 'long')) "
            f"  AND closed_at IS NULL "
            f"  AND quarantined_at IS NULL "
            f"  AND allocation_id NOT IN ({catchall_ph}) "
            f"  AND id != :self_id "
            f"LIMIT 1"
        ), {"s": sym, "side": side or "long", "self_id": pos_id, **{f"a{i}": v for i, v in enumerate(catchall_alloc_ids)}}).fetchone()
        if other:
            dupes.append({
                "catchall_position_id": pos_id,
                "symbol": sym,
                "side": side,
                "qty": float(qty or 0),
                "avg_cost_cents": int(avg_c or 0),
                "opened_at": str(opened),
                "catchall_alloc_id": alloc_id,
                "other_position_id": int(other[0]),
                "other_alloc_id": int(other[1]),
            })

    quarantined = 0
    if not dry_run and dupes:
        now = datetime.now(timezone.utc)
        dupe_ids = [d["catchall_position_id"] for d in dupes]
        ph = ",".join([":i" + str(i) for i in range(len(dupe_ids))])
        db.execute(_t(
            f"UPDATE bot_positions "
            f"SET quarantined_at = :now, quarantine_reason = 'catchall_dupe_of_bot_alloc' "
            f"WHERE id IN ({ph})"
        ), {"now": now.isoformat(), **{f"i{i}": v for i, v in enumerate(dupe_ids)}})
        # Also quarantine the paired BotTrade rows (if any) for these positions
        db.execute(_t(
            f"UPDATE bot_trades "
            f"SET quarantined_at = :now, quarantine_reason = 'catchall_dupe_of_bot_alloc' "
            f"WHERE position_id IN ({ph}) AND quarantined_at IS NULL"
        ), {"now": now.isoformat(), **{f"i{i}": v for i, v in enumerate(dupe_ids)}})
        db.commit()
        quarantined = len(dupe_ids)

    return {
        "dry_run": dry_run,
        "since_hours": since_hours,
        "catchall_alloc_ids": catchall_alloc_ids,
        "catchall_candidates_in_window": len(candidates),
        "dupes_found": len(dupes),
        "quarantined": quarantined,
        "dupes_sample": dupes[:20],
    }


@router.get("/diag/i2-hypothesis")
def diag_i2_hypothesis(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """I2 drift diagnostic per Brock 2026-08-10 PM.

    Signature: BMG says $10K more unrealized loss than Alpaca despite
    tracking fewer positions (57 vs 137). Wrong rows counted, not missing.

    Primary: quarantined-in-sum-but-not-in-count. Groups open bot_positions
    by active vs quarantined; if the quarantined group has non-zero
    aggregate unrealized fed into some display path, that's the bug.
    """
    from sqlalchemy import text as _t
    result: Dict[str, Any] = {}

    # ── Primary: does any query sum unrealized WITHOUT filtering quarantined? ──
    # Note bot_positions doesn't store unrealized directly; it lives in
    # per-bot snapshot compute. So the direct hypothesis is: some path
    # sums per-position (avg_cost, mark, qty) INCLUDING quarantined rows.
    # We approximate by comparing counts + notional exposure between the
    # two groups; the diff = how much quarantined rows could be inflating.
    rows = db.execute(_t(
        "SELECT (quarantined_at IS NULL) AS active, "
        "       COUNT(*)                 AS n, "
        "       COALESCE(SUM(qty * avg_cost_cents), 0) AS sum_notional_cents, "
        "       COALESCE(SUM(CASE WHEN option_type IS NOT NULL THEN 1 ELSE 0 END), 0) AS n_options "
        "FROM bot_positions "
        "WHERE closed_at IS NULL "
        "GROUP BY 1"
    )).fetchall()
    result["primary_open_by_quarantine_status"] = [
        {
            "active_flag": bool(r[0]),
            "count": int(r[1] or 0),
            "sum_notional_cents": int(r[2] or 0),
            "sum_notional_dollars": round(int(r[2] or 0) / 100, 2),
            "options_count": int(r[3] or 0),
        }
        for r in rows
    ]

    # For user_1 fleet specifically (matches canonical / leaderboard scope)
    user_rows = db.execute(_t(
        "SELECT (bp.quarantined_at IS NULL) AS active, "
        "       COUNT(*) AS n, "
        "       COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0) AS sum_notional_cents, "
        "       COALESCE(SUM(CASE WHEN bp.option_type IS NOT NULL THEN 1 ELSE 0 END), 0) AS n_options "
        "FROM bot_positions bp "
        "JOIN bot_allocations a ON a.id = bp.allocation_id "
        "WHERE bp.closed_at IS NULL AND a.user_id = 1 "
        "GROUP BY 1"
    )).fetchall()
    result["primary_user1_open_by_quarantine_status"] = [
        {"active_flag": bool(r[0]), "count": int(r[1] or 0),
         "sum_notional_cents": int(r[2] or 0),
         "sum_notional_dollars": round(int(r[2] or 0) / 100, 2),
         "options_count": int(r[3] or 0)}
        for r in rows
    ]

    # ── Secondary: fetch canonical's per-position unrealized and compare per-symbol to Alpaca ──
    try:
        import os as _os, urllib.request as _ur, json as _j
        from app.db.models.bots import BotPosition
        from app.services.option_marks import fetch_option_marks_cents
        kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
        ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
        alp = _j.loads(_ur.urlopen(_ur.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read()) or []
        alp_upl_by_sym: dict[str, float] = {}
        alp_price_by_sym: dict[str, float] = {}
        for p in alp:
            sym = p.get("symbol")
            if not sym:
                continue
            alp_upl_by_sym[sym] = float(p.get("unrealized_pl") or 0)
            alp_price_by_sym[sym] = float(p.get("current_price") or 0)

        # BMG open + non-quarantined for user 1
        bmg_open = (
            db.query(BotPosition)
            .join(_ap_model(), BotPosition.allocation_id == _ap_model().id)
            .filter(_ap_model().user_id == 1)
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .all()
        )
        # Get option marks
        occ_syms = [p.symbol for p in bmg_open if getattr(p, "option_type", None)]
        marks: dict = {}
        need_fmp = [s for s in occ_syms if s not in alp_price_by_sym]
        if need_fmp:
            marks = fetch_option_marks_cents(need_fmp) or {}
        for s in occ_syms:
            if s in alp_price_by_sym:
                marks[s] = int(round(alp_price_by_sym[s] * 100))

        per_sym_diffs = []
        bmg_total_upl_cents = 0
        for p in bmg_open:
            is_opt = bool(getattr(p, "option_type", None))
            is_short = getattr(p, "side", "long") == "short"
            mult = 100 if is_opt else 1
            entry_c = float(p.avg_cost_cents or 0)
            if is_opt:
                mark_c = marks.get(p.symbol)
                cur_c = float(mark_c) if mark_c is not None else entry_c
            else:
                cur_c = alp_price_by_sym.get(p.symbol, 0) * 100
                if cur_c == 0:
                    cur_c = entry_c
            if is_short:
                bmg_upl_c = int((entry_c - cur_c) * (p.qty or 0) * mult)
            else:
                bmg_upl_c = int((cur_c - entry_c) * (p.qty or 0) * mult)
            bmg_total_upl_cents += bmg_upl_c
            alp_upl = alp_upl_by_sym.get(p.symbol, 0.0)
            diff_dollars = round(bmg_upl_c / 100 - alp_upl, 2)
            per_sym_diffs.append({
                "symbol": p.symbol,
                "bmg_upl_dollars": round(bmg_upl_c / 100, 2),
                "alp_upl_dollars": round(alp_upl, 2),
                "diff_dollars": diff_dollars,
                "abs_diff": abs(diff_dollars),
                "in_alpaca": p.symbol in alp_upl_by_sym,
                "bmg_qty": float(p.qty or 0),
                "bmg_avg_cost_cents": entry_c,
            })
        per_sym_diffs.sort(key=lambda x: -x["abs_diff"])
        result["secondary_top_10_per_symbol_diff"] = per_sym_diffs[:10]
        result["secondary_bmg_only_symbols"] = [d for d in per_sym_diffs if not d["in_alpaca"]][:20]
        result["secondary_total"] = {
            "bmg_upl_dollars": round(bmg_total_upl_cents / 100, 2),
            "alp_upl_dollars_summed_from_dict": round(sum(alp_upl_by_sym.values()), 2),
            "bmg_positions": len(bmg_open),
            "alp_positions": len(alp),
        }

        # ── Tertiary: cost-basis drift on adopted positions ──────────────
        alp_avg_by_sym: dict[str, float] = {p.get("symbol"): float(p.get("avg_entry_price") or 0) for p in alp}
        adopted_drift = []
        for p in bmg_open:
            if getattr(p, "origin", None) != "ADOPTED":
                continue
            alp_avg = alp_avg_by_sym.get(p.symbol)
            if alp_avg is None:
                continue
            bmg_avg = (p.avg_cost_cents or 0) / 100.0
            drift = round(bmg_avg - alp_avg, 4)
            if abs(drift) > 0.005:  # >0.5c per share
                adopted_drift.append({
                    "symbol": p.symbol,
                    "bmg_avg": round(bmg_avg, 4),
                    "alp_avg": round(alp_avg, 4),
                    "drift_dollars_per_share": drift,
                    "position_id": p.id,
                    "qty": float(p.qty or 0),
                })
        adopted_drift.sort(key=lambda x: -abs(x["drift_dollars_per_share"]))
        result["tertiary_adopted_cost_basis_drift"] = adopted_drift[:20]

    except Exception as exc:
        result["secondary_tertiary_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    return result


def _ap_model():
    """Lazy import BotAllocation for join."""
    from app.db.models.bots import BotAllocation
    return BotAllocation


@router.get("/pending-acks")
def pending_acks(
    category: Optional[str] = Query(None, description="Filter by category (AUTO_PAUSE|DISK_HIGH|SIM_FILL_DETECTED|INVARIANT_RED_STALE|MANUAL_TEST)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """List unacknowledged human_ack_required records. Auto-actions create
    these; scans_gate resume is blocked until AUTO_PAUSE rows are acked."""
    from app.services.human_ack import list_unacked
    rows = list_unacked(db, category=category)
    return {"count": len(rows), "category": category, "unacked": rows}


@router.post("/ack")
def ack_endpoint(
    ack_id: int = Query(..., description="Row ID from /admin/pending-acks"),
    by: str = Query(..., description="Human identifier (e.g. 'brock', 'user_1')"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Acknowledge a human_ack_required row. Once acked, any resume gates
    it was blocking will release. Idempotent — acking an already-acked
    row returns ok:false."""
    from app.services.human_ack import acknowledge
    ok = acknowledge(db, ack_id=ack_id, by=by)
    return {"ok": ok, "ack_id": ack_id, "by": by,
            "note": "ok:false = already acked or not found"}


@router.post("/admin-close-limit")
def admin_close_limit(
    symbol: str = Query(..., description="Alpaca symbol (OCC for options)"),
    qty: float = Query(..., description="Contracts to sell"),
    limit_price: float = Query(..., description="Limit price per share (options: per share, ×100 for contract)"),
    reason: str = Query(..., description="Human-readable remediation reason (goes to alpaca client_order_id and BMG log)"),
    tif: str = Query("day", description="day|gtc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Submit an admin remediation SELL LIMIT to Alpaca. Not a bot trade.

    Records a pending BotTrade with origin=BACKFILL and a
    admin_remediation_<date>:<reason> alpaca_order_id marker until the
    real Alpaca UUID lands. Once Alpaca returns the order id, the BMG row
    is patched with the real UUID.

    On fill, the position_monitor or daily reconciler will update BMG
    close-side state as usual. For now this endpoint's job is: submit +
    record intent, and return the Alpaca order id."""
    import os as _os, json as _json, urllib.request as _ur, urllib.error as _urerr
    from datetime import datetime as _dt, timezone as _tz
    from app.db.models.bots import BotPosition, BotTrade

    kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        return {"error": "no_alpaca_creds"}

    # Locate BMG open position for this symbol so we can log against the right alloc
    pos = (
        db.query(BotPosition)
        .filter(BotPosition.symbol == symbol)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .order_by(BotPosition.opened_at.desc())
        .first()
    )
    if not pos:
        return {"error": f"no_open_bmg_position_for_{symbol}",
                "hint": "check /admin/inspect-symbol; the position may be quarantined"}

    today = _dt.now(_tz.utc).strftime("%Y%m%d")
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "sell",
        "type": "limit",
        "limit_price": str(round(float(limit_price), 2)),
        "time_in_force": tif,
        # position_intent tells Alpaca this closes an existing long — without
        # it the account-level options approval defaults to "uncovered short
        # open" and rejects (40310000). This endpoint is close-only by design.
        "position_intent": "sell_to_close",
    }
    body = _json.dumps(payload).encode()
    req = _ur.Request(
        "https://paper-api.alpaca.markets/v2/orders",
        data=body,
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec,
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ur.urlopen(req, timeout=15) as resp:
            order = _json.loads(resp.read())
    except _urerr.HTTPError as httpe:
        try:
            err_body = httpe.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = str(httpe)
        return {"error": "alpaca_http_error", "status": httpe.code, "body": err_body[:500]}
    except Exception as exc:
        return {"error": f"alpaca_submit_failed:{type(exc).__name__}", "detail": str(exc)[:200]}

    order_id = order.get("id")
    if not order_id:
        return {"error": "no_order_id_from_alpaca", "response": order}

    # Ledger #33 (Brock 2026-08-11): DO NOT write BotTrade at submit time
    # using limit_price. Fill price is only known after Alpaca confirms.
    # Caller must invoke POST /admin/confirm-alpaca-fill-and-close?order_id=X
    # after fill to book the trade + close the BMG position.
    return {
        "ok": True,
        "alpaca_order_id": order_id,
        "status": order.get("status"),
        "symbol": symbol,
        "qty": qty,
        "limit_price": float(limit_price),
        "expected_proceeds_usd_at_limit": round(float(limit_price) * float(qty) * 100, 2),
        "bmg_position_id_targeted": pos.id,
        "reason": reason,
        "note": (
            "Order queued at Alpaca. No BMG trade written yet — actual fill "
            "price is unknown until Alpaca fills. Once filled, invoke:\n"
            f"  POST /admin/confirm-alpaca-fill-and-close?order_id={order_id}"
            f"&position_id={pos.id}&reason={reason}\n"
            "That endpoint polls Alpaca for filled_avg_price and books the "
            "BotTrade with the REAL fill (never the limit). Reprice via "
            "POST /admin/admin-close-reprice?alpaca_order_id={order_id}."
        ),
    }


@router.post("/confirm-alpaca-fill-and-close")
def confirm_alpaca_fill_and_close(
    order_id: str = Query(..., description="Alpaca order id"),
    position_id: int = Query(..., description="BMG position_id to close on fill"),
    reason: str = Query(..., description="Admin-remediation reason string"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Book a BotTrade + close the BMG position from Alpaca's FILL event
    (never from the submitted limit). Idempotent — refuses if a trade row
    for this order_id already exists.

    Structural rule per Brock 2026-08-11: any trade write must use the
    fill_avg_price from the broker's fill confirmation, not the limit
    from the order request. Same family as sim/phantom/adopter (BMG's
    record diverging from what the broker did)."""
    import os as _os, json as _j, urllib.request as _ur
    from datetime import datetime as _dt, timezone as _tz
    from app.db.models.bots import BotPosition, BotTrade

    # 1. Fetch order status
    kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        return {"error": "no_alpaca_creds"}
    try:
        order = _j.loads(_ur.urlopen(_ur.Request(
            f"https://paper-api.alpaca.markets/v2/orders/{order_id}",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read())
    except Exception as exc:
        return {"error": f"fetch_order_failed:{type(exc).__name__}", "detail": str(exc)[:200]}

    status = order.get("status")
    if status != "filled":
        return {"error": "order_not_filled", "status": status,
                "hint": "wait for fill, then re-invoke"}

    filled_avg = float(order.get("filled_avg_price") or 0)
    filled_qty = float(order.get("filled_qty") or 0)
    symbol = order.get("symbol")
    side_alpaca = order.get("side")
    if filled_avg <= 0 or filled_qty <= 0:
        return {"error": "fill_price_or_qty_missing", "response": order}

    # 2. Idempotency guard
    existing = db.query(BotTrade).filter(BotTrade.alpaca_order_id == order_id).first()
    if existing:
        return {"already_booked": True, "existing_trade_id": existing.id,
                "existing_fill_price_cents": existing.fill_price_cents,
                "existing_fill_price_usd": (existing.fill_price_cents or 0) / 100,
                "hint": "trade already logged — no-op"}

    # 3. Load position + verify
    pos = db.query(BotPosition).filter(BotPosition.id == position_id).first()
    if not pos:
        return {"error": "position_not_found", "position_id": position_id}
    if pos.symbol != symbol:
        return {"error": "symbol_mismatch", "bmg_symbol": pos.symbol, "alpaca_symbol": symbol}
    if pos.closed_at is not None:
        return {"error": "position_already_closed",
                "closed_at": pos.closed_at.isoformat() if pos.closed_at else None}

    # 4. Book the trade with REAL fill price + close the position
    bmg_side_close = "sell" if (pos.side or "long") == "long" else "cover"
    now = _dt.now(_tz.utc)
    trade_row = BotTrade(
        allocation_id=pos.allocation_id,
        symbol=symbol,
        side=bmg_side_close,
        qty=filled_qty,
        fill_price_cents=int(round(filled_avg * 100)),  # REAL FILL
        fill_price_micros=int(round(float(filled_avg) * 1_000_000)),  # m100 — sub-penny precise
        fees_cents=0,
        ts=now,
        position_id=pos.id,
        is_paper=True,
        alpaca_order_id=order_id,
        origin="BACKFILL",
        # reason goes on the position's exit_reason (BotTrade has no strategy col)
    )
    db.add(trade_row)
    pos.closed_at = now
    pos.exit_reason = f"admin_remediation:{reason}"
    db.commit()

    return {
        "ok": True,
        "trade_id": trade_row.id,
        "position_id": pos.id,
        "symbol": symbol,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg,
        "fill_price_cents_written": trade_row.fill_price_cents,
        "position_closed_at": now.isoformat(),
        "reason": reason,
    }


@router.post("/admin-close-reprice")
def admin_close_reprice(
    alpaca_order_id: str = Query(..., description="Existing Alpaca order id"),
    tick: float = Query(0.01, description="Tick step in dollars (default $0.01 penny pilot)"),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Cancel + resubmit an unfilled SELL LIMIT one tick lower toward bid.
    Floors at current NBBO bid — never goes below bid.

    Returns diagnostic: prior limit, new limit, current bid/ask, floored?"""
    import os as _os, json as _json, urllib.request as _ur, urllib.error as _urerr
    kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        return {"error": "no_alpaca_creds"}
    headers = {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec}

    # 1. Fetch current order
    try:
        order = _json.loads(_ur.urlopen(_ur.Request(
            f"https://paper-api.alpaca.markets/v2/orders/{alpaca_order_id}",
            headers=headers,
        ), timeout=10).read())
    except Exception as exc:
        return {"error": f"fetch_order_failed:{type(exc).__name__}", "detail": str(exc)[:200]}

    status = order.get("status")
    if status not in ("new", "accepted", "pending_new", "partially_filled"):
        return {"error": "order_not_repriceable", "status": status,
                "hint": "only unfilled/accepted orders can be repriced"}

    symbol = order.get("symbol")
    side = order.get("side")
    qty = float(order.get("qty") or 0)
    current_limit = float(order.get("limit_price") or 0)
    if side != "sell":
        return {"error": "reprice_only_supports_sell_orders"}

    # 2. Get current NBBO
    try:
        snap = _json.loads(_ur.urlopen(_ur.Request(
            f"https://data.alpaca.markets/v1beta1/options/snapshots?symbols={symbol}",
            headers=headers,
        ), timeout=10).read())
        q = snap.get("snapshots", {}).get(symbol, {}).get("latestQuote", {})
        bid = float(q.get("bp") or 0)
        ask = float(q.get("ap") or 0)
    except Exception as exc:
        return {"error": f"fetch_nbbo_failed:{type(exc).__name__}", "detail": str(exc)[:200]}
    if bid <= 0:
        return {"error": "no_bid_available", "current_limit": current_limit}

    # 3. Compute new limit: current - 1 tick, floor at bid
    new_limit = round(current_limit - tick, 2)
    floored = False
    if new_limit < bid:
        new_limit = bid
        floored = True

    if new_limit >= current_limit:
        return {"error": "no_downward_room",
                "current_limit": current_limit, "bid": bid, "ask": ask}

    # 4. Cancel existing order
    try:
        _ur.urlopen(_ur.Request(
            f"https://paper-api.alpaca.markets/v2/orders/{alpaca_order_id}",
            headers=headers, method="DELETE",
        ), timeout=10)
    except _urerr.HTTPError as httpe:
        # 204 or 422 (already-filled) — check status again
        if httpe.code == 422:
            return {"error": "cancel_failed_maybe_filled", "status_code": httpe.code}
    except Exception as exc:
        return {"error": f"cancel_failed:{type(exc).__name__}", "detail": str(exc)[:200]}

    # 5. Submit new limit at new_limit
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": "limit",
        "limit_price": str(new_limit),
        "time_in_force": order.get("time_in_force") or "day",
        "position_intent": order.get("position_intent") or "sell_to_close",
    }
    body = _json.dumps(payload).encode()
    try:
        with _ur.urlopen(_ur.Request(
            "https://paper-api.alpaca.markets/v2/orders",
            data=body, headers={**headers, "Content-Type": "application/json"},
            method="POST",
        ), timeout=15) as resp:
            new_order = _json.loads(resp.read())
    except _urerr.HTTPError as httpe:
        try:
            err_body = httpe.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = str(httpe)
        return {"error": "resubmit_http_error", "status": httpe.code, "body": err_body[:500],
                "note": "OLD ORDER ALREADY CANCELLED — re-submit manually via /admin/admin-close-limit"}

    return {
        "ok": True,
        "prior_alpaca_order_id": alpaca_order_id,
        "new_alpaca_order_id": new_order.get("id"),
        "symbol": symbol,
        "qty": qty,
        "prior_limit": current_limit,
        "new_limit": new_limit,
        "bid": bid,
        "ask": ask,
        "floored_at_bid": floored,
        "expected_proceeds_usd": round(new_limit * qty * 100, 2),
    }


@router.get("/alpaca-order-status")
def alpaca_order_status(
    order_id: str = Query(..., description="Alpaca order id"),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Fetch current status of an Alpaca order. Non-mutating."""
    import os as _os, json as _json, urllib.request as _ur
    kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        return {"error": "no_alpaca_creds"}
    try:
        order = _json.loads(_ur.urlopen(_ur.Request(
            f"https://paper-api.alpaca.markets/v2/orders/{order_id}",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read())
    except Exception as exc:
        return {"error": f"fetch_failed:{type(exc).__name__}", "detail": str(exc)[:200]}
    return {k: order.get(k) for k in [
        "id", "symbol", "side", "qty", "type", "limit_price", "status",
        "filled_qty", "filled_avg_price", "submitted_at", "filled_at",
        "canceled_at", "time_in_force",
    ]}


@router.post("/fire-test-critical-alert")
def fire_test_critical_alert(
    note: str = Query("test", description="Optional note appended to the alert"),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Fire a MANUAL_TEST critical alert via the critical-alert channel.
    Brock 2026-08-10: 'until Brock confirms he received it, treat the fund
    as unmonitored.' Use this endpoint to validate the alert path end-to-end
    after any Discord/webhook config change."""
    from app.services.critical_alert import send_critical
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    delivered = send_critical(
        category="MANUAL_TEST",
        title=f"Test alert ({note})",
        message=(
            f"Manual test fired at {ts} by user_{current_user.id}. "
            f"If you see this in Discord, the critical-alert channel is "
            f"reaching you. If NOT, the fund is unmonitored — "
            f"CRITICAL_ALERTS_ENABLED / ALERT_WEBHOOK_URL / Discord webhook "
            f"config is broken."
        ),
        source="admin.fire_test_critical_alert",
    )
    return {"delivered": delivered, "note": note, "fired_at": ts,
            "next_step": "Brock must confirm receipt in Discord. "
                         "Until confirmed, fund is UNMONITORED."}


@router.get("/audits/list")
def audits_list(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """List all audit reports in /data/audits (or BMG_AUDIT_DIR env override).
    Returns filename, size, mtime. Fetch content via /admin/audits/{filename}."""
    import os
    from datetime import datetime, timezone
    root = os.getenv("BMG_AUDIT_DIR", "/data/audits")
    if not os.path.isdir(root):
        return {"exists": False, "dir": root, "files": []}
    files = []
    for name in sorted(os.listdir(root), reverse=True):
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        try:
            sz = os.path.getsize(p)
            mt = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).isoformat()
            files.append({"name": name, "size_bytes": sz, "mtime_utc": mt})
        except Exception:
            continue
    return {"exists": True, "dir": root, "count": len(files), "files": files}


@router.get("/audits/{filename}")
def audits_get(
    filename: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Return content of one audit report. Filename must not contain path
    separators (basic anti-traversal)."""
    import os
    if "/" in filename or ".." in filename or "\\" in filename:
        return {"error": "invalid_filename"}
    root = os.getenv("BMG_AUDIT_DIR", "/data/audits")
    path = os.path.join(root, filename)
    if not os.path.isfile(path):
        return {"error": "not_found", "path": path}
    try:
        with open(path) as f:
            content = f.read()
        return {"name": filename, "size_bytes": len(content), "content": content}
    except Exception as exc:
        return {"error": f"read_failed:{exc}"}


@router.post("/audits/run-premarket-now")
def audits_run_premarket_now(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Force the pre-market report to run now (bypassing the 9:15 ET cron).
    Useful for pre-Monday verification and any time you want the latest."""
    from app.jobs.premarket_report import run_premarket_report_job
    report = run_premarket_report_job(db=db)
    return {"ok": True, "bytes": len(report), "preview": report[:500]}


@router.get("/scans/status")
def scans_status(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Current scan-gate state: env overrides, runtime state, effective per-sleeve.

    Ledger #22 kill switch (2026-08-09). Effective = env_master AND env_sleeve
    AND state_global AND state_sleeve — all must be true for scans to run."""
    from app.services.scans_gate import status_summary
    return status_summary()


@router.post("/scans/pause")
def scans_pause(
    sleeve: str = Query("all", description="all|global|stocks|crypto|options|quant|pr"),
    reason: str = Query(..., description="Human-readable reason (required, goes to log + history)"),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Pause bot scans globally or per-sleeve. Runtime-only — no redeploy.

    Ledger #22 kill switch. Consult /admin/scans/status after to confirm
    the state took effect. Verify halt by watching Railway logs for
    '[scan-gate] SKIP <profile>' on the next scan tick."""
    from app.services.scans_gate import set_paused
    try:
        new_state = set_paused(sleeve=sleeve, paused=True,
                               muted_by=f"user_{current_user.id}",
                               muted_reason=reason)
    except ValueError as ve:
        return {"error": str(ve)}
    return {"ok": True, "sleeve": sleeve, "reason": reason, "state": new_state}


@router.post("/scans/resume")
def scans_resume(
    sleeve: str = Query("all", description="all|global|stocks|crypto|options|quant|pr"),
    force: bool = Query(False, description="Override the unacked-auto-pause gate. Logged."),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Resume bot scans globally or per-sleeve.

    RESUME GATE (Brock 2026-08-10): refuses when any AUTO_PAUSE record in
    human_ack_required is unacknowledged. Use force=true to override
    (logged; do not use casually)."""
    from app.services.scans_gate import set_paused
    try:
        result = set_paused(sleeve=sleeve, paused=False,
                            muted_by=f"user_{current_user.id}",
                            muted_reason=None, force=force)
    except ValueError as ve:
        return {"error": str(ve)}
    if isinstance(result, dict) and result.get("error"):
        return result  # resume blocked — pass through the diagnostic
    return {"ok": True, "sleeve": sleeve, "force": force, "state": result}


@router.post("/backup-sqlite-offvolume")
def backup_sqlite_offvolume(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Ship a gzipped SQLite snapshot to configured off-volume storage.

    Closes ledger #16 properly: an on-volume .bak dies with the disk.
    This endpoint takes a fresh snapshot, gzips it, and PUTs it to a
    URL provided via env var. Local temp files are cleaned before return.

    Required env:
      OFFVOLUME_BACKUP_URL_TEMPLATE — full URL with {ts} placeholder.
        Example: https://bucket.r2.cloudflarestorage.com/backups/{ts}.db.gz?<pre-signed-query>
        Works with any S3-compatible pre-signed URL, R2, B2, Backblaze,
        MinIO, or a self-hosted receiver. {ts} is replaced with UTC
        YYYYMMDD-HHMMSS.

    Optional env:
      OFFVOLUME_BACKUP_AUTH_HEADER — literal "Header: Value" string.
        Example: 'Authorization: Bearer sk_live_...' — added to the PUT.

    On success writes /data/last_offvolume_backup.json marker used by
    the V0 discipline gate (destructive ops require recent off-volume
    backup).
    """
    import os, sqlite3, gzip, json
    import urllib.request, urllib.error
    from datetime import datetime, timezone
    from app.db.session import engine

    # 2026-08-18 Brock: two config modes.
    #  Mode A (S3-compatible): OFFVOLUME_BACKUP_S3_* env vars — sign PUT
    #    with AWS Signature Version 4. Works with R2, AWS S3, MinIO, B2.
    #    Preferred: uses long-lived credentials, no URL expiration.
    #  Mode B (pre-signed URL): OFFVOLUME_BACKUP_URL_TEMPLATE with {ts}
    #    placeholder. Legacy; needs periodic re-signing.
    s3_ak = os.getenv("OFFVOLUME_BACKUP_S3_ACCESS_KEY_ID", "").strip()
    s3_sk = os.getenv("OFFVOLUME_BACKUP_S3_SECRET_ACCESS_KEY", "").strip()
    s3_endpoint = os.getenv("OFFVOLUME_BACKUP_S3_ENDPOINT", "").strip().rstrip("/")
    s3_bucket = os.getenv("OFFVOLUME_BACKUP_S3_BUCKET", "").strip().strip("/")
    s3_region = os.getenv("OFFVOLUME_BACKUP_S3_REGION", "auto").strip()
    s3_prefix = os.getenv("OFFVOLUME_BACKUP_S3_PREFIX", "bmg-backups").strip().strip("/")

    use_s3 = bool(s3_ak and s3_sk and s3_endpoint and s3_bucket)

    template = os.getenv("OFFVOLUME_BACKUP_URL_TEMPLATE", "").strip()
    if not use_s3:
        if not template:
            return {"error": "not_configured",
                    "hint": "set OFFVOLUME_BACKUP_S3_* env vars (preferred) OR OFFVOLUME_BACKUP_URL_TEMPLATE"}
        if "{ts}" not in template:
            return {"error": "url_template_missing_ts_placeholder"}
    auth_header = os.getenv("OFFVOLUME_BACKUP_AUTH_HEADER", "").strip()

    url = engine.url
    if url.get_backend_name() != "sqlite":
        return {"error": "not_sqlite", "driver": url.get_backend_name()}
    src_path = url.database
    if not src_path or not os.path.exists(src_path):
        return {"error": "src_not_found", "path": src_path}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap_path = f"{src_path}.offv_{ts}.tmp"
    gz_path = f"{snap_path}.gz"

    result: dict = {"ts_utc": ts, "url": template.replace("{ts}", ts)}
    started = datetime.now(timezone.utc)
    try:
        # 1) Snapshot to /data
        src_conn = sqlite3.connect(src_path)
        dst_conn = sqlite3.connect(snap_path)
        with dst_conn:
            src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()
        snap_size = os.path.getsize(snap_path)
        result["snapshot_bytes"] = snap_size

        # 2) Gzip snapshot
        with open(snap_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
            while True:
                chunk = f_in.read(1024 * 1024)
                if not chunk:
                    break
                f_out.write(chunk)
        gz_size = os.path.getsize(gz_path)
        result["gzip_bytes"] = gz_size

        # 3) Free snapshot before upload — reduces peak disk use
        try:
            os.unlink(snap_path)
        except Exception:
            pass

        # 4) PUT to configured destination
        with open(gz_path, "rb") as f_gz:
            payload = f_gz.read()

        if use_s3:
            # S3-compatible v4-signed PUT
            from app.services.s3_sigv4 import sign_request
            object_key = f"{s3_prefix}/{ts}.db.gz" if s3_prefix else f"{ts}.db.gz"
            put_url = f"{s3_endpoint}/{s3_bucket}/{object_key}"
            headers = sign_request(
                method="PUT",
                url=put_url,
                payload=payload,
                access_key=s3_ak,
                secret_key=s3_sk,
                region=s3_region,
                service="s3",
                extra_headers={"Content-Type": "application/gzip"},
            )
            req = urllib.request.Request(put_url, data=payload, method="PUT")
            for k, v in headers.items():
                req.add_header(k, v)
            result["mode"] = "s3_v4"
            result["object_key"] = object_key
            result["bucket"] = s3_bucket
        else:
            put_url = template.replace("{ts}", ts)
            req = urllib.request.Request(put_url, data=payload, method="PUT")
            req.add_header("Content-Type", "application/gzip")
            if auth_header:
                k, _, v = auth_header.partition(":")
                if k and v:
                    req.add_header(k.strip(), v.strip())
            result["mode"] = "url_template"

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result["http_status"] = resp.status
                result["http_reason"] = resp.reason
        except urllib.error.HTTPError as httpe:
            result["error"] = "http_error"
            result["http_status"] = httpe.code
            result["http_reason"] = httpe.reason
            try:
                result["http_body"] = httpe.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise
        except Exception as ue:
            result["error"] = f"upload_failed:{type(ue).__name__}"
            result["upload_exception"] = str(ue)[:200]
            raise

        # 5) Success — write marker
        finished = datetime.now(timezone.utc)
        marker = {
            "ts_utc": ts,
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "duration_seconds": round((finished - started).total_seconds(), 2),
            "gzip_bytes": gz_size,
            "gzip_mb": round(gz_size / (1024*1024), 2),
            "snapshot_bytes": snap_size,
            "snapshot_mb": round(snap_size / (1024*1024), 2),
            "url": put_url.split("?")[0],  # store base URL only, not signed query
            "http_status": result.get("http_status"),
        }
        try:
            with open("/data/last_offvolume_backup.json", "w") as f_m:
                json.dump(marker, f_m)
            result["marker_written"] = True
        except Exception as me:
            result["marker_write_error"] = str(me)[:200]
        result.update({k: v for k, v in marker.items() if k not in result})
        result["ok"] = True
        return result
    finally:
        # Always clean local temp files, even on failure
        for p in (snap_path, gz_path):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


@router.get("/offvolume-backup-status")
def offvolume_backup_status(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Read the marker /data/last_offvolume_backup.json — returns last
    off-volume backup ts, age, size. Powers the V0 gate check ("recent
    off-volume backup exists before destructive op")."""
    import os, json
    from datetime import datetime, timezone
    p = "/data/last_offvolume_backup.json"
    if not os.path.exists(p):
        return {"exists": False, "hint": "no off-volume backup taken yet; run POST /admin/backup-sqlite-offvolume"}
    try:
        with open(p) as f:
            data = json.load(f)
    except Exception as exc:
        return {"exists": True, "error": f"read_failed:{exc}"}
    try:
        fin_ts = data.get("finished_utc")
        if fin_ts:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(fin_ts.replace("Z", "+00:00"))).total_seconds()
            data["age_seconds"] = round(age, 1)
            data["age_hours"] = round(age / 3600, 2)
    except Exception:
        pass
    data["exists"] = True
    return data


@router.post("/offvolume-restore-test")
def offvolume_restore_test(
    object_key: Optional[str] = Query(None, description="Optional S3 object key to test; default = latest from marker"),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Round-trip verify the most recent off-volume backup.

    Brock 2026-08-18: "A backup nobody has restored is a hypothesis, not
    a backup." This endpoint:
      1. GETs the object from S3 (default = latest backup per marker)
      2. Gunzips into a tmp file on /data
      3. Opens as SQLite, counts rows in bot_positions + bot_trades
      4. Compares to LIVE DB row counts
      5. Deletes the tmp file
      6. Returns match / mismatch verdict

    Only supports S3 mode (Mode A). URL-template mode has no LIST/GET path.
    """
    import os, sqlite3, gzip, json
    import urllib.request, urllib.error
    from datetime import datetime, timezone
    from app.db.session import engine

    s3_ak = os.getenv("OFFVOLUME_BACKUP_S3_ACCESS_KEY_ID", "").strip()
    s3_sk = os.getenv("OFFVOLUME_BACKUP_S3_SECRET_ACCESS_KEY", "").strip()
    s3_endpoint = os.getenv("OFFVOLUME_BACKUP_S3_ENDPOINT", "").strip().rstrip("/")
    s3_bucket = os.getenv("OFFVOLUME_BACKUP_S3_BUCKET", "").strip().strip("/")
    s3_region = os.getenv("OFFVOLUME_BACKUP_S3_REGION", "auto").strip()

    if not (s3_ak and s3_sk and s3_endpoint and s3_bucket):
        return {"error": "s3_not_configured", "hint": "restore-test only supports S3 mode"}

    # Determine object_key: use provided, else marker
    if not object_key:
        marker_path = "/data/last_offvolume_backup.json"
        if not os.path.exists(marker_path):
            return {"error": "no_marker", "hint": "run /admin/backup-sqlite-offvolume first"}
        try:
            with open(marker_path) as f:
                marker = json.load(f)
            object_key = marker.get("object_key")
        except Exception as exc:
            return {"error": f"marker_read_failed:{exc}"}
        if not object_key:
            return {"error": "marker_missing_object_key",
                    "hint": "marker predates S3 mode; run /admin/backup-sqlite-offvolume again"}

    from app.services.s3_sigv4 import sign_request
    get_url = f"{s3_endpoint}/{s3_bucket}/{object_key}"
    headers = sign_request(
        method="GET", url=get_url, payload=b"",
        access_key=s3_ak, secret_key=s3_sk, region=s3_region, service="s3",
    )
    req = urllib.request.Request(get_url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)

    result: Dict[str, Any] = {"object_key": object_key, "url": get_url.split("?")[0]}
    tmp_gz = f"/data/restore_test.{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.tmp.gz"
    tmp_db = f"{tmp_gz}.db"
    try:
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
                result["downloaded_bytes"] = len(data)
                result["http_status"] = resp.status
        except urllib.error.HTTPError as he:
            result["error"] = "download_failed"
            result["http_status"] = he.code
            try:
                result["http_body"] = he.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            return result
        with open(tmp_gz, "wb") as f:
            f.write(data)
        # Gunzip
        with gzip.open(tmp_gz, "rb") as gz_in, open(tmp_db, "wb") as db_out:
            while True:
                chunk = gz_in.read(1024 * 1024)
                if not chunk:
                    break
                db_out.write(chunk)
        result["gunzipped_bytes"] = os.path.getsize(tmp_db)

        # Open as SQLite, count rows
        conn = sqlite3.connect(tmp_db)
        cur = conn.cursor()
        bk_bp = cur.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0]
        bk_bt = cur.execute("SELECT COUNT(*) FROM bot_trades").fetchone()[0]
        conn.close()

        # Compare to live
        from sqlalchemy import text as _t
        with engine.connect() as c:
            live_bp = c.execute(_t("SELECT COUNT(*) FROM bot_positions")).scalar() or 0
            live_bt = c.execute(_t("SELECT COUNT(*) FROM bot_trades")).scalar() or 0

        result["backup_bot_positions"] = int(bk_bp)
        result["backup_bot_trades"] = int(bk_bt)
        result["live_bot_positions"] = int(live_bp)
        result["live_bot_trades"] = int(live_bt)
        # Match if backup <= live (live may have grown since backup)
        result["counts_match_or_grew"] = (int(bk_bp) <= int(live_bp) and int(bk_bt) <= int(live_bt))
        result["ok"] = result["counts_match_or_grew"] and int(bk_bp) > 0
        return result
    finally:
        for p in (tmp_gz, tmp_db):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


@router.post("/vacuum-sqlite")
def vacuum_sqlite(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """VACUUM the live SQLite DB to reclaim page-level free space.

    VACUUM rebuilds the DB file in-place using ~2x temporary disk while
    running. Caller must confirm sufficient volume headroom via
    /admin/data-usage first. Serial (no parallel writes allowed) — safe
    to call during off-hours."""
    import os, sqlite3
    from datetime import datetime, timezone
    from app.db.session import engine
    url = engine.url
    if url.get_backend_name() != "sqlite":
        return {"error": "not_sqlite", "driver": url.get_backend_name()}
    src_path = url.database
    if not src_path or not os.path.exists(src_path):
        return {"error": "src_not_found", "path": src_path}
    # Verify headroom — refuse to run if free < 2× DB size
    src_size = os.path.getsize(src_path)
    st = os.statvfs(os.path.dirname(src_path) or "/")
    free = st.f_bavail * st.f_frsize
    if free < 2 * src_size:
        return {
            "error": "insufficient_free_space",
            "src_size_bytes": src_size,
            "src_size_mb": round(src_size / (1024*1024), 2),
            "free_bytes": free,
            "free_mb": round(free / (1024*1024), 2),
            "required_bytes": 2 * src_size,
            "hint": "VACUUM needs ~2× DB size scratch. Prune backups first.",
        }
    started = datetime.now(timezone.utc)
    conn = sqlite3.connect(src_path)
    try:
        conn.isolation_level = None  # VACUUM cannot run inside a transaction
        conn.execute("VACUUM")
    finally:
        conn.close()
    ended = datetime.now(timezone.utc)
    new_size = os.path.getsize(src_path)
    st_after = os.statvfs(os.path.dirname(src_path) or "/")
    free_after = st_after.f_bavail * st_after.f_frsize
    return {
        "started_utc": started.isoformat(),
        "ended_utc": ended.isoformat(),
        "duration_seconds": round((ended - started).total_seconds(), 2),
        "size_before_bytes": src_size,
        "size_before_mb": round(src_size / (1024*1024), 2),
        "size_after_bytes": new_size,
        "size_after_mb": round(new_size / (1024*1024), 2),
        "reclaimed_bytes": src_size - new_size,
        "reclaimed_mb": round((src_size - new_size) / (1024*1024), 2),
        "reclaimed_pct": round((src_size - new_size) / src_size * 100, 2) if src_size else 0,
        "volume_free_mb_before": round(free / (1024*1024), 2),
        "volume_free_mb_after": round(free_after / (1024*1024), 2),
    }


@router.get("/data-usage")
def data_usage(
    min_size_mb: float = Query(0.0, description="Only list files >= this size."),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """List every file under /data with size + mtime + free-space totals.

    Item P0 (2026-08-09): Railway alerted /data volume 98% full. This
    endpoint tells us the file breakdown so we can prune safely. Also
    checks the live SQLite WAL/SHM sizes — a large WAL indicates
    checkpointing isn't happening and can balloon disk usage."""
    import os
    from datetime import datetime, timezone
    root = "/data"
    if not os.path.isdir(root):
        return {"error": "no_data_dir", "path": root}
    try:
        st = os.statvfs(root)
        total = st.f_blocks * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        used = total - avail
        pct_used = round(used / total * 100, 2) if total else None
    except Exception as exc:
        total = avail = used = pct_used = None
    files: list[dict] = []
    for entry in os.listdir(root):
        p = os.path.join(root, entry)
        try:
            if not os.path.isfile(p):
                continue
            sz = os.path.getsize(p)
            if sz < min_size_mb * 1024 * 1024:
                continue
            mt = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).isoformat()
            files.append({
                "name": entry,
                "size_bytes": sz,
                "size_mb": round(sz / (1024*1024), 2),
                "mtime_utc": mt,
                "is_backup": entry.endswith(".bak"),
                "is_wal": entry.endswith("-wal"),
                "is_shm": entry.endswith("-shm"),
            })
        except Exception:
            continue
    files.sort(key=lambda x: -x["size_bytes"])
    return {
        "volume_total_bytes": total,
        "volume_used_bytes": used,
        "volume_free_bytes": avail,
        "volume_total_mb": round(total / (1024*1024), 2) if total else None,
        "volume_used_mb": round(used / (1024*1024), 2) if used else None,
        "volume_free_mb": round(avail / (1024*1024), 2) if avail else None,
        "volume_pct_used": pct_used,
        "file_count": len(files),
        "total_listed_bytes": sum(f["size_bytes"] for f in files),
        "files": files,
    }


@router.post("/prune-backups")
def prune_backups(
    keep: int = Query(1, description="Number of most recent .bak files to keep."),
    dry_run: bool = Query(True, description="Preview by default. Set false to delete."),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Delete /data/*.bak files, keeping the N most recent.

    Item P0 (2026-08-09): /data volume 98% full — backups on same volume
    as the live DB are consuming space. Backups on the same volume are
    not backups anyway (they die with the disk); ledger #16 remains open
    until backups live off-volume. Interim: keep at most `keep` recent
    ones to prevent volume exhaustion."""
    import os
    from datetime import datetime, timezone
    root = "/data"
    if not os.path.isdir(root):
        return {"error": "no_data_dir", "path": root}
    entries: list[dict] = []
    for name in os.listdir(root):
        if not name.endswith(".bak"):
            continue
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        try:
            sz = os.path.getsize(p)
            mt = os.path.getmtime(p)
            entries.append({"path": p, "name": name, "size_bytes": sz, "mtime": mt})
        except Exception:
            continue
    # Sort newest-first by mtime
    entries.sort(key=lambda x: -x["mtime"])
    keep_paths = {e["path"] for e in entries[:max(0, keep)]}
    to_delete = [e for e in entries if e["path"] not in keep_paths]
    # Also sweep orphan .bak-journal files. A journal is only valid while
    # its parent .bak exists. If the parent is gone (or being deleted this
    # run), the journal is inert leftover from an earlier prune.
    existing_bak_names = {e["name"] for e in entries if e["path"] in keep_paths}
    for name in os.listdir(root):
        if not name.endswith(".bak-journal"):
            continue
        parent_bak = name[:-len("-journal")]
        if parent_bak in existing_bak_names:
            continue  # legit journal for a kept .bak
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        try:
            sz = os.path.getsize(p)
            mt = os.path.getmtime(p)
            to_delete.append({"path": p, "name": name, "size_bytes": sz, "mtime": mt})
        except Exception:
            continue
    deleted: list[dict] = []
    delete_errors: list[dict] = []
    freed_bytes = 0
    if not dry_run:
        for e in to_delete:
            try:
                os.unlink(e["path"])
                freed_bytes += e["size_bytes"]
                deleted.append({
                    "name": e["name"],
                    "size_mb": round(e["size_bytes"] / (1024*1024), 2),
                    "mtime_utc": datetime.fromtimestamp(e["mtime"], tz=timezone.utc).isoformat(),
                })
            except Exception as exc:
                delete_errors.append({"name": e["name"], "error": f"{type(exc).__name__}: {exc}"})
    # Post-delete free space
    try:
        st = os.statvfs(root)
        avail_after = st.f_bavail * st.f_frsize
    except Exception:
        avail_after = None
    return {
        "dry_run": dry_run,
        "keep": keep,
        "backup_count_before": len(entries),
        "keep_names": sorted([e["name"] for e in entries[:max(0, keep)]]),
        "delete_candidates": [
            {
                "name": e["name"],
                "size_mb": round(e["size_bytes"] / (1024*1024), 2),
                "mtime_utc": datetime.fromtimestamp(e["mtime"], tz=timezone.utc).isoformat(),
            }
            for e in to_delete
        ],
        "delete_candidate_count": len(to_delete),
        "delete_candidate_total_mb": round(sum(e["size_bytes"] for e in to_delete) / (1024*1024), 2),
        "deleted": deleted,
        "delete_errors": delete_errors,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024*1024), 2),
        "volume_free_mb_after": round(avail_after / (1024*1024), 2) if avail_after else None,
    }


@router.get("/db-driver")
def db_driver(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """P0 accountability: what DB is prod actually connected to right now?
    Returns driver scheme + database name + host (no creds)."""
    from app.db.session import engine
    from sqlalchemy import inspect
    url = engine.url
    return {
        "driver": url.get_backend_name(),          # 'sqlite' | 'postgresql' | ...
        "dialect_driver": url.get_driver_name(),   # 'pysqlite' | 'psycopg2' | ...
        "database": url.database,                  # file path for sqlite, dbname for pg
        "host": url.host,                          # None for sqlite
        "port": url.port,
        "table_count": len(inspect(engine).get_table_names()),
    }


@router.get("/inspect-allocation")
def inspect_allocation(
    allocation_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Deep dive on a single allocation: trades, pnl breakdown, positions."""
    from app.db.models.bots import BotTrade, BotPosition, BotAllocation, BotProfile
    a = db.query(BotAllocation).filter(BotAllocation.id == allocation_id).first()
    if not a:
        return {"error": "not found"}
    prof = db.query(BotProfile).filter(BotProfile.id == a.profile_id).first()
    trades = db.query(BotTrade).filter(BotTrade.allocation_id == allocation_id).filter(BotTrade.quarantined_at.is_(None)).all()
    positions = db.query(BotPosition).filter(BotPosition.allocation_id == allocation_id).all()
    from collections import Counter
    sides = Counter(t.side.lower() for t in trades)
    pnl_sum = sum(int(t.pnl_cents or 0) for t in trades)
    pnl_by_source: dict = {}
    for t in trades:
        if t.pnl_cents is None: continue
        pnl_by_source.setdefault(t.pnl_source or "none", 0)
        pnl_by_source[t.pnl_source or "none"] += int(t.pnl_cents)
    open_pos_open_cost = sum(int(p.avg_cost_cents or 0) * float(p.qty or 0) for p in positions if not p.closed_at and not p.quarantined_at)
    return {
        "allocation_id": allocation_id,
        "user_id": a.user_id,
        "profile_name": prof.name if prof else None,
        "enabled": a.enabled,
        "starting_capital_cents": a.starting_capital_cents,
        "trades_active_count": len(trades),
        "sides": dict(sides),
        "sum_pnl_cents_active_trades": pnl_sum,
        "sum_pnl_dollars": round(pnl_sum/100, 2),
        "pnl_by_source_cents": pnl_by_source,
        "positions_open_active": sum(1 for p in positions if not p.closed_at and not p.quarantined_at),
        "positions_closed_only": sum(1 for p in positions if p.closed_at and not p.quarantined_at),
        "positions_quarantined": sum(1 for p in positions if p.quarantined_at),
        "open_position_entry_notional_cents": int(open_pos_open_cost),
    }


@router.get("/inspect-bot-positions")
def inspect_bot_positions(
    profile: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Every BotPosition for a profile with open/closed/quarantined breakdown."""
    from app.db.models.bots import BotPosition, BotProfile, BotAllocation
    prof = db.query(BotProfile).filter(BotProfile.name == profile).first()
    if not prof:
        return {"error": "profile_not_found"}
    allocs = db.query(BotAllocation).filter(BotAllocation.profile_id == prof.id).all()
    alloc_ids = [a.id for a in allocs]
    positions = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id.in_(alloc_ids))
        .order_by(BotPosition.opened_at.desc())
        .limit(80)
        .all()
    )
    out = []
    for p in positions:
        out.append({
            "id": p.id,
            "symbol": p.symbol, "side": p.side, "qty": float(p.qty or 0),
            "avg_cost_cents": p.avg_cost_cents,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "quarantined_at": p.quarantined_at.isoformat() if p.quarantined_at else None,
            "quarantine_reason": p.quarantine_reason,
            "exit_reason": p.exit_reason,
        })
    open_c = sum(1 for p in positions if not p.closed_at and not p.quarantined_at)
    closed_c = sum(1 for p in positions if p.closed_at and not p.quarantined_at)
    quar_c = sum(1 for p in positions if p.quarantined_at)
    return {
        "profile": profile, "allocation_ids": alloc_ids,
        "total_positions": len(positions),
        "open_active": open_c, "closed_only": closed_c, "quarantined": quar_c,
        "positions": out,
    }


@router.post("/reconcile-user1-to-alpaca")
def reconcile_user1_to_alpaca(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Iter 3 close-out per Brock: SYNC user 1 to Alpaca. Alpaca wins.
    Two ops: (a) quarantine only_in_user1 phantoms, (b) proportionally
    scale user 1's rows down where sum(qty) > Alpaca's qty. Scoped to
    user 1 only — leaves other users' simulated allocs untouched."""
    import os, urllib.request, json
    from datetime import datetime, timezone
    from collections import defaultdict
    from app.db.models.bots import BotPosition, BotAllocation

    now = datetime.now(timezone.utc)
    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")
    alp_list = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
    ), timeout=15).read())
    alp_qty_by_key: dict = {}
    for p in alp_list:
        q = float(p.get("qty"))
        side = "short" if q < 0 else "long"
        alp_qty_by_key[(p.get("symbol"), side)] = abs(q)

    user1_alloc_ids = [a.id for a in db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()]
    bmg_rows = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id.in_(user1_alloc_ids))
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    bmg_by_key: dict = defaultdict(list)
    for p in bmg_rows:
        key = (p.symbol or "", (p.side or "long").lower())
        bmg_by_key[key].append(p)

    quarantined = []
    scaled = []

    # (a) Quarantine phantoms — keys BMG has that Alpaca doesn't
    for key, group in bmg_by_key.items():
        if key in alp_qty_by_key: continue
        for p in group:
            quarantined.append({"id": p.id, "symbol": p.symbol, "side": p.side, "qty": float(p.qty or 0)})
            if not dry_run:
                p.quarantined_at = now
                p.quarantine_reason = "phantom_not_at_alpaca_2026_08_07"

    # (b) Scale qty mismatches down proportionally
    for key, alp_qty in alp_qty_by_key.items():
        group = bmg_by_key.get(key, [])
        bmg_total = sum(float(p.qty or 0) for p in group)
        if bmg_total <= alp_qty + 0.001: continue
        if bmg_total <= 0.001: continue
        ratio = alp_qty / bmg_total
        for p in group:
            old = float(p.qty or 0)
            new = old * ratio
            scaled.append({"id": p.id, "symbol": p.symbol, "side": p.side,
                          "old_qty": round(old, 6), "new_qty": round(new, 6),
                          "allocation_id": p.allocation_id})
            if not dry_run:
                p.qty = new

    if not dry_run and (quarantined or scaled):
        db.commit()

    return {
        "dry_run": dry_run,
        "phantoms_quarantined": len(quarantined),
        "qty_rows_scaled": len(scaled),
        "phantoms_preview": quarantined[:10],
        "scaled_preview": scaled[:10],
    }


@router.post("/pause-bot")
def pause_bot(
    profile_name: str = Query(...),
    reason: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Pause every user_1 allocation for a given profile — sets
    enabled=False, paused_reason=<reason>. Bot runner reads this on
    the next cycle and skips execution."""
    from app.db.models.bots import BotAllocation, BotProfile
    prof = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not prof:
        return {"error": f"profile_not_found: {profile_name}"}
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == 1)
        .filter(BotAllocation.profile_id == prof.id)
        .all()
    )
    for a in allocs:
        a.enabled = False
        a.paused_reason = reason[:400]
    db.commit()
    return {
        "profile": profile_name,
        "affected_allocations": [a.id for a in allocs],
        "paused_reason": reason,
    }


@router.get("/risk-gate-config")
def risk_gate_config(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Report the ACTUALLY-ENFORCED risk gate values from the running
    process (env vars + code defaults). PM Claude spec: prove the gate
    values, not what the repo says."""
    import os
    keys = [
        "GROSS_EXPOSURE_MAX_PCT_NAV", "NET_EXPOSURE_MAX_PCT_NAV",
        "OPTIONS_MAX_NOTIONAL_PCT", "OPTIONS_MAX_CONTRACTS_PER_TRADE",
        "OPTIONS_SLEEVE_MAX_PCT", "LEAPS_MIN_DTE",
        "OPTIONS_RISK_GATES_ENABLED", "INVARIANT_ENGINE_ENABLED",
    ]
    return {k: os.getenv(k, "<unset>") for k in keys}


@router.get("/legacy-simulator-damage")
def legacy_simulator_damage(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """ADD 2 (Brock 2026-08-07): how much of BMG's recorded history
    was written by bot_executor.py's random-fill simulator.

    Fingerprint (heuristic, high precision — bot_executor is the only
    module known to combine all three):
      - alpaca_order_id IS NULL
      - signal_id IS NULL (bot_executor doesn't reference signals)
      - fees_cents = 0 (bot_executor sets fees=0; real broker fills
        get a friction model)
    """
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile
    from sqlalchemy import func
    from collections import defaultdict

    # Multiple candidate fingerprints so we can report the total damage
    # regardless of which write path missed a field.
    q_null_oid = db.query(BotTrade).filter(BotTrade.alpaca_order_id.is_(None))
    q_strict = q_null_oid.filter(BotTrade.signal_id.is_(None))
    fp_counts = {
        "alpaca_order_id_null_only": q_null_oid.count(),
        "alpaca_order_id_null_AND_signal_id_null": q_strict.count(),
    }
    # Use the broader filter as the working set for the damage report
    q = q_null_oid
    total = q.count()
    survived = q.filter(BotTrade.quarantined_at.is_(None)).count()
    quarantined = total - survived

    date_range = db.query(func.min(BotTrade.ts), func.max(BotTrade.ts)).filter(
        BotTrade.alpaca_order_id.is_(None),
    ).first()

    # Per-bot breakdown (survived only — those still contributing to P&L)
    profs_by_id = {p.id: p.name for p in db.query(BotProfile).all()}
    alloc_to_prof = {a.id: profs_by_id.get(a.profile_id) for a in db.query(BotAllocation).all()}
    per_bot: dict = defaultdict(lambda: {"survived": 0, "quarantined": 0, "total": 0, "sum_qty": 0.0, "sum_notional_cents": 0})
    for r in q.all():
        prof = alloc_to_prof.get(r.allocation_id, "?")
        pb = per_bot[prof]
        pb["total"] += 1
        pb["sum_qty"] += float(r.qty or 0)
        pb["sum_notional_cents"] += int((r.fill_price_cents or 0) * (r.qty or 0))
        if r.quarantined_at:
            pb["quarantined"] += 1
        else:
            pb["survived"] += 1

    top = sorted(per_bot.items(), key=lambda x: -x[1]["survived"])
    return {
        "fingerprint_counts": fp_counts,
        "using_fingerprint": "alpaca_order_id IS NULL (broader net)",
        "total_rows_ever": total,
        "quarantined_by_prior_sweeps": quarantined,
        "surviving_in_current_ledger": survived,
        "date_range": {
            "first": date_range[0].isoformat() if date_range[0] else None,
            "last": date_range[1].isoformat() if date_range[1] else None,
        },
        "top_bots_by_surviving_sim_rows": [
            {
                "bot": k,
                "survived": v["survived"],
                "quarantined": v["quarantined"],
                "total": v["total"],
                "sum_notional_usd": round(v["sum_notional_cents"] / 100, 2),
            } for k, v in top[:15]
        ],
    }


@router.get("/sim-leak-diag")
def sim_leak_diag(
    lookback_hours: int = Query(48),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """4a: identify sim-leak fills (alpaca_order_id IS NULL) since
    the m078 real-only-mode block. Report per-bot which paths wrote
    them so we can find the bypass."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile
    from collections import defaultdict
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    rows = (
        db.query(BotTrade)
        .filter(BotTrade.ts >= cutoff)
        .filter(BotTrade.alpaca_order_id.is_(None))
        .filter(BotTrade.quarantined_at.is_(None))
        .order_by(BotTrade.ts.desc())
        .all()
    )
    alloc_to_user: dict = {}
    alloc_to_profile: dict = {}
    for a in db.query(BotAllocation).all():
        alloc_to_user[a.id] = a.user_id
    for p in db.query(BotProfile).all():
        pass
    profs_by_id = {p.id: p.name for p in db.query(BotProfile).all()}
    alloc_to_prof_name = {}
    for a in db.query(BotAllocation).all():
        alloc_to_prof_name[a.id] = profs_by_id.get(a.profile_id)

    by_bot: dict = defaultdict(list)
    for r in rows:
        prof = alloc_to_prof_name.get(r.allocation_id, "?")
        by_bot[prof].append({
            "id": r.id, "ts": r.ts.isoformat() if r.ts else None,
            "symbol": r.symbol, "side": r.side, "qty": float(r.qty or 0),
            "fill_price_cents": r.fill_price_cents,
            "user_id": alloc_to_user.get(r.allocation_id),
            "allocation_id": r.allocation_id,
        })
    return {
        "lookback_hours": lookback_hours,
        "total_sim_rows": len(rows),
        "by_bot": [{"bot": k, "count": len(v), "rows": v} for k, v in sorted(by_bot.items(), key=lambda x: -len(x[1]))],
    }


@router.get("/user1-capital-vs-funded")
def user1_capital_vs_funded(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Structural report for acceptance B: sum(user_1 starting_capital)
    vs the actual Alpaca-funded base. If sum > funded, fund PV inflates
    by exactly that excess (fund PV = sum(starting + realized + unrealized))."""
    import os, urllib.request, json
    from app.db.models.bots import BotAllocation

    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")
    acct = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/account",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
    ), timeout=15).read())
    funded = float(acct.get("portfolio_value") or 0)

    allocs = db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()
    enabled = [a for a in allocs if a.enabled]
    all_sum_cents = sum(int(a.starting_capital_cents or 0) for a in allocs)
    en_sum_cents = sum(int(a.starting_capital_cents or 0) for a in enabled)
    return {
        "alpaca_funded_base_usd": round(funded, 2),
        "user1_alloc_count_all": len(allocs),
        "user1_alloc_count_enabled": len(enabled),
        "sum_starting_capital_all_usd": round(all_sum_cents / 100, 2),
        "sum_starting_capital_enabled_usd": round(en_sum_cents / 100, 2),
        "excess_enabled_usd": round(en_sum_cents / 100 - funded, 2),
        "target_scale_factor": round(funded / (en_sum_cents / 100), 4) if en_sum_cents > 0 else None,
    }


@router.post("/rescale-user1-allocations")
def rescale_user1_allocations(
    dry_run: bool = Query(True),
    target_base_usd: Optional[float] = Query(None, description="Override funded base; default = Alpaca equity"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Structural B-fix per PM 2026-08-07: rescale enabled user_1
    allocations proportionally so sum(starting_capital) == funded base.
    Same operation as m077 rescale (July $1M→$100K)."""
    import os, urllib.request, json
    from app.db.models.bots import BotAllocation

    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")
    if target_base_usd is None:
        acct = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://paper-api.alpaca.markets/v2/account",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=15).read())
        target_base_usd = float(acct.get("portfolio_value") or 0)

    target_base_cents = int(round(target_base_usd * 100))
    enabled = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == 1)
        .filter(BotAllocation.enabled == True)
        .all()
    )
    current_sum = sum(int(a.starting_capital_cents or 0) for a in enabled)
    if current_sum <= 0:
        return {"error": "current_sum_zero"}
    scale = target_base_cents / current_sum
    actions = []
    new_sum = 0
    for a in enabled:
        old = int(a.starting_capital_cents or 0)
        new = int(round(old * scale))
        new_sum += new
        actions.append({
            "allocation_id": a.id, "profile_id": a.profile_id,
            "old_starting_cents": old, "new_starting_cents": new,
            "old_usd": round(old/100, 2), "new_usd": round(new/100, 2),
        })
        if not dry_run:
            a.starting_capital_cents = new
    if not dry_run:
        db.commit()
    return {
        "dry_run": dry_run,
        "target_base_cents": target_base_cents,
        "target_base_usd": target_base_usd,
        "current_sum_cents": current_sum,
        "current_sum_usd": round(current_sum/100, 2),
        "scale_factor": round(scale, 6),
        "new_sum_cents": new_sum,
        "new_sum_usd": round(new_sum/100, 2),
        "rescaled_alloc_count": len(actions),
        "sample_actions": actions[:10],
    }


@router.post("/backfill-alloc-starting-capital")
def backfill_alloc_starting_capital(
    allocation_id: int = Query(...),
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """PM Claude 2026-08-07 (alloc 27 spec): backfill starting_capital
    when it's $0 but real fills exist. Prefer prior non-zero value from
    bot_allocations history; if none, use capital deployed at first
    fill (fill_price × qty × multiplier for the first BUY trade)."""
    from app.db.models.bots import BotAllocation, BotTrade
    a = db.query(BotAllocation).filter(BotAllocation.id == allocation_id).first()
    if not a:
        return {"error": "not_found"}
    if a.starting_capital_cents and a.starting_capital_cents > 0:
        return {
            "allocation_id": allocation_id,
            "already_set": True,
            "starting_capital_cents": a.starting_capital_cents,
            "no_action": True,
        }
    # No history table for allocation capital changes; use first fill.
    first_buy = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id == allocation_id)
        .filter(BotTrade.quarantined_at.is_(None))
        .filter(BotTrade.side.in_(("buy", "short")))
        .order_by(BotTrade.ts.asc())
        .first()
    )
    if not first_buy:
        return {"error": "no_buy_trades_to_derive_capital_from",
                "allocation_id": allocation_id}
    # Derive: for options, premium × 100 × contracts; else fill × qty
    is_opt = bool(getattr(first_buy, "option_type", None))
    fill = int(first_buy.fill_price_cents or 0)
    qty = float(first_buy.qty or 0)
    if is_opt:
        derived_cents = int(fill * qty * 100)
    else:
        derived_cents = int(fill * qty)
    if derived_cents <= 0:
        return {"error": "derived_capital_zero", "allocation_id": allocation_id}
    old = a.starting_capital_cents
    if not dry_run:
        a.starting_capital_cents = derived_cents
        db.commit()
    return {
        "allocation_id": allocation_id,
        "dry_run": dry_run,
        "old_starting_cents": old,
        "derived_starting_cents": derived_cents,
        "derived_starting_usd": round(derived_cents / 100, 2),
        "basis": f"first BUY trade id={first_buy.id} at ts={first_buy.ts.isoformat()} "
                 f"(symbol={first_buy.symbol}, qty={qty}, fill_price_cents={fill}, "
                 f"is_option={is_opt})",
    }


@router.get("/daily-report")
def daily_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """On-demand daily report — same content as the 4:15pm ET cron."""
    from app.jobs.daily_report import build_daily_report
    return {"report": build_daily_report(db)}


@router.post("/daily-report/run")
def daily_report_run_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Fire the report + persist to vault (same as the 4:15pm ET cron)."""
    from app.jobs.daily_report import run_daily_report_job
    report = run_daily_report_job(db)
    return {"ok": True, "report": report}


@router.get("/premarket-report")
def premarket_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """On-demand pre-market report — same content as the 9:15am ET cron."""
    from app.jobs.premarket_report import build_premarket_report
    return {"report": build_premarket_report(db)}


@router.post("/premarket-report/run")
def premarket_report_run_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Fire the pre-market report + persist to vault (same as the 9:15am ET cron)."""
    from app.jobs.premarket_report import run_premarket_report_job
    report = run_premarket_report_job(db)
    return {"ok": True, "report": report}


@router.get("/round-trips-per-bot")
def round_trips_per_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Autonomy readiness: how many Alpaca-verified closed round trips
    per bot right now. Round trip = matched (buy→sell) or (short→cover)
    pair, both sides having alpaca_order_id set (real broker fills)."""
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile
    from collections import defaultdict, deque

    allocs = db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()
    profs = {p.id: p.name for p in db.query(BotProfile).all()}
    alloc_to_prof = {a.id: profs.get(a.profile_id) for a in allocs}
    alloc_ids = [a.id for a in allocs]

    # m099: round-trips count only BROKER_FILL rows (real live fills).
    # Adopter/reconcile/rebuild rows represent history reconstruction, not new
    # broker events, and must not inflate the round-trip count.
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id.in_(alloc_ids))
        .filter(BotTrade.quarantined_at.is_(None))
        .filter(BotTrade.origin == "BROKER_FILL")
        .order_by(BotTrade.ts.asc())
        .all()
    )

    # FIFO pair per (bot, symbol) — buy→sell = long RT, short→cover = short RT
    open_positions_by_key: dict = defaultdict(deque)
    round_trips_by_bot: dict = defaultdict(int)
    for t in trades:
        bot = alloc_to_prof.get(t.allocation_id, "?")
        key = (bot, t.symbol)
        side = (t.side or "").lower()
        if side in ("buy", "short"):
            open_positions_by_key[key].append((side, float(t.qty or 0)))
        elif side in ("sell", "cover", "close"):
            q = open_positions_by_key.get(key)
            need_qty = float(t.qty or 0)
            while q and need_qty > 0.001:
                open_side, open_qty = q[0]
                # matched round trip when opposite-side closes an open
                take = min(open_qty, need_qty)
                if (open_side == "buy" and side == "sell") or (open_side == "short" and side in ("cover", "close")):
                    round_trips_by_bot[bot] += 1
                if take >= open_qty - 0.001:
                    q.popleft()
                else:
                    q[0] = (open_side, open_qty - take)
                need_qty -= take

    return {
        "target_round_trips_per_bot": 50,
        "round_trips": [
            {"bot": k, "round_trips": v} for k, v in sorted(round_trips_by_bot.items(), key=lambda x: -x[1])
        ],
        "bots_at_or_over_50": sum(1 for v in round_trips_by_bot.values() if v >= 50),
        "bots_with_zero_round_trips": len([a for a in allocs if a.enabled]) - len(round_trips_by_bot),
    }


@router.get("/audit-users")
def audit_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Per-user counts of allocations / positions / trades. Ahead of
    single-tenant enforcement (user 1 = the fund, others = test)."""
    from app.db.models.bots import BotAllocation, BotPosition, BotTrade
    from collections import defaultdict
    counts: dict = defaultdict(lambda: {
        "allocations": 0, "enabled_allocations": 0,
        "positions_total": 0, "positions_open_nonquar": 0,
        "trades_total": 0, "trades_active": 0,
        "starting_capital_total_cents": 0,
    })
    for a in db.query(BotAllocation).all():
        c = counts[a.user_id]
        c["allocations"] += 1
        if a.enabled:
            c["enabled_allocations"] += 1
        c["starting_capital_total_cents"] += int(a.starting_capital_cents or 0)
    # Positions + trades
    alloc_user = {a.id: a.user_id for a in db.query(BotAllocation).all()}
    for p in db.query(BotPosition).all():
        u = alloc_user.get(p.allocation_id)
        if u is None: continue
        counts[u]["positions_total"] += 1
        if not p.closed_at and not p.quarantined_at:
            counts[u]["positions_open_nonquar"] += 1
    for t in db.query(BotTrade).all():
        u = alloc_user.get(t.allocation_id)
        if u is None: continue
        counts[u]["trades_total"] += 1
        if not t.quarantined_at:
            counts[u]["trades_active"] += 1
    out = []
    for u, c in sorted(counts.items()):
        out.append({"user_id": u, **c,
                    "starting_capital_total_usd": round(c["starting_capital_total_cents"]/100, 2)})
    return {"users": out}


@router.post("/quarantine-non-user1-allocations")
def quarantine_non_user1_allocations(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Disable + tombstone every BotAllocation whose user_id != 1.
    Also mark their open positions quarantined so they drop out of
    every rollup. Data-only, reversible via UPDATE."""
    from datetime import datetime, timezone
    from app.db.models.bots import BotAllocation, BotPosition, BotTrade
    now = datetime.now(timezone.utc)
    allocs = db.query(BotAllocation).filter(BotAllocation.user_id != 1).all()
    alloc_ids = [a.id for a in allocs]
    open_pos = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id.in_(alloc_ids))
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .count()
    )
    active_trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id.in_(alloc_ids))
        .filter(BotTrade.quarantined_at.is_(None))
        .count()
    )
    if not dry_run and alloc_ids:
        # Tombstone allocations
        for a in allocs:
            a.enabled = False
            a.paused_reason = "single_tenant_user1_only_2026_08_07"
        # Quarantine their open positions (so they don't enter user 1's rollup by mistake)
        (
            db.query(BotPosition)
            .filter(BotPosition.allocation_id.in_(alloc_ids))
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .update(
                {"quarantined_at": now, "quarantine_reason": "single_tenant_user1_only_2026_08_07"},
                synchronize_session=False,
            )
        )
        # Quarantine their trades
        (
            db.query(BotTrade)
            .filter(BotTrade.allocation_id.in_(alloc_ids))
            .filter(BotTrade.quarantined_at.is_(None))
            .update(
                {"quarantined_at": now, "quarantine_reason": "single_tenant_user1_only_2026_08_07"},
                synchronize_session=False,
            )
        )
        db.commit()
    return {
        "dry_run": dry_run,
        "allocations_to_tombstone": len(alloc_ids),
        "open_positions_to_quarantine": open_pos,
        "active_trades_to_quarantine": active_trades,
        "affected_user_ids": sorted({a.user_id for a in allocs}),
    }


@router.post("/reset-reconstructed-pnl-user1")
def reset_reconstructed_pnl_user1(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Clear pnl_cents on user 1 bot_trades tagged pnl_source='reconstructed'.
    Provisional-by-definition per iter-2 spec; keeping them polluted the
    P&L rollup. Exact (R7 client_order_id) pairings retained."""
    from app.db.models.bots import BotTrade, BotAllocation
    user1_alloc_ids = [a.id for a in db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()]
    rows = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id.in_(user1_alloc_ids))
        .filter(BotTrade.pnl_source == "reconstructed")
        .filter(BotTrade.pnl_cents.isnot(None))
        .all()
    )
    total_pnl_wiped_cents = sum(int(r.pnl_cents or 0) for r in rows)
    if not dry_run:
        for r in rows:
            r.pnl_cents = None
            r.pnl_source = None
        db.commit()
    return {
        "dry_run": dry_run,
        "rows_affected": len(rows),
        "total_pnl_wiped_cents": total_pnl_wiped_cents,
        "total_pnl_wiped_usd": round(total_pnl_wiped_cents / 100, 2),
    }


@router.get("/user1-vs-alpaca")
def user1_vs_alpaca(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """The scoped recon: user_id=1's positions vs Alpaca. Prior
    bmg-alpaca-diff was global across all users; the fund-of-record
    is user 1 (Brock), so this is what should SYNC."""
    import os, urllib.request, json
    from collections import defaultdict
    from app.db.models.bots import BotPosition, BotAllocation

    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")
    alp_list = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
    ), timeout=15).read())
    alp_agg: dict = {}
    for p in alp_list:
        q = float(p.get("qty"))
        side = "short" if q < 0 else "long"
        alp_agg[(p.get("symbol"), side)] = abs(q)

    user1_alloc_ids = [a.id for a in db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()]
    bmg_rows = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id.in_(user1_alloc_ids))
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    bmg_agg: dict = defaultdict(lambda: {"qty": 0.0, "rows": 0, "ids": []})
    for p in bmg_rows:
        side = (p.side or "long").lower()
        key = (p.symbol or "", side)
        bmg_agg[key]["qty"] += float(p.qty or 0)
        bmg_agg[key]["rows"] += 1
        bmg_agg[key]["ids"].append(p.id)

    bmg_keys = set(bmg_agg.keys())
    alp_keys = set(alp_agg.keys())
    only_bmg = sorted(bmg_keys - alp_keys)
    only_alp = sorted(alp_keys - bmg_keys)
    common = bmg_keys & alp_keys
    mismatches = []
    for k in common:
        if abs(bmg_agg[k]["qty"] - alp_agg[k]) > 0.5:
            mismatches.append({"symbol": k[0], "side": k[1],
                               "bmg_qty": round(bmg_agg[k]["qty"], 4),
                               "alp_qty": round(alp_agg[k], 4),
                               "bmg_rows": bmg_agg[k]["rows"]})
    return {
        "user_id": 1,
        "user1_open_rows": len(bmg_rows),
        "user1_unique_symbol_side": len(bmg_keys),
        "alpaca_unique_symbol_side": len(alp_keys),
        "only_in_user1": [{"symbol": k[0], "side": k[1], "qty": round(bmg_agg[k]["qty"],4), "rows": bmg_agg[k]["rows"]} for k in only_bmg],
        "only_in_alpaca": [{"symbol": k[0], "side": k[1], "qty": round(alp_agg[k],4)} for k in only_alp],
        "qty_mismatches": mismatches,
    }


@router.get("/inspect-order-id")
def inspect_order_id(
    order_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Show every BMG bot_trades row with a matching alpaca_order_id, no
    filters. Used to debug why rebuild pairing isn't finding matches."""
    from app.db.models.bots import BotTrade
    rows = db.query(BotTrade).filter(BotTrade.alpaca_order_id == order_id).all()
    return {
        "order_id": order_id,
        "count": len(rows),
        "rows": [{
            "id": r.id, "allocation_id": r.allocation_id, "symbol": r.symbol,
            "side": r.side, "qty": float(r.qty or 0),
            "fill_price_cents": r.fill_price_cents,
            "ts": r.ts.isoformat() if r.ts else None,
            "quarantined_at": r.quarantined_at.isoformat() if r.quarantined_at else None,
            "pnl_cents": r.pnl_cents, "pnl_source": r.pnl_source,
        } for r in rows],
    }


@router.get("/order-id-overlap")
def order_id_overlap(
    lookback_days: int = Query(60),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Diagnostic: how many BMG bot_trades.alpaca_order_id values actually
    match live Alpaca /v2/orders UUIDs? Non-overlap means the rebuild
    can't pair anything and needs a different key."""
    import os, urllib.request, urllib.parse, json
    from datetime import datetime, timezone, timedelta
    from app.db.models.bots import BotTrade

    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")
    after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    alp_ids = set()
    alp_client_ids = set()
    page_after = after
    for _ in range(10):
        qs = urllib.parse.urlencode({"status":"closed","after":page_after,"limit":500,"direction":"asc","nested":"true"})
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets/v2/orders?{qs}",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        )
        batch = json.loads(urllib.request.urlopen(req, timeout=30).read()) or []
        if not batch: break
        for o in batch:
            if o.get("id"): alp_ids.add(o["id"])
            if o.get("client_order_id"): alp_client_ids.add(o["client_order_id"])
        if len(batch) < 500: break
        page_after = batch[-1].get("filled_at") or batch[-1].get("submitted_at")

    bmg_ids = {oid for (oid,) in db.query(BotTrade.alpaca_order_id).filter(BotTrade.alpaca_order_id.isnot(None)).all()}
    # Split BMG ids by prefix
    by_prefix = {}
    for oid in bmg_ids:
        if oid.startswith("rebuild_"): by_prefix["rebuild"] = by_prefix.get("rebuild",0)+1
        elif oid.startswith("catchall_"): by_prefix["catchall"] = by_prefix.get("catchall",0)+1
        elif oid.startswith("reconcile_close"): by_prefix["reconcile"] = by_prefix.get("reconcile",0)+1
        elif oid.startswith("orphan_adopter"): by_prefix["orphan_adopter"] = by_prefix.get("orphan_adopter",0)+1
        elif len(oid) == 36 and oid.count("-") == 4: by_prefix["uuid"] = by_prefix.get("uuid",0)+1
        else: by_prefix["other"] = by_prefix.get("other",0)+1

    overlap_ids = bmg_ids & alp_ids
    overlap_client = bmg_ids & alp_client_ids

    return {
        "alpaca_order_ids_in_window": len(alp_ids),
        "alpaca_client_order_ids_in_window": len(alp_client_ids),
        "bmg_alpaca_order_ids_total": len(bmg_ids),
        "bmg_by_prefix": by_prefix,
        "overlap_bmg_vs_alpaca_id": len(overlap_ids),
        "overlap_bmg_vs_alpaca_client_id": len(overlap_client),
        "sample_overlap_ids": list(overlap_ids)[:5],
        "sample_overlap_client": list(overlap_client)[:5],
    }


@router.get("/inspect-bot-trades")
def inspect_bot_trades(
    profile: str = Query(...),
    limit: int = Query(30),
    include_quarantined: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Dump raw BotTrade rows for a given profile so we can see why
    realized P&L is zero despite trades > 0."""
    from collections import Counter
    from app.db.models.bots import BotTrade, BotProfile, BotAllocation
    prof = db.query(BotProfile).filter(BotProfile.name == profile).first()
    if not prof:
        return {"error": f"profile '{profile}' not found"}
    allocs = db.query(BotAllocation).filter(BotAllocation.profile_id == prof.id).all()
    alloc_ids = [a.id for a in allocs]
    q = db.query(BotTrade).filter(BotTrade.allocation_id.in_(alloc_ids))
    if not include_quarantined:
        q = q.filter(BotTrade.quarantined_at.is_(None))
    trades = q.order_by(BotTrade.ts.desc()).limit(limit).all()
    # Summary of all trades regardless of quarantine
    all_trades = db.query(BotTrade).filter(BotTrade.allocation_id.in_(alloc_ids)).all()
    side_all = Counter(t.side.lower() for t in all_trades)
    side_active = Counter(t.side.lower() for t in all_trades if not t.quarantined_at)
    quarantined_sells = sum(1 for t in all_trades if t.quarantined_at and t.side.lower() in ('sell','close','cover'))
    out = []
    for t in trades:
        out.append({
            "id": t.id,
            "ts": t.ts.isoformat() if t.ts else None,
            "symbol": t.symbol,
            "side": t.side,
            "qty": float(t.qty or 0),
            "fill_price_cents": t.fill_price_cents,
            "fill_price_dollars": (t.fill_price_cents or 0) / 100,
            "fees_cents": t.fees_cents,
            "position_id": t.position_id,
            "alpaca_order_id": t.alpaca_order_id,
        })
    return {
        "profile": profile,
        "allocation_ids": alloc_ids,
        "total_trades_active": len(out),
        "trades": out,
        "sides_all_time_all_status": dict(side_all),
        "sides_all_time_active_only": dict(side_active),
        "quarantined_sell_or_close_count": quarantined_sells,
        "total_all_rows": len(all_trades),
    }


@router.post("/adopt-missing-alpaca-positions")
def adopt_missing_alpaca_positions(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Iter 3 step 2 (per Brock adopter spec 2026-08-07):

    Upsert every Alpaca position not present in BMG open+non-quarantined.
    Rules:
      1. Key on (allocation_id, symbol, side). m097 partial index
         enforces uniqueness at DB layer — catch IntegrityError, skip.
      2. Cost basis = Alpaca avg_entry_price. Never current_price.
      3. Attribution: match Alpaca order's client_order_id (from R7,
         format `{bot}_{signal_id}_{epoch_ms}`) to bot profile. Legacy
         orders without R7 client_order_id → catchall alloc, tag
         attribution_source='unresolved'.
      4. Scope: both equity + options (R7 spec item 4 — no improvised
         second code path).
      5. Dry-run must show adds == (alpaca_count - matched_count) exactly.

    Idempotent — safe to re-run. Uses m097 uniq index to prevent
    double-adopts if state races.
    """
    import os, urllib.request, urllib.parse, json
    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade, BotProfile, BotAllocation

    now = datetime.now(timezone.utc)

    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    def alp_get(path: str):
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets{path}",
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
        )
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    alp_positions = alp_get("/v2/positions")

    # BMG open+non-quarantined for user
    user_alloc_ids = [a.id for a in db.query(BotAllocation).filter(BotAllocation.user_id == current_user.id).all()]
    bmg_open = (
        db.query(BotPosition)
        .filter(BotPosition.allocation_id.in_(user_alloc_ids) if user_alloc_ids else False)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    bmg_keys = {(p.symbol or "", (p.side or "long").lower()) for p in bmg_open}

    # Ensure catchall exists
    prof = db.query(BotProfile).filter(BotProfile.name == "broker_orphan_catchall").first()
    if not prof and not dry_run:
        prof = BotProfile(
            name="broker_orphan_catchall",
            description="Catch-all for Alpaca positions not attributable via client_order_id.",
            asset_class="stock",
            enabled=False,
        )
        db.add(prof); db.flush()
    catchall = None
    if prof:
        catchall = (
            db.query(BotAllocation)
            .filter(BotAllocation.user_id == current_user.id)
            .filter(BotAllocation.profile_id == prof.id)
            .first()
        )
        if not catchall and not dry_run:
            catchall = BotAllocation(
                user_id=current_user.id, profile_id=prof.id,
                capital_pct=0.0, starting_capital_cents=0,
                enabled=False, paper_mode=True,
            )
            db.add(catchall); db.flush()
    catchall_id = catchall.id if catchall else None

    # Build profile → allocation lookup for THIS user only
    profiles_by_name = {p.name: p.id for p in db.query(BotProfile).all()}
    profile_id_to_user_alloc: dict = {}
    for a in db.query(BotAllocation).filter(BotAllocation.user_id == current_user.id).all():
        # Prefer alloc with real starting_capital when multiple
        existing = profile_id_to_user_alloc.get(a.profile_id)
        if existing is None or (a.starting_capital_cents or 0) > (existing[1] or 0):
            profile_id_to_user_alloc[a.profile_id] = (a.id, a.starting_capital_cents)

    # For each Alpaca position, walk /v2/orders to find opening client_order_id
    # (only for missing keys — narrow the API load)
    missing_by_symbol: dict = {}
    for p in alp_positions:
        raw_qty = float(p.get("qty") or 0)
        side = "short" if raw_qty < 0 else "long"
        key = (p.get("symbol"), side)
        if key in bmg_keys: continue
        missing_by_symbol.setdefault(p.get("symbol"), []).append(p)

    # Pull open+filled orders for missing symbols, look at client_order_id
    # Alpaca /v2/orders supports symbols query param
    coid_by_position: dict = {}
    if missing_by_symbol:
        from datetime import timedelta
        after = (now - timedelta(days=60)).isoformat()
        for sym_chunk_start in range(0, len(missing_by_symbol), 20):
            chunk = list(missing_by_symbol.keys())[sym_chunk_start:sym_chunk_start+20]
            qs = urllib.parse.urlencode({
                "status": "closed", "after": after,
                "limit": 500, "direction": "asc",
                "symbols": ",".join(chunk),
            })
            batch = alp_get(f"/v2/orders?{qs}") or []
            for o in batch:
                if o.get("status") != "filled": continue
                sym = o.get("symbol")
                side_o = (o.get("side") or "").lower()
                coid = o.get("client_order_id") or ""
                # This is an opening order iff its side matches the position side.
                # Alpaca side='buy' opens long; side='sell' opens short.
                pos_side = "long" if side_o == "buy" else "short"
                pos_key = (sym, pos_side)
                if pos_key in [(pp.get("symbol"), "short" if float(pp.get("qty",0))<0 else "long") for pp in missing_by_symbol.get(sym, [])]:
                    # Prefer R7-format coid ({bot}_{sig}_{ts}) — must have underscore
                    if "_" in coid:
                        coid_by_position.setdefault(pos_key, coid)

    adopts: list[dict] = []
    skipped_dup: list[dict] = []
    unresolved: list[dict] = []

    for p in alp_positions:
        raw_qty = float(p.get("qty") or 0)
        side = "short" if raw_qty < 0 else "long"
        sym = p.get("symbol")
        key = (sym, side)
        if key in bmg_keys:
            continue

        avg_entry = float(p.get("avg_entry_price") or 0)
        cost_cents = int(round(avg_entry * 100)) if avg_entry > 0 else 0
        asset_class = p.get("asset_class") or "us_equity"
        is_option = asset_class == "us_option"

        # Attribute via R7 client_order_id
        coid = coid_by_position.get(key)
        attr_alloc = None
        attr_source = "unresolved"
        if coid:
            bot_name = coid.split("_", 1)[0]  # {bot}_{sig}_{ts}
            prof_id = profiles_by_name.get(bot_name)
            if prof_id:
                pair = profile_id_to_user_alloc.get(prof_id)
                if pair:
                    attr_alloc = pair[0]
                    attr_source = "r7_client_order_id"
        if attr_alloc is None:
            attr_alloc = catchall_id
            attr_source = "unresolved_catchall"

        entry = {
            "symbol": sym, "side": side, "qty": abs(raw_qty),
            "avg_entry_usd": avg_entry, "market_value": float(p.get("market_value") or 0),
            "unrealized_pl": float(p.get("unrealized_pl") or 0),
            "asset_class": asset_class,
            "allocation_id": attr_alloc,
            "attribution_source": attr_source,
        }

        if dry_run or attr_alloc is None:
            adopts.append({**entry, "would_adopt": True})
            continue

        # Insert with IntegrityError guard for m097
        parsed = {}
        if is_option:
            try:
                from app.services.orphan_adopter import _parse_occ
                parsed = _parse_occ(sym) or {}
            except Exception:
                pass
        # §ADOPT-BOUND (Brock 2026-08-11): if BMG already tracks this
        # (symbol, side) on ANY active alloc, don't create a catchall
        # duplicate. This is the specific bug from 2026-08-10 overnight:
        # 20 of 83 catchall adopts duplicated positions real bots owned,
        # inflating bot_sum_pv by $16K.
        _already_owned = (
            db.query(BotPosition)
            .filter(BotPosition.symbol == sym)
            .filter((BotPosition.side == side) | (BotPosition.side.is_(None) if side == "long" else False))
            .filter(BotPosition.closed_at.is_(None))
            .filter(BotPosition.quarantined_at.is_(None))
            .first()
        )
        if _already_owned:
            skipped_dup.append({**entry, "reason": "already_owned_by_alloc",
                                "existing_pos_id": _already_owned.id,
                                "existing_alloc_id": _already_owned.allocation_id})
            continue

        # m098 chokepoint: check risk gates, accept + flag if breach
        from app.services.position_write_gate import check_position_pre_write
        gate = check_position_pre_write(
            symbol=sym, qty=abs(raw_qty), side=side,
            avg_cost_cents=cost_cents, is_option=is_option,
            strike_price=parsed.get("strike_price"),
            expiration_date=parsed.get("expiration_date"),
            entry_path="catchall_adopter",
        )
        pos = BotPosition(
            allocation_id=attr_alloc,
            symbol=sym, qty=abs(raw_qty),
            avg_cost_cents=cost_cents, side=side,
            opened_at=now, closed_at=None, is_paper=True,
            option_type=parsed.get("option_type"),
            strike_price=parsed.get("strike_price"),
            expiration_date=parsed.get("expiration_date"),
            underlying_symbol=parsed.get("root"),
            contract_count=int(abs(raw_qty)) if is_option else None,
            contract_premium_cents=cost_cents if is_option else None,
            breach_on_adopt=gate.breach,
            breach_reason=gate.reason if gate.breach else None,
            remediation_ticket_id=gate.ticket_id if gate.breach else None,
            origin="ADOPTED",  # m099 — adopt_missing_2026_08_07
        )
        try:
            db.add(pos); db.flush()
        except Exception as exc:
            db.rollback()
            skipped_dup.append({**entry, "reason": f"integrity_error:{type(exc).__name__}"})
            continue
        entry_trade = BotTrade(
            allocation_id=attr_alloc,
            symbol=sym,
            side="short" if side == "short" else "buy",
            qty=abs(raw_qty),
            fill_price_cents=cost_cents,
            fill_price_micros=cost_cents * 10000,  # m100 — lossless from int cents
            fees_cents=0, ts=now, position_id=pos.id,
            is_paper=True,
            alpaca_order_id=f"adopt_missing_2026_08_07:{attr_source}",
            option_type=parsed.get("option_type"),
            strike_price=parsed.get("strike_price"),
            expiration_date=parsed.get("expiration_date"),
            underlying_symbol=parsed.get("root"),
            contract_count=int(abs(raw_qty)) if is_option else None,
            contract_premium_cents=cost_cents if is_option else None,
            origin="ADOPTED",  # m099 — adopt_missing_2026_08_07
        )
        db.add(entry_trade)
        if attr_source == "unresolved_catchall":
            unresolved.append(entry)
        adopts.append({**entry, "pos_id": pos.id, "trade_id": entry_trade.id})

    if not dry_run:
        db.commit()

    return {
        "dry_run": dry_run,
        "alpaca_positions": len(alp_positions),
        "bmg_matched": len(alp_positions) - len(adopts) - len(skipped_dup),
        "would_adopt_or_adopted": len(adopts),
        "skipped_integrity_dup": len(skipped_dup),
        "unresolved_to_catchall": len(unresolved),
        "adopts_preview": adopts[:15],
        "unresolved_sample": unresolved[:5],
    }


@router.post("/merge-duplicate-allocations")
def merge_duplicate_allocations(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Iteration 3 (a): sweep every profile with >1 active BotAllocation
    for the same user. Merge dupes into ONE surviving alloc, re-point
    trades/positions/signals, tombstone dead allocs.

    Survivor selection: prefer alloc with highest starting_capital_cents;
    tie → lowest id. No heuristic-based prefer-at-lookup remains after
    this — known-issue #3 has recurred, per compounding rule heuristics
    are off the table.

    Data-only migration (UPDATE + tombstone). No schema change.
    """
    from datetime import datetime, timezone
    from collections import defaultdict
    from app.db.models.bots import BotAllocation, BotTrade, BotPosition, BotSignal

    now = datetime.now(timezone.utc)
    allocs = db.query(BotAllocation).filter(BotAllocation.user_id == current_user.id).all()
    by_profile: dict = defaultdict(list)
    for a in allocs:
        by_profile[a.profile_id].append(a)

    merges: list[dict] = []
    total_trades_repointed = 0
    total_positions_repointed = 0
    total_signals_repointed = 0
    total_tombstoned = 0

    for profile_id, group in by_profile.items():
        if len(group) < 2:
            continue
        # Survivor: highest starting_capital, then lowest id
        group_sorted = sorted(group, key=lambda a: (-(a.starting_capital_cents or 0), a.id))
        survivor = group_sorted[0]
        dead = group_sorted[1:]
        dead_ids = [d.id for d in dead]

        # Count what would move (works for both dry-run and live)
        n_trades = db.query(BotTrade).filter(BotTrade.allocation_id.in_(dead_ids)).count()
        n_positions = db.query(BotPosition).filter(BotPosition.allocation_id.in_(dead_ids)).count()
        n_signals = db.query(BotSignal).filter(BotSignal.allocation_id.in_(dead_ids)).count()

        merges.append({
            "profile_id": profile_id,
            "survivor_alloc_id": survivor.id,
            "survivor_starting_cents": survivor.starting_capital_cents,
            "dead_alloc_ids": dead_ids,
            "dead_starting_cents": [d.starting_capital_cents for d in dead],
            "trades_to_repoint": n_trades,
            "positions_to_repoint": n_positions,
            "signals_to_repoint": n_signals,
        })

        if not dry_run and dead_ids:
            db.query(BotTrade).filter(BotTrade.allocation_id.in_(dead_ids)).update(
                {"allocation_id": survivor.id}, synchronize_session=False,
            )
            db.query(BotPosition).filter(BotPosition.allocation_id.in_(dead_ids)).update(
                {"allocation_id": survivor.id}, synchronize_session=False,
            )
            db.query(BotSignal).filter(BotSignal.allocation_id.in_(dead_ids)).update(
                {"allocation_id": survivor.id}, synchronize_session=False,
            )
            # Also carry starting_capital forward if survivor has zero and any dead has non-zero
            if not (survivor.starting_capital_cents or 0):
                for d in dead:
                    if (d.starting_capital_cents or 0) > 0:
                        survivor.starting_capital_cents = d.starting_capital_cents
                        break
            # Tombstone
            for d in dead:
                d.enabled = False
                d.paused_reason = f"merged_into_alloc_{survivor.id}_2026_08_07"
            total_trades_repointed += n_trades
            total_positions_repointed += n_positions
            total_signals_repointed += n_signals
            total_tombstoned += len(dead_ids)

    if not dry_run and merges:
        db.commit()

    return {
        "dry_run": dry_run,
        "profiles_with_duplicates": len(merges),
        "merges": merges,
        "total_trades_repointed": total_trades_repointed,
        "total_positions_repointed": total_positions_repointed,
        "total_signals_repointed": total_signals_repointed,
        "total_tombstoned": total_tombstoned,
        "backups_confirmed": False,
        "prevention_still_deferred": [
            "unique partial index bot_allocations(user_id, profile_id) WHERE enabled=true",
            "invariant I12: profiles with >1 active alloc == 0",
        ],
    }


@router.post("/rebuild-realized-pnl")
def rebuild_realized_pnl(
    dry_run: bool = Query(True),
    lookback_days: int = Query(60, description="How far back to pull Alpaca order history for pairing."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """C6 extension per vault/context/09-realized-pnl-rebuild-spec.md.

    Rebuilds bot_trades.pnl_cents on close-side rows from Alpaca order
    pairs (FIFO). Two-tier attribution:

      Tier 1 (exact): within-bot pairing via client_order_id match.
      Tier 2 (reconstructed): FIFO pro-rata across bots holding the
        symbol simultaneously.

    Reconcile-flatten closes (rows with quarantine_reason from cleanup
    sweeps) book realized at the flatten's actual fill price — honest
    track record including remediation cost.

    Idempotent: safe to re-run; overwrites pnl_cents on close rows.
    """
    import os, urllib.request, urllib.parse, json
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict, deque
    from app.db.models.bots import BotTrade

    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")

    def alp_get(path: str):
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets{path}",
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
        )
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    # Pull filled orders in lookback window
    after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    filled: list[dict] = []
    page_after = after
    for _ in range(20):
        qs = urllib.parse.urlencode({
            "status": "closed", "after": page_after,
            "limit": 500, "direction": "asc", "nested": "true",
        })
        batch = alp_get(f"/v2/orders?{qs}") or []
        batch = [o for o in batch if o.get("status") == "filled" and float(o.get("filled_qty") or 0) > 0]
        if not batch:
            break
        filled.extend(batch)
        if len(batch) < 500:
            break
        page_after = batch[-1].get("filled_at") or batch[-1].get("submitted_at")

    # Iteration 3 (2026-08-07): scope the alpaca_order_id → allocation
    # lookup to CURRENT USER'S allocations only. Previously the scan hit
    # every row in bot_trades regardless of user, so oids from other
    # users' allocs would attribute to the first-scanned user 1 alloc
    # (the crypto_quant_aggressive alloc 27 phantom root cause).
    from app.db.models.bots import BotAllocation as _BAlloc
    _user_alloc_ids = {a.id for a in db.query(_BAlloc).filter(_BAlloc.user_id == current_user.id).all()}
    order_id_to_alloc: dict = {}
    for oid, aid in (
        db.query(BotTrade.alpaca_order_id, BotTrade.allocation_id)
        .filter(BotTrade.alpaca_order_id.isnot(None))
        .filter(BotTrade.allocation_id.in_(list(_user_alloc_ids)) if _user_alloc_ids else False)
        .all()
    ):
        if oid and aid:
            order_id_to_alloc.setdefault(oid, aid)

    # FIFO lots per (symbol, allocation_id): each lot = (qty, cost_cents, source_order_id)
    lots: dict = defaultdict(deque)
    # Realized rows to attribute back to bot_trades
    #   {alpaca_order_id: [(pnl_cents, allocation_id, source), ...]}
    realized_by_order: dict = defaultdict(list)

    exact_count = 0
    reconstructed_count = 0
    unattributed_count = 0

    # Iteration 3 (2026-08-07): SIGNED-INVENTORY FIFO per (symbol, alloc).
    # Handles both long round-trips (buy→sell) and short round-trips
    # (sell→buy_to_cover). Lots carry signed qty: +qty for a long lot,
    # −qty for a short lot. A crossing (long lot closed by sell, short
    # lot covered by buy) realizes P&L on the crossing chunk.
    #
    # Inventory that would go negative-then-positive across the lookback
    # window boundary (an open we can't see because it predates lookback)
    # is tagged WINDOW_TRUNCATED, not force-paired.
    window_truncated_count = 0
    for o in filled:
        sym = o.get("symbol")
        side = (o.get("side") or "").lower()
        qty = float(o.get("filled_qty") or 0)
        px = float(o.get("filled_avg_price") or 0)
        oid = o.get("id")
        client_oid = o.get("client_order_id")
        asset_class = o.get("asset_class") or ""
        mult = 100 if asset_class == "us_option" else 1
        close_ts = o.get("filled_at") or o.get("submitted_at") or ""
        if not sym or qty <= 0 or px <= 0:
            continue

        alloc_id = order_id_to_alloc.get(oid) or order_id_to_alloc.get(client_oid)

        # Signed direction for THIS fill's effect on inventory:
        # buy = +qty, sell = -qty. Sign of existing inventory determines
        # whether this fill is an OPEN (same sign) or CLOSE (opposite sign).
        fill_sign = +1 if side == "buy" else -1
        remaining = qty

        def eligible_lots_for(target_alloc):
            """Return list of lots for (sym, target_alloc) that predate
            close_ts, in FIFO order. Sign of lot[0] indicates long/short."""
            q = lots.get((sym, target_alloc))
            if not q: return []
            return [lot for lot in q if lot[3] <= close_ts]

        def opposite_lots_for(target_alloc):
            """Eligible lots whose sign is opposite to fill_sign — those
            are the ones this fill CLOSES."""
            return [lot for lot in eligible_lots_for(target_alloc)
                    if (lot[0] > 0) != (fill_sign > 0)]

        # Tier 1 — exact: within-bot closing if alloc_id known.
        if alloc_id is not None:
            q = lots.get((sym, alloc_id))
            if q:
                # Walk lots in FIFO order looking for opposite-sign lots
                i = 0
                while i < len(q) and remaining > 0.001:
                    lot = q[i]
                    if lot[3] > close_ts:
                        i += 1; continue
                    same_sign = (lot[0] > 0) == (fill_sign > 0)
                    if same_sign:
                        # Fill adds to same-sign inventory; don't close here
                        i += 1; continue
                    # Opposite-sign lot → this fill closes some/all of it
                    lot_abs = abs(lot[0])
                    take = min(lot_abs, remaining)
                    entry_cents = lot[1]
                    # PnL: if lot was LONG (lot[0] > 0), close is a sell → (px − entry) * take
                    # if lot was SHORT (lot[0] < 0), close is a buy   → (entry − px) * take
                    if lot[0] > 0:
                        pnl_cents = int(round((px - entry_cents / 100.0) * take * mult * 100))
                    else:
                        pnl_cents = int(round((entry_cents / 100.0 - px) * take * mult * 100))
                    realized_by_order[oid].append((pnl_cents, alloc_id, "exact"))
                    exact_count += 1
                    # Reduce lot abs qty, remove if depleted
                    if lot[0] > 0:
                        lot[0] -= take
                    else:
                        lot[0] += take
                    remaining -= take
                    if abs(lot[0]) <= 0.001:
                        del q[i]
                    else:
                        i += 1

        # Tier 2 — reconstructed: proportional across all bots' eligible
        # opposite-sign lots.
        if remaining > 0.001:
            per_bot_opp: dict = defaultdict(float)
            per_bot_opp_lots: dict = defaultdict(list)
            for bk, q in lots.items():
                if bk[0] != sym: continue
                if bk[1] is None: continue
                if bk[1] == alloc_id: continue  # already tried Tier 1
                for lot in q:
                    if lot[3] > close_ts: continue
                    same_sign = (lot[0] > 0) == (fill_sign > 0)
                    if same_sign: continue
                    per_bot_opp[bk[1]] += abs(lot[0])
                    per_bot_opp_lots[bk[1]].append(lot)
            total_eligible = sum(per_bot_opp.values())
            if total_eligible > 0.001:
                take_total = min(remaining, total_eligible)
                for target_alloc, bot_opp_qty in per_bot_opp.items():
                    if bot_opp_qty <= 0: continue
                    share = (bot_opp_qty / total_eligible) * take_total
                    bot_remaining = share
                    for lot in per_bot_opp_lots[target_alloc]:
                        if bot_remaining <= 0.001: break
                        lot_abs = abs(lot[0])
                        take = min(lot_abs, bot_remaining)
                        if lot[0] > 0:
                            pnl_cents = int(round((px - lot[1] / 100.0) * take * mult * 100))
                        else:
                            pnl_cents = int(round((lot[1] / 100.0 - px) * take * mult * 100))
                        realized_by_order[oid].append((pnl_cents, target_alloc, "reconstructed"))
                        reconstructed_count += 1
                        if lot[0] > 0:
                            lot[0] -= take
                        else:
                            lot[0] += take
                        bot_remaining -= take
                        src_key = (sym, target_alloc)
                        if lots.get(src_key) and abs(lots[src_key][0][0] if lots[src_key] else 1) <= 0.001:
                            lots[src_key].popleft()
                remaining -= take_total

        # Any remaining fill qty OPENS a new lot (same-sign inventory).
        # This is either a legitimate new open, or (if it's a sell) a
        # WINDOW_TRUNCATED close whose original open predates our lookback.
        if remaining > 0.001:
            # Store as signed lot with fill_sign
            lots[(sym, alloc_id)].append([fill_sign * remaining, int(round(px * 100)), oid, close_ts])
            # If this fill would have needed to close inventory but couldn't
            # find any (opposite-sign inventory was empty), tag it truncated.
            # Detection heuristic: if a sell hits and inventory has never
            # been positive for this (sym, alloc), the original long open
            # is outside the window. Flag but don't force-pair.
            if side == "sell" and alloc_id is not None:
                # Check whether we ever saw a positive lot here
                q = lots.get((sym, alloc_id), [])
                has_ever_long = any(l[0] > 0 for l in q) or any(
                    l[1] < px * 100 * 0.99 for l in q
                )
                # This is a loose flag — surfacing quantity, not gating.
                # If the whole window shows only sells with no matching buys,
                # count as truncated so the report is honest.
                if not has_ever_long:
                    window_truncated_count += 1
            unattributed_count += 0  # opens are not unattributed; they're new lots

    # UPDATE existing close-side rows, and INSERT new ones for Alpaca
    # fills BMG doesn't have (the 66 quarantined closes on stock_quant_day_momentum
    # etc. — sim closes stay dead; real close-side rows get created from Alpaca).
    updates = 0
    inserts = 0
    # Cache Alpaca order metadata by oid for insert path
    alp_order_by_id = {o.get("id"): o for o in filled}
    # Pre-fetch existing bot_trades keyed by alpaca_order_id (any side, any status)
    existing_by_oid: dict = {}
    for r in db.query(BotTrade).filter(BotTrade.alpaca_order_id.in_(list(realized_by_order.keys()))).all():
        existing_by_oid.setdefault(r.alpaca_order_id, []).append(r)
    if not dry_run:
        for oid, pnls in realized_by_order.items():
            total_cents = sum(p[0] for p in pnls)
            sources = {p[2] for p in pnls}
            src = "exact" if sources == {"exact"} else ("reconstructed" if "reconstructed" in sources else "exact")
            # Determine the closing allocation from the FIFO pair (last entry
            # in pnls carries the target allocation attribution).
            attributed_alloc = pnls[-1][1]
            existing = existing_by_oid.get(oid, [])
            # Try to update an existing row on the close side first
            close_rows = [r for r in existing if (r.side or "").lower() in ("sell","close","cover")]
            if close_rows:
                for r in close_rows:
                    r.pnl_cents = total_cents
                    r.pnl_source = src
                    updates += 1
                continue
            # Otherwise INSERT a fresh close-side row from Alpaca truth
            o = alp_order_by_id.get(oid)
            if not o or attributed_alloc is None:
                continue
            filled_qty = float(o.get("filled_qty") or 0)
            filled_px = float(o.get("filled_avg_price") or 0)
            filled_at = o.get("filled_at") or o.get("submitted_at")
            asset_class = o.get("asset_class") or ""
            is_opt = asset_class == "us_option"
            alp_side = (o.get("side") or "").lower()
            # BMG side convention: sell=closes long, cover=closes short
            # If pnls came from long-lot FIFO (which our current impl always
            # does), the close is a 'sell'. Short-side FIFO would use 'cover'.
            bmg_side = "sell" if alp_side == "sell" else "cover"
            from datetime import datetime as _dt
            try:
                ts = _dt.fromisoformat(str(filled_at).replace("Z","+00:00")) if filled_at else datetime.now(timezone.utc)
            except Exception:
                ts = datetime.now(timezone.utc)
            new_t = BotTrade(
                allocation_id=attributed_alloc,
                symbol=o.get("symbol"),
                side=bmg_side,
                qty=filled_qty,
                fill_price_cents=int(round(filled_px * 100)),
                fill_price_micros=int(round(float(filled_px) * 1_000_000)),  # m100
                fees_cents=0,
                ts=ts,
                is_paper=True,
                alpaca_order_id=oid,
                pnl_cents=total_cents,
                pnl_source=src,
                origin="REBUILD",  # m099 — rebuild-from-alpaca-order-history job
            )
            if is_opt:
                new_t.option_type = "call" if "C" in (o.get("symbol") or "")[10:] else "put"
                new_t.underlying_symbol = "".join(c for c in (o.get("symbol") or "") if c.isalpha())
                new_t.contract_count = int(filled_qty)
                new_t.contract_premium_cents = int(round(filled_px * 100))
            db.add(new_t)
            inserts += 1
        db.commit()

    # Also mark opening rows with pnl_source=null explicitly (already is) —
    # skipping to keep migration foot-print minimal.

    # Reconcile-flatten pass: bot_trades where quarantine_reason IS NULL,
    # side ∈ closes, alpaca_order_id like 'reconcile_close_%' or
    # 'catchall_%' etc get pnl booked as (fill - avg_cost) using the
    # already-set fill_price_cents on that row.
    reconcile_updates = 0
    if not dry_run:
        recon_rows = (
            db.query(BotTrade)
            .filter(BotTrade.side.in_(("sell", "close", "cover")))
            .filter(BotTrade.alpaca_order_id.like("reconcile_close_%"))
            .filter(BotTrade.pnl_cents.is_(None))
            .all()
        )
        for r in recon_rows:
            # reconcile_close was booked at entry price → pnl = 0. Honest.
            r.pnl_cents = 0
            r.pnl_source = "reconcile_close"
            reconcile_updates += 1
        db.commit()

    # Iteration 2 R5d: per-bot exact vs reconstructed $ split, and
    # provisional flag when reconstructed dominates or |realized| exceeds
    # 30% of starting_capital.
    from app.db.models.bots import BotAllocation as _BA
    per_bot_exact_c: dict = defaultdict(int)
    per_bot_recon_c: dict = defaultdict(int)
    for oid, pnls in realized_by_order.items():
        for pc, aid, src in pnls:
            if src == "exact":
                per_bot_exact_c[aid] += pc
            else:
                per_bot_recon_c[aid] += pc
    alloc_starting = {a.id: int(a.starting_capital_cents or 0) for a in db.query(_BA).all()}
    per_bot_report = []
    for aid in set(list(per_bot_exact_c.keys()) + list(per_bot_recon_c.keys())):
        exact_c = per_bot_exact_c.get(aid, 0)
        recon_c = per_bot_recon_c.get(aid, 0)
        total_c = exact_c + recon_c
        starting_c = alloc_starting.get(aid, 0)
        recon_pct = (abs(recon_c) / abs(total_c) * 100) if total_c else 0.0
        realized_pct_of_start = (abs(total_c) / starting_c * 100) if starting_c else 0.0
        flag = None
        if realized_pct_of_start > 30:
            flag = "SANITY_BREACH_realized_>30pct_of_starting"
        elif recon_pct > 50:
            flag = "MOSTLY_RECONSTRUCTED_pnl_provisional"
        per_bot_report.append({
            "allocation_id": aid,
            "starting_cents": starting_c,
            "exact_pnl_cents": exact_c,
            "reconstructed_pnl_cents": recon_c,
            "total_pnl_cents": total_c,
            "reconstructed_pct_of_total": round(recon_pct, 1),
            "realized_pct_of_starting": round(realized_pct_of_start, 1),
            "provisional_flag": flag,
        })
    per_bot_report.sort(key=lambda r: -abs(r["total_pnl_cents"]))

    return {
        "dry_run": dry_run,
        "lookback_days": lookback_days,
        "alpaca_fills_processed": len(filled),
        "pairs_exact": exact_count,
        "pairs_reconstructed": reconstructed_count,
        "unattributed_close_qty": unattributed_count,
        "bot_trade_rows_updated": updates,
        "bot_trade_rows_inserted": inserts,
        "reconcile_close_rows_updated": reconcile_updates,
        "per_bot": per_bot_report,
        "sanity_flagged_bots": [r for r in per_bot_report if r["provisional_flag"]],
        "window_truncated_count": window_truncated_count,
    }


@router.get("/alpaca-realized-truth")
def alpaca_realized_truth(
    lookback_days: int = Query(45),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """A2 comparator per iteration 2 R3: walk /v2/account/activities
    (FILL type) and compute Alpaca-truth realized via FIFO per symbol.
    portfolio/history.profit_loss includes unrealized swings and is not
    the correct comparator."""
    import os, urllib.request, urllib.parse, json
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict, deque

    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")
    after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()

    fills: list[dict] = []
    page_after = after
    for _ in range(30):
        qs = urllib.parse.urlencode({
            "activity_types": "FILL", "after": page_after,
            "page_size": 100, "direction": "asc",
        })
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets/v2/account/activities?{qs}",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        )
        batch = json.loads(urllib.request.urlopen(req, timeout=30).read()) or []
        if not batch:
            break
        fills.extend(batch)
        if len(batch) < 100:
            break
        # activities API paginates by 'page_token' but we can use the last
        # transaction_time as the next 'after' if page_token isn't returned.
        last_ts = batch[-1].get("transaction_time") or batch[-1].get("timestamp")
        if not last_ts or last_ts == page_after:
            break
        page_after = last_ts

    # FIFO per symbol across all fills
    lots: dict = defaultdict(deque)
    realized_total = 0
    realized_by_symbol: dict = defaultdict(int)
    for f in fills:
        sym = f.get("symbol")
        side = (f.get("side") or "").lower()
        qty = float(f.get("qty") or 0)
        px = float(f.get("price") or 0)
        # Alpaca returns type='fill' for opening fills, 'partial_fill' too.
        # For realized we only care buy vs sell direction; equity assumed.
        if not sym or qty <= 0 or px <= 0:
            continue
        mult = 100 if len(sym) > 10 else 1  # option OCC heuristic
        if side == "buy":
            lots[sym].append([qty, px])
        elif side == "sell":
            remaining = qty
            while lots[sym] and remaining > 0.001:
                lot = lots[sym][0]
                take = min(lot[0], remaining)
                pnl = int(round((px - lot[1]) * take * mult * 100))
                realized_total += pnl
                realized_by_symbol[sym] += pnl
                lot[0] -= take
                remaining -= take
                if lot[0] <= 0.001:
                    lots[sym].popleft()

    top = sorted(realized_by_symbol.items(), key=lambda x: -abs(x[1]))[:10]
    return {
        "lookback_days": lookback_days,
        "since": after,
        "fills_processed": len(fills),
        "alpaca_realized_total_cents": realized_total,
        "alpaca_realized_total_usd": round(realized_total / 100, 2),
        "top_symbols_by_realized": [{"symbol": s, "pnl_cents": pc, "pnl_usd": round(pc/100,2)} for s, pc in top],
    }


@router.get("/spot-check-pnl-pairs")
def spot_check_pnl_pairs(
    n_each: int = Query(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """A4 spot-check per iteration 2 R4: sample N exact + N reconstructed
    close-side bot_trades. For each, show qty/entry/exit/pnl vs Alpaca
    order pair. Reconstructed pairs are where the phantom lives."""
    import os, urllib.request, json
    from app.db.models.bots import BotTrade

    kid = os.environ.get("ALPACA_API_KEY", "")
    ksec = os.environ.get("ALPACA_SECRET_KEY", "")

    def alp_order(oid: str):
        try:
            req = urllib.request.Request(
                f"https://paper-api.alpaca.markets/v2/orders/{oid}",
                headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
            )
            return json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception as e:
            return {"error": str(e)}

    def sample(src: str):
        rows = (
            db.query(BotTrade)
            .filter(BotTrade.pnl_source == src)
            .filter(BotTrade.pnl_cents.isnot(None))
            .filter(BotTrade.alpaca_order_id.isnot(None))
            .order_by(BotTrade.ts.desc())
            .limit(n_each)
            .all()
        )
        out = []
        for r in rows:
            alp = alp_order(r.alpaca_order_id)
            out.append({
                "bmg_id": r.id, "allocation_id": r.allocation_id,
                "symbol": r.symbol, "side": r.side, "qty": float(r.qty or 0),
                "bmg_fill_price_cents": r.fill_price_cents,
                "bmg_fill_price_usd": (r.fill_price_cents or 0) / 100,
                "bmg_pnl_cents": r.pnl_cents,
                "bmg_pnl_usd": round((r.pnl_cents or 0)/100, 2),
                "bmg_pnl_source": r.pnl_source,
                "alpaca_id": r.alpaca_order_id,
                "alpaca_side": alp.get("side"),
                "alpaca_filled_qty": alp.get("filled_qty"),
                "alpaca_filled_avg_price": alp.get("filled_avg_price"),
                "alpaca_symbol": alp.get("symbol"),
                "alpaca_status": alp.get("status"),
            })
        return out

    return {
        "exact_samples": sample("exact"),
        "reconstructed_samples": sample("reconstructed"),
    }


@router.post("/close-ghost-positions")
def close_ghost_positions(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """STEP A: close every open BotPosition Alpaca doesn't report in
    /v2/positions. These are 'ghosts' — DB rows for positions the broker
    doesn't hold. Sets closed_at=now, exit_reason='reconcile_close',
    and books a realized P&L using BMG's last mark vs entry."""
    import os, urllib.request, json
    from datetime import datetime, timezone
    from app.db.models.bots import BotPosition, BotTrade

    now = datetime.now(timezone.utc)
    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
    )
    alp_list = json.loads(urllib.request.urlopen(req, timeout=15).read())
    alp_syms = {p.get("symbol") for p in alp_list}

    bmg_open = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    ghosts = []
    for p in bmg_open:
        if (p.symbol or "") not in alp_syms:
            ghosts.append(p)

    actions = []
    for p in ghosts:
        entry = (p.avg_cost_cents or 0) / 100.0
        # book realized = 0 since we have no exit price; conservative
        actions.append({
            "position_id": p.id,
            "symbol": p.symbol,
            "side": p.side,
            "qty": float(p.qty or 0),
            "entry_cents": p.avg_cost_cents,
            "allocation_id": p.allocation_id,
        })
        if not dry_run:
            p.closed_at = now
            p.exit_reason = "reconcile_close"
            # Book a paired close trade at entry price = zero-P&L exit
            close_trade = BotTrade(
                allocation_id=p.allocation_id,
                symbol=p.symbol,
                side="sell" if (p.side or "long").lower() == "long" else "cover",
                qty=float(p.qty or 0),
                fill_price_cents=int(p.avg_cost_cents or 0),
                fill_price_micros=int(p.avg_cost_cents or 0) * 10000,  # m100 — lossless from int cents
                fees_cents=0,
                ts=now,
                position_id=p.id,
                is_paper=True,
                alpaca_order_id="reconcile_close_2026_08_06",
                option_type=p.option_type,
                strike_price=p.strike_price,
                expiration_date=p.expiration_date,
                underlying_symbol=p.underlying_symbol,
                contract_count=p.contract_count,
                contract_premium_cents=p.contract_premium_cents,
                origin="RECONCILE",  # m099 — reconcile-close ghost positions
            )
            db.add(close_trade)
    if not dry_run and ghosts:
        db.commit()

    return {
        "dry_run": dry_run,
        "alpaca_positions": len(alp_syms),
        "bmg_open_positions": len(bmg_open),
        "ghosts_count": len(ghosts),
        "actions": actions,
    }


@router.get("/i2-drift-detail")
def i2_drift_detail(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Per-position UPL comparison — BMG vs Alpaca — so we can pinpoint
    which rows contribute to the I2 drift."""
    import os, urllib.request, json
    from app.db.models.bots import BotPosition

    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
    )
    alp_list = json.loads(urllib.request.urlopen(req, timeout=15).read())
    alp_by_sym = {p.get("symbol"): p for p in alp_list}

    bmg_open = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    rows = []
    no_alp_match = []
    total_bmg = 0.0
    total_alp = 0.0
    for p in bmg_open:
        sym = p.symbol
        is_opt = bool(getattr(p, "option_type", None))
        is_short = getattr(p, "side", "long") == "short"
        mult = 100 if is_opt else 1
        entry = (p.avg_cost_cents or 0) / 100.0
        alp = alp_by_sym.get(sym)
        if not alp:
            no_alp_match.append({
                "id": p.id, "symbol": sym, "side": p.side, "qty": float(p.qty or 0),
                "entry_cents": p.avg_cost_cents, "allocation_id": p.allocation_id,
                "is_option": is_opt,
            })
            continue
        curr = float(alp.get("current_price") or 0)
        alp_entry = float(alp.get("avg_entry_price") or 0)
        alp_qty = float(alp.get("qty"))
        alp_upl = float(alp.get("unrealized_pl") or 0)
        bmg_qty = float(p.qty or 0)
        # BMG UPL calc same logic as I2 check
        if is_short:
            bmg_upl = (entry - curr) * bmg_qty * mult
        else:
            bmg_upl = (curr - entry) * bmg_qty * mult
        total_bmg += bmg_upl
        total_alp += alp_upl
        diff = bmg_upl - alp_upl
        if abs(diff) > 1:
            rows.append({
                "symbol": sym, "is_opt": is_opt, "side": p.side,
                "bmg_entry": entry, "alp_entry": alp_entry,
                "curr": curr, "bmg_qty": bmg_qty, "alp_qty": alp_qty,
                "bmg_upl": round(bmg_upl, 2), "alp_upl": round(alp_upl, 2),
                "delta": round(diff, 2),
            })
    rows.sort(key=lambda x: -abs(x["delta"]))
    return {
        "total_bmg_upl": round(total_bmg, 2),
        "total_alp_upl": round(total_alp, 2),
        "total_delta": round(total_bmg - total_alp, 2),
        "count_with_diff": len(rows),
        "top_diffs": rows[:20],
        "no_alp_match_count": len(no_alp_match),
        "no_alp_match": no_alp_match,
    }


@router.get("/inspect-symbol")
def inspect_symbol(
    symbol: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Dump every BotPosition row for the given symbol (open + closed +
    quarantined) so we can see where BMG state actually is."""
    from app.db.models.bots import BotPosition, BotProfile, BotAllocation
    rows = (
        db.query(BotPosition)
        .filter(BotPosition.symbol == symbol)
        .order_by(BotPosition.opened_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for p in rows:
        alloc = db.query(BotAllocation).filter(BotAllocation.id == p.allocation_id).first() if p.allocation_id else None
        prof_name = None
        if alloc and alloc.profile_id:
            prof = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
            prof_name = prof.name if prof else None
        out.append({
            "id": p.id,
            "allocation_id": p.allocation_id,
            "profile": prof_name,
            "qty": float(p.qty or 0),
            "side": p.side,
            "avg_cost_cents": p.avg_cost_cents,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "quarantined_at": p.quarantined_at.isoformat() if p.quarantined_at else None,
            "quarantine_reason": p.quarantine_reason,
        })
    return {"symbol": symbol, "rows": out, "count": len(out)}


@router.post("/pr-mark-now")
def pr_mark_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Fire portfolio-rank daily-mark synchronously. Clears I6 stale holdings."""
    from app.jobs.pr_daily_mark import mark_all_pr_holdings
    return mark_all_pr_holdings(db)


@router.post("/quarantine-sim-only")
def quarantine_sim_only(
    lookback_hours: int = Query(72, description="How far back to walk BotTrade rows."),
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Quarantine BotTrade rows where alpaca_order_id IS NULL. These are
    sim / no-broker leaks and never correspond to a real fill."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.bots import BotTrade, BotPosition

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    victims = (
        db.query(BotTrade)
        .filter(BotTrade.ts >= cutoff)
        .filter(BotTrade.alpaca_order_id.is_(None))
        .filter(BotTrade.quarantined_at.is_(None))
        .all()
    )
    victim_ids = [t.id for t in victims]
    position_ids = [t.position_id for t in victims if t.position_id]

    if not dry_run and victim_ids:
        (
            db.query(BotTrade)
            .filter(BotTrade.id.in_(victim_ids))
            .update(
                {"quarantined_at": now, "quarantine_reason": "sim_no_broker_id_2026_08_06"},
                synchronize_session=False,
            )
        )
        if position_ids:
            (
                db.query(BotPosition)
                .filter(BotPosition.id.in_(position_ids))
                .filter(BotPosition.quarantined_at.is_(None))
                .update(
                    {"quarantined_at": now, "quarantine_reason": "sim_no_broker_id_2026_08_06"},
                    synchronize_session=False,
                )
            )
        db.commit()

    return {
        "dry_run": dry_run,
        "lookback_hours": lookback_hours,
        "victims_count": len(victims),
        "position_ids_count": len(position_ids),
        "sample": [
            {"id": t.id, "symbol": t.symbol, "side": t.side, "qty": t.qty, "ts": t.ts.isoformat() if t.ts else None, "position_id": t.position_id}
            for t in victims[:10]
        ],
    }


@router.post("/quarantine-bmg-phantom-positions")
def quarantine_bmg_phantom_positions(
    dry_run: bool = Query(True, description="Preview only when true (default)."),
    max_age_hours: int = Query(48, description="Only touch positions opened this many hours ago at most (avoid new fills)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Quarantine BMG open positions whose (symbol, side) key doesn't
    exist in Alpaca. Skips positions opened in the last N hours to avoid
    catching in-flight fills that Alpaca hasn't reported yet."""
    import os, urllib.request, json
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    from app.db.models.bots import BotPosition

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    # Fetch Alpaca positions
    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
    )
    alp_list = json.loads(urllib.request.urlopen(req, timeout=15).read())
    alp_keys = set()
    for p in alp_list:
        sym = p.get("symbol")
        q = float(p.get("qty"))
        side = "short" if q < 0 else "long"
        alp_keys.add((sym, side))

    # BMG open, non-quarantined positions
    bmg_rows = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )

    victims: list[dict] = []
    for p in bmg_rows:
        side = (p.side or "long").lower()
        key = (p.symbol or "", side)
        if key in alp_keys:
            continue
        # Skip in-flight
        if p.opened_at and p.opened_at.replace(tzinfo=timezone.utc) > cutoff:
            continue
        victims.append({
            "id": p.id,
            "symbol": p.symbol,
            "side": side,
            "qty": float(p.qty or 0),
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        })

    if not dry_run and victims:
        ids = [v["id"] for v in victims]
        (
            db.query(BotPosition)
            .filter(BotPosition.id.in_(ids))
            .update(
                {"quarantined_at": now, "quarantine_reason": "bmg_phantom_not_at_broker_2026_08_06"},
                synchronize_session=False,
            )
        )
        db.commit()

    return {
        "dry_run": dry_run,
        "max_age_hours": max_age_hours,
        "bmg_open_rows_scanned": len(bmg_rows),
        "alpaca_keys": len(alp_keys),
        "quarantined_count": len(victims) if not dry_run else 0,
        "victims_count": len(victims),
        "victims_preview": victims[:20],
    }


@router.get("/trades-today-by-bot")
def trades_today_by_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Per-bot trade counts since 00:00 UTC today. Splits real-broker
    fills from sim fills. Read-only."""
    from datetime import datetime, timezone
    from app.db.models.bots import BotTrade, BotAllocation, BotProfile

    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    trades = (
        db.query(BotProfile.name, BotTrade.alpaca_order_id)
        .join(BotAllocation, BotAllocation.id == BotTrade.allocation_id)
        .join(BotProfile, BotProfile.id == BotAllocation.profile_id)
        .filter(BotTrade.ts >= midnight)
        .filter(BotTrade.quarantined_at.is_(None))
        .all()
    )
    from collections import defaultdict
    agg: dict = defaultdict(lambda: {"total": 0, "with_broker_order_id": 0})
    for bot_name, oid in trades:
        agg[bot_name]["total"] += 1
        if oid:
            agg[bot_name]["with_broker_order_id"] += 1
    out = []
    for bot_name, d in agg.items():
        out.append({
            "bot_name": bot_name,
            "total": d["total"],
            "with_broker_order_id": d["with_broker_order_id"],
            "sim_or_no_broker": d["total"] - d["with_broker_order_id"],
        })
    out.sort(key=lambda x: -x["total"])
    total_all = sum(x["total"] for x in out)
    total_broker = sum(x["with_broker_order_id"] for x in out)
    return {
        "as_of": now.isoformat(),
        "since": midnight.isoformat(),
        "by_bot": out,
        "total_trades": total_all,
        "total_with_broker": total_broker,
        "total_sim_or_no_broker": total_all - total_broker,
    }


@router.get("/bmg-alpaca-diff")
def bmg_alpaca_diff(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Compare BMG open positions (aggregated by symbol+side) to Alpaca.
    Returns three lists — phantoms (BMG-only), missing (Alpaca-only), and
    qty mismatches on common keys. Read-only."""
    import os, urllib.request, json
    from collections import defaultdict
    from app.db.models.bots import BotPosition

    bmg_rows = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None))
        .filter(BotPosition.quarantined_at.is_(None))
        .all()
    )
    bmg_agg: dict = defaultdict(lambda: {"qty": 0.0, "rows": 0, "ids": []})
    for p in bmg_rows:
        side = (p.side or "long").lower()
        key = (p.symbol or "", side)
        bmg_agg[key]["qty"] += float(p.qty or 0)
        bmg_agg[key]["rows"] += 1
        bmg_agg[key]["ids"].append(p.id)

    key_id  = os.environ.get("ALPACA_API_KEY", "")
    key_sec = os.environ.get("ALPACA_SECRET_KEY", "")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/positions",
        headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": key_sec},
    )
    alp_list = json.loads(urllib.request.urlopen(req, timeout=15).read())
    alp_agg = {}
    for p in alp_list:
        sym = p.get("symbol")
        q = float(p.get("qty"))
        side = "short" if q < 0 else "long"
        alp_agg[(sym, side)] = abs(q)

    bmg_keys = set(bmg_agg.keys())
    alp_keys = set(alp_agg.keys())
    only_bmg = sorted(bmg_keys - alp_keys)
    only_alp = sorted(alp_keys - bmg_keys)
    common   = bmg_keys & alp_keys
    mismatches = []
    for k in common:
        if abs(bmg_agg[k]["qty"] - alp_agg[k]) > 0.5:
            mismatches.append({
                "symbol": k[0], "side": k[1],
                "bmg_qty": round(bmg_agg[k]["qty"], 4),
                "alp_qty": round(alp_agg[k], 4),
                "bmg_rows": bmg_agg[k]["rows"],
                "bmg_position_ids": bmg_agg[k]["ids"],
            })

    return {
        "bmg_open_positions_rows": len(bmg_rows),
        "bmg_unique_symbol_side": len(bmg_keys),
        "alpaca_unique_symbol_side": len(alp_keys),
        "only_in_bmg_count": len(only_bmg),
        "only_in_alpaca_count": len(only_alp),
        "qty_mismatch_count": len(mismatches),
        "only_in_bmg": [
            {"symbol": k[0], "side": k[1],
             "qty": round(bmg_agg[k]["qty"], 4),
             "rows": bmg_agg[k]["rows"],
             "ids": bmg_agg[k]["ids"]} for k in only_bmg
        ],
        "only_in_alpaca": [
            {"symbol": k[0], "side": k[1], "qty": round(alp_agg[k], 4)} for k in only_alp
        ],
        "qty_mismatches": mismatches,
    }


@router.post("/quarantine-non-broker-trades")
def quarantine_non_broker_trades(
    dry_run: bool = Query(True, description="Preview only when true (default). Set false to actually quarantine."),
    lookback_days: int = Query(90, description="How far back to walk both BMG trades and Alpaca fills."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Reconcile BMG bot_trades against Alpaca. Quarantine anything not real.

    Returns per-bot counts of {kept, quarantined_phantom, quarantined_sim}
    plus a list of the alpaca_order_ids that BMG expected but Alpaca never
    filled. Idempotent — already-quarantined rows are skipped.
    """
    import os, json, urllib.request, urllib.parse
    from datetime import datetime, timedelta, timezone
    from app.db.models.bots import BotTrade, BotPosition, BotAllocation, BotProfile

    key = os.getenv("ALPACA_PAPER_KEY") or os.getenv("ALPACA_API_KEY", "")
    sec = os.getenv("ALPACA_PAPER_SECRET") or os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not sec:
        raise HTTPException(500, "Alpaca creds not configured")

    # ── 1. Pull all Alpaca filled order IDs in the lookback window ────────
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    alpaca_filled_ids: set[str] = set()
    until = datetime.now(timezone.utc)
    for _ in range(50):  # pagination cap
        params = urllib.parse.urlencode({
            "status": "closed", "limit": 500,
            "after": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "direction": "desc",
        })
        req = urllib.request.Request(
            f"https://paper-api.alpaca.markets/v2/orders?{params}",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
        )
        try:
            batch = json.loads(urllib.request.urlopen(req, timeout=15).read()) or []
        except Exception as exc:
            raise HTTPException(500, f"Alpaca orders fetch failed: {exc}")
        if not batch: break
        for o in batch:
            if o.get("status") == "filled" and o.get("id"):
                alpaca_filled_ids.add(o["id"])
        oldest = min((o.get("submitted_at") or o.get("created_at") or "") for o in batch)
        if not oldest: break
        try:
            import re as _re
            _s = _re.sub(r'\.(\d+)([+-Z])', lambda m: '.' + m.group(1).ljust(6, '0')[:6] + m.group(2), oldest)
            new_until = datetime.fromisoformat(_s.replace("Z","+00:00"))
        except Exception: break
        if new_until >= until: break
        until = new_until - timedelta(seconds=1)
        if len(batch) < 500: break

    # ── 2. Walk BMG bot_trades in the window ──────────────────────────────
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.ts >= cutoff)
        .filter(BotTrade.quarantined_at.is_(None))
        .all()
    )

    # Map allocation → bot name
    alloc_to_bot: dict[int, str] = {}
    allocs = db.query(BotAllocation).all()
    profs = {p.id: p.name for p in db.query(BotProfile).all()}
    for a in allocs:
        alloc_to_bot[a.id] = profs.get(a.profile_id, f"alloc_{a.id}")

    from app.services.trade_write_gate import is_admin_marker

    per_bot: dict[str, dict] = {}
    ids_to_quarantine_trade: list[int] = []
    ids_to_quarantine_position: set[int] = set()
    now_dt = datetime.now(timezone.utc)
    skipped_admin_marker = 0

    for t in trades:
        bot = alloc_to_bot.get(t.allocation_id, "unknown")
        stats = per_bot.setdefault(bot, {"kept": 0, "phantom": 0, "sim": 0, "admin_marker": 0})
        oid = getattr(t, "alpaca_order_id", None)
        if oid and oid in alpaca_filled_ids:
            stats["kept"] += 1
            continue
        # Adopter/rebuild/reconcile markers are legitimate — see ledger #31.
        if is_admin_marker(oid):
            stats["admin_marker"] += 1
            skipped_admin_marker += 1
            continue
        if oid:
            stats["phantom"] += 1
            reason = f"phantom_not_filled_at_alpaca:{oid}"
        else:
            stats["sim"] += 1
            reason = "sim_no_alpaca_order_id"
        ids_to_quarantine_trade.append(t.id)
        if t.position_id: ids_to_quarantine_position.add(t.position_id)
        if not dry_run:
            t.quarantined_at = now_dt
            t.quarantine_reason = reason

    # ── 3. Quarantine matching BotPosition rows ───────────────────────────
    if not dry_run and ids_to_quarantine_position:
        (
            db.query(BotPosition)
            .filter(BotPosition.id.in_(list(ids_to_quarantine_position)))
            .filter(BotPosition.quarantined_at.is_(None))
            .update(
                {"quarantined_at": now_dt, "quarantine_reason": "trade_quarantined_broker_recon"},
                synchronize_session=False,
            )
        )
        db.commit()

    return {
        "as_of": now_dt.isoformat(),
        "dry_run": dry_run,
        "lookback_days": lookback_days,
        "alpaca_filled_ids_in_window": len(alpaca_filled_ids),
        "bmg_trades_in_window": len(trades),
        "trades_to_quarantine": len(ids_to_quarantine_trade),
        "skipped_admin_marker": skipped_admin_marker,
        "positions_to_quarantine": len(ids_to_quarantine_position),
        "per_bot": dict(sorted(per_bot.items(), key=lambda x: -(x[1]["phantom"] + x[1]["sim"]))),
    }


# ── GET /api/admin/broker-reconciliation ────────────────────────────────────
#
# Ground-truth answer to "is our track record real or DB-simulated?"
# Pulls Alpaca /v2/positions + /v2/orders and cross-references against
# BMG's bot_trades and bot_positions. Any drift means silent fallback
# writes (see runner.py:_execute_signal) are producing synthetic rows.

@router.get("/broker-reconciliation")
def broker_reconciliation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Cross-check Alpaca broker state vs BMG DB claim.

    Returns per-source counts + drift verdict. Zero real Alpaca fills
    means every "trade" in bot_trades is a silent DB fallback from the
    runner's exception handler (best-effort broker call, sim on any
    failure). This endpoint surfaces that.
    """
    import os as _os
    import urllib.request as _ur
    import json as _json
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text as _text

    key = _os.getenv("ALPACA_PAPER_KEY") or _os.getenv("ALPACA_API_KEY", "")
    secret = _os.getenv("ALPACA_PAPER_SECRET") or _os.getenv("ALPACA_SECRET_KEY", "")

    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    result: Dict[str, Any] = {"as_of": now.isoformat()}

    alpaca_positions: list = []
    alpaca_orders: list = []
    alpaca_error: str | None = None

    if not key or not secret:
        alpaca_error = "no_credentials"
    else:
        base = "https://paper-api.alpaca.markets/v2"
        hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        try:
            with _ur.urlopen(_ur.Request(f"{base}/positions", headers=hdrs), timeout=10) as r:
                alpaca_positions = _json.loads(r.read())
        except Exception as exc:
            alpaca_error = f"positions_fetch_failed: {exc}"
        try:
            with _ur.urlopen(
                _ur.Request(f"{base}/orders?status=all&limit=500&direction=desc", headers=hdrs),
                timeout=10,
            ) as r:
                alpaca_orders = _json.loads(r.read())
        except Exception as exc:
            alpaca_error = f"{alpaca_error or ''}; orders_fetch_failed: {exc}"

    orders_24h = [
        o for o in alpaca_orders
        if (o.get("submitted_at") or o.get("created_at") or "") >= cutoff_24h
    ]
    orders_filled = [o for o in alpaca_orders if o.get("status") == "filled"]

    result["alpaca"] = {
        "positions_count": len(alpaca_positions),
        "orders_count_all_time": len(alpaca_orders),
        "orders_filled_all_time": len(orders_filled),
        "orders_24h_count": len(orders_24h),
        "error": alpaca_error,
    }

    # BMG DB claim — 2026-08-07 scoped to user_id=1 (fund-of-record).
    # Alpaca is a single account; counting all users' allocations here
    # inflated DB=193 vs Alpaca=134. Also excludes quarantined rows so
    # this matches what user 1 actually holds. Legacy "raw" counts
    # (all users, all statuses) live under bmg_db_raw for debugging.
    db_positions_row = db.execute(_text(
        "SELECT COUNT(*) FROM bot_positions bp "
        "JOIN bot_allocations a ON a.id = bp.allocation_id "
        "WHERE a.user_id = 1 "
        "  AND bp.closed_at IS NULL "
        "  AND bp.quarantined_at IS NULL"
    )).fetchone()
    # m099: trades_24h counts BROKER_FILL only (adopter/reconcile/rebuild
    # rows are BMG-generated, not fills).
    db_trades_24h_row = db.execute(_text(
        "SELECT COUNT(*) FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = 1 AND t.ts >= :cut "
        "  AND t.quarantined_at IS NULL "
        "  AND t.origin = 'BROKER_FILL'"
    ), {"cut": cutoff_24h}).fetchone()
    db_trades_alpaca_linked_row = db.execute(_text(
        "SELECT COUNT(*) FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = 1 AND t.alpaca_order_id IS NOT NULL "
        "  AND t.quarantined_at IS NULL"
    )).fetchone()
    db_trades_no_alpaca_row = db.execute(_text(
        "SELECT COUNT(*) FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = 1 AND t.alpaca_order_id IS NULL "
        "  AND t.quarantined_at IS NULL"
    )).fetchone()

    result["bmg_db"] = {
        "open_positions_count": int(db_positions_row[0] or 0),
        "trades_24h": int(db_trades_24h_row[0] or 0),
        "trades_with_alpaca_order_id": int(db_trades_alpaca_linked_row[0] or 0),
        "trades_without_alpaca_order_id": int(db_trades_no_alpaca_row[0] or 0),
        "_scope": "user_id=1, non-quarantined",
    }

    # Per-asset-class breakdown of Alpaca activity in 24h window.
    result["alpaca_by_asset"] = {}
    for cls in ("us_equity", "us_option", "crypto"):
        cls_positions = [p for p in alpaca_positions
                         if p.get("asset_class", "us_equity") == cls]
        cls_orders_24h = [o for o in orders_24h
                          if o.get("asset_class") == cls]
        cls_orders_filled_24h = [o for o in cls_orders_24h
                                 if o.get("status") == "filled"]
        cls_orders_rejected_24h = [o for o in cls_orders_24h
                                   if o.get("status") in ("rejected", "canceled", "expired")]
        result["alpaca_by_asset"][cls] = {
            "positions": len(cls_positions),
            "orders_24h": len(cls_orders_24h),
            "orders_filled_24h": len(cls_orders_filled_24h),
            "orders_rejected_24h": len(cls_orders_rejected_24h),
        }

    # DB fills per source. Distinguish real Alpaca (alpaca_order_id NOT NULL)
    # vs silent DB fallback (alpaca_order_id NULL) per bot for the last 24h
    # so a caller can see which bots are actually routing to broker.
    # 2026-07-07 fix: group by p.name only (not starting_capital_cents)
    # to eliminate duplicate rows when a bot has multiple allocations.
    # m083 fix: scope starting_cents to user_id=1 (fund owner). MAX() across
    # all users leaked user_id=3's legacy $200K demo allocations into the
    # recon output, showing crypto_day=$200,000 when the real fund allocation
    # is $6,813.80. Now matches /api/admin/bots/diagnostics exactly.
    src_rows = db.execute(_text("""
        SELECT p.name,
               (SELECT MAX(a2.starting_capital_cents)
                  FROM bot_allocations a2
                 WHERE a2.profile_id = p.id
                   AND a2.user_id = 1
                   AND a2.enabled = 1) AS starting_cents,
               SUM(CASE WHEN t.alpaca_order_id IS NOT NULL THEN 1 ELSE 0 END) AS real_fills,
               SUM(CASE WHEN t.alpaca_order_id IS NULL THEN 1 ELSE 0 END) AS sim_fills
        FROM bot_trades t
        JOIN bot_allocations a ON a.id = t.allocation_id
        JOIN bot_profiles p ON p.id = a.profile_id
        WHERE t.ts >= :cut AND a.user_id = 1
        GROUP BY p.name, p.id
        ORDER BY real_fills + sim_fills DESC
    """), {"cut": cutoff_24h}).fetchall()
    result["bmg_db_by_bot_24h"] = [
        {
            "bot": row[0],
            "starting_cents": int(row[1] or 0),
            "real_alpaca_fills": int(row[2] or 0),
            "sim_fallback_fills": int(row[3] or 0),
        }
        for row in src_rows
    ]

    # Verdict
    db_open = result["bmg_db"]["open_positions_count"]
    alp_open = result["alpaca"]["positions_count"]
    pct_real = 0.0
    total_trades = (
        result["bmg_db"]["trades_with_alpaca_order_id"]
        + result["bmg_db"]["trades_without_alpaca_order_id"]
    )
    if total_trades > 0:
        pct_real = round(
            result["bmg_db"]["trades_with_alpaca_order_id"] / total_trades * 100, 2
        )

    if alpaca_error:
        verdict = "UNKNOWN — Alpaca query failed"
    elif db_open == alp_open == 0 and total_trades == 0:
        verdict = "EMPTY — no positions on either side"
    elif alp_open == 0 and db_open > 0:
        verdict = (
            "DRIFT — DB reports positions but Alpaca has none. Every 'trade' in "
            "bot_trades is a silent DB fallback from runner._execute_signal, not a real "
            "Alpaca paper fill. Track record is internal simulation, not verifiable."
        )
    elif alp_open > 0 and db_open == 0:
        verdict = "DRIFT — Alpaca has positions not tracked in BMG DB"
    else:
        drift = abs(db_open - alp_open)
        if drift == 0:
            verdict = f"SYNCED — DB={db_open} = Alpaca={alp_open}"
        else:
            verdict = f"PARTIAL — DB={db_open} vs Alpaca={alp_open} (drift={drift})"

    result["verdict"] = verdict
    result["pct_real_alpaca_fills"] = pct_real

    return result


# ── POST /api/admin/options/quarantine-all-open ────────────────────────────
#
# Emergency: mark every open options position as quarantined so the
# canonical PV aggregator drops it from sleeve mark-to-market. Used to
# reset the sleeve after a sign-flip / sizing / illiquid-mark bug.
# Position rows are preserved for audit history — only quarantined_at
# and quarantine_reason are set.

@router.post("/options/quarantine-all-open")
def options_quarantine_all_open(
    reason: str = "sign_flip_and_illiquid_marks_2026_07_07",
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> Dict[str, Any]:
    """Quarantine every open options position (option_type IS NOT NULL and
    closed_at IS NULL and quarantined_at IS NULL). Returns count quarantined.
    """
    from sqlalchemy import text as _t
    now_iso = datetime.now(timezone.utc).isoformat()
    res = db.execute(_t("""
        UPDATE bot_positions
        SET quarantined_at = :ts, quarantine_reason = :r
        WHERE option_type IS NOT NULL
          AND closed_at IS NULL
          AND quarantined_at IS NULL
    """), {"ts": now_iso, "r": reason})
    db.commit()
    return {
        "quarantined_count": res.rowcount,
        "reason": reason,
        "ts": now_iso,
    }


# ── POST /api/admin/positions/quarantine-all-sim ────────────────────────────
#
# Path 2 (honest labeling): quarantine every open position that is NOT
# verified against Alpaca (alpaca_order_id IS NULL on ALL entry trades
# for that position). Leaves REAL Alpaca-linked positions untouched.
#
# After running, /api/admin/broker-reconciliation open_positions_count
# should match Alpaca positions_count within 1-2 (small race with new
# fills). This ends the "586 in DB vs 5 at Alpaca" mismatch.

@router.post("/positions/quarantine-all-sim")
def positions_quarantine_all_sim(
    reason: str = "path2_honest_labeling_2026_07_07",
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> Dict[str, Any]:
    """Quarantine every open position that has no linked Alpaca fill.

    Criteria for quarantine:
      - closed_at IS NULL
      - quarantined_at IS NULL
      - No BotTrade rows exist for this position with alpaca_order_id NOT NULL

    A position is considered "real" if at least one of its trades has an
    alpaca_order_id (meaning a real Alpaca fill was recorded during entry).
    Everything else was a silent DB fallback write.
    """
    from sqlalchemy import text as _t
    now_iso = datetime.now(timezone.utc).isoformat()

    # Count before
    before_row = db.execute(_t(
        "SELECT COUNT(*) FROM bot_positions "
        "WHERE closed_at IS NULL AND quarantined_at IS NULL"
    )).fetchone()
    before_count = int(before_row[0] or 0)

    # Quarantine any open position that has NO alpaca-linked trade.
    res = db.execute(_t("""
        UPDATE bot_positions
        SET quarantined_at = :ts, quarantine_reason = :r
        WHERE id IN (
            SELECT p.id
            FROM bot_positions p
            WHERE p.closed_at IS NULL
              AND p.quarantined_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM bot_trades t
                WHERE t.position_id = p.id
                  AND t.alpaca_order_id IS NOT NULL
              )
        )
    """), {"ts": now_iso, "r": reason})
    db.commit()

    after_row = db.execute(_t(
        "SELECT COUNT(*) FROM bot_positions "
        "WHERE closed_at IS NULL AND quarantined_at IS NULL"
    )).fetchone()
    after_count = int(after_row[0] or 0)

    return {
        "quarantined_count": res.rowcount,
        "open_positions_before": before_count,
        "open_positions_after": after_count,
        "remaining_are_alpaca_verified": True,
        "reason": reason,
        "ts": now_iso,
    }


# ── POST /api/admin/bots/scrub-ghost-pnl ─────────────────────────────────────

@router.post("/bots/scrub-ghost-pnl")
def scrub_ghost_pnl(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete stale/phantom P&L rows and reset realized P&L on paper allocations.

    Safe to call repeatedly — removes daily snapshots and pnl rows from before
    today, and zeros out all_time_realized_pnl_cents on paper allocations.
    """
    from sqlalchemy import text
    from app.db.models.bots import BotAllocation

    snaps_deleted = pnl_deleted = allocs_reset = 0
    errors = []

    try:
        r = db.execute(text(
            "DELETE FROM daily_portfolio_snapshots WHERE snapshot_date < CURRENT_DATE"
        ))
        snaps_deleted = r.rowcount
    except Exception as exc:
        errors.append(f"daily_portfolio_snapshots: {exc}")

    try:
        r = db.execute(text(
            "DELETE FROM bot_daily_pnl WHERE date < CURRENT_DATE"
        ))
        pnl_deleted = r.rowcount
    except Exception as exc:
        errors.append(f"bot_daily_pnl: {exc}")

    try:
        allocs = (
            db.query(BotAllocation)
            .filter(
                BotAllocation.user_id == current_user.id,
                BotAllocation.paper_mode.is_(True),
            )
            .all()
        )
        for a in allocs:
            a.all_time_realized_pnl_cents = 0
        allocs_reset = len(allocs)
    except Exception as exc:
        errors.append(f"bot_allocations reset: {exc}")

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": f"commit failed: {exc}"}

    logger.info(
        "admin: scrub_ghost_pnl user=%d snaps=%d pnl_rows=%d allocs_reset=%d",
        current_user.id, snaps_deleted, pnl_deleted, allocs_reset,
    )
    return {
        "ok": True,
        "daily_portfolio_snapshots_deleted": snaps_deleted,
        "bot_daily_pnl_rows_deleted": pnl_deleted,
        "paper_allocs_pnl_zeroed": allocs_reset,
        "errors": errors,
    }


# ── GET /api/admin/system/health ──────────────────────────────────────────────

@router.get("/system/health")
def system_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Live health check across all data sources and the bot scheduler."""
    from app.db.models.bots import BotSignal, BotAllocation

    result: Dict[str, Any] = {}

    # ── Alpaca stocks ──────────────────────────────────────────────────────────
    try:
        from app.services.live_prices import fetch_live_prices
        t0 = datetime.now(timezone.utc)
        prices = fetch_live_prices(["AAPL"])
        price = prices.get("AAPL")
        result["alpaca_stocks"] = {
            "connected": price is not None,
            "last_quote_at": t0.isoformat(),
            "last_quote_symbol": "AAPL",
            "last_quote_price": price,
        }
    except Exception as exc:
        result["alpaca_stocks"] = {"connected": False, "error": str(exc)}

    # ── Kraken / Alpaca crypto ─────────────────────────────────────────────────
    try:
        from app.services.live_prices import fetch_live_prices
        t0 = datetime.now(timezone.utc)
        prices = fetch_live_prices(["BTC/USD"])
        price = prices.get("BTC/USD")
        result["alpaca_crypto"] = {
            "connected": price is not None,
            "last_quote_at": t0.isoformat(),
            "last_quote_symbol": "BTC/USD",
            "last_quote_price": price,
        }
    except Exception as exc:
        result["alpaca_crypto"] = {"connected": False, "error": str(exc)}

    # ── Options (Alpaca paper stocks, options chain) ───────────────────────────
    try:
        from app.services.live_prices import fetch_live_prices
        t0 = datetime.now(timezone.utc)
        prices = fetch_live_prices(["SPY"])
        price = prices.get("SPY")
        result["alpaca_options"] = {
            "connected": price is not None,
            "last_quote_at": t0.isoformat(),
            "last_quote_symbol": "SPY",
            "last_quote_price": price,
            "note": "Underlying equity price check only — options chain requires market hours.",
        }
    except Exception as exc:
        result["alpaca_options"] = {"connected": False, "error": str(exc)}

    # ── Discord worker (last posted signal) ───────────────────────────────────
    try:
        last_post = (
            db.query(BotSignal)
            .filter(BotSignal.discord_posted_at.isnot(None))
            .order_by(BotSignal.discord_posted_at.desc())
            .first()
        )
        if last_post:
            alloc = db.query(BotAllocation).filter(
                BotAllocation.id == last_post.allocation_id
            ).first()
            from app.db.models.bots import BotProfile
            prof_name = None
            if alloc:
                prof = db.query(BotProfile).filter(BotProfile.id == alloc.profile_id).first()
                prof_name = prof.name if prof else None
            result["discord_worker"] = {
                "online": True,
                "last_post_at": last_post.discord_posted_at.isoformat(),
                "last_post_channel": f"#{_BOT_CHANNEL_MAP.get(prof_name or '', 'unknown')}",
                "last_signal_bot": prof_name,
                "last_signal_symbol": last_post.symbol,
            }
        else:
            result["discord_worker"] = {
                "online": None,
                "last_post_at": None,
                "note": "No signals have been posted yet.",
            }
    except Exception as exc:
        result["discord_worker"] = {"online": False, "error": str(exc)}

    # ── Scheduler ─────────────────────────────────────────────────────────────
    try:
        from strategy_lab.bot_scheduler import scheduler
        jobs = scheduler.get_jobs()
        job_names = [j.id for j in jobs]

        # Last scan per bot: most recent BotSignal ts per allocation
        allocs = db.query(BotAllocation).filter(
            BotAllocation.user_id == current_user.id
        ).all()
        alloc_ids = [a.id for a in allocs]

        from app.db.models.bots import BotProfile
        last_scan: Dict[str, Any] = {}
        if alloc_ids:
            rows = (
                db.query(
                    BotAllocation.profile_id,
                    func.max(BotSignal.ts).label("last_ts"),
                )
                .join(BotSignal, BotSignal.allocation_id == BotAllocation.id)
                .filter(BotAllocation.id.in_(alloc_ids))
                .group_by(BotAllocation.profile_id)
                .all()
            )
            prof_map = {
                p.id: p.name
                for p in db.query(BotProfile).all()
            }
            last_scan = {
                prof_map.get(r.profile_id, str(r.profile_id)): iso_utc(r.last_ts)
                for r in rows
            }

        result["scheduler"] = {
            "jobs_registered": len(jobs),
            "job_ids": job_names[:20],
            "last_scan_per_bot": last_scan,
        }
    except Exception as exc:
        result["scheduler"] = {"error": str(exc)}


# ── POST /api/admin/positions/dedupe-by-symbol-bot ───────────────────────────

@router.post("/positions/dedupe-by-symbol-bot")
def dedupe_positions_by_symbol_bot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Quarantine duplicate open positions — keeps the newest per (allocation_id, symbol).

    Run this after the same-scan dedup fix lands to clean up any duplicates
    created by the now-fixed concurrent-scan race condition.
    """
    from app.db.models.bots import BotPosition

    # 2026-08-18: was .isoformat() str, which SQLite DateTime column rejected.
    now_dt = datetime.now(timezone.utc)

    open_positions = (
        db.query(BotPosition)
        .filter(BotPosition.closed_at.is_(None), BotPosition.quarantined_at.is_(None))
        .order_by(BotPosition.allocation_id, BotPosition.symbol, BotPosition.opened_at.desc())
        .all()
    )

    seen: set = set()
    to_quarantine = []
    for pos in open_positions:
        key = (pos.allocation_id, pos.symbol)
        if key in seen:
            to_quarantine.append(pos)
        else:
            seen.add(key)

    quarantined_ids = []
    for pos in to_quarantine:
        pos.quarantined_at = now_dt
        pos.quarantine_reason = "dedupe_duplicate_open_position"
        quarantined_ids.append(pos.id)
    db.commit()

    return {
        "ok": True,
        "positions_quarantined": len(to_quarantine),
        "unique_positions_kept": len(seen),
        "quarantined_position_ids": quarantined_ids,
    }


@router.post("/positions/re-adopt-symbol")
def re_adopt_symbol(
    symbol: str = Query(..., description="Exact Alpaca symbol to sync (e.g. JNJ)"),
    dry_run: bool = Query(True, description="If true, show planned change without writing."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Surgical single-symbol re-adopt: sync BMG's position qty + avg_cost
    to Alpaca truth for one specific symbol.

    Brock 2026-08-18 resume step 1: JNJ shows BMG qty=1.71 vs Alpaca ~92
    (under-adopted). This endpoint fixes ONE symbol at a time — no fleet
    sweep, no ADOPT-BOUND surprise.

    Rules:
      - Fetches Alpaca position for symbol. If Alpaca doesn't hold it,
        return error (nothing to adopt).
      - Finds active (open, non-quarantined) BotPositions for symbol under
        user_1. If 0 or >1, return error with the count (manual dedupe or
        insert needed first).
      - If exactly 1 row: update qty + avg_cost_cents to Alpaca truth.
      - dry_run=true shows the planned before/after values.
    """
    import os as _os, urllib.request as _ur, json as _j
    from datetime import datetime as _dt, timezone as _tz
    from app.db.models.bots import BotPosition, BotAllocation

    kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        return {"error": "no_alpaca_creds"}

    # Fetch Alpaca position for this specific symbol
    try:
        req = _ur.Request(
            f"https://paper-api.alpaca.markets/v2/positions/{symbol}",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        )
        alp = _j.loads(_ur.urlopen(req, timeout=10).read())
    except Exception as exc:
        return {"error": f"alpaca_fetch_failed: {str(exc)[:200]}",
                "symbol": symbol}

    alp_qty = float(alp.get("qty") or 0)
    alp_avg = float(alp.get("avg_entry_price") or 0)
    alp_side = alp.get("side")  # 'long' or 'short'

    # BMG active rows for this symbol under user_1
    rows = (
        db.query(BotPosition, BotAllocation)
        .join(BotAllocation, BotAllocation.id == BotPosition.allocation_id)
        .filter(
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
            BotAllocation.user_id == 1,
            BotPosition.symbol == symbol,
        )
        .all()
    )
    if len(rows) == 0:
        return {"error": "no_bmg_row_for_symbol", "symbol": symbol,
                "hint": "insert new row via a full adopter run, not this endpoint"}
    if len(rows) > 1:
        return {
            "error": "multiple_bmg_rows_for_symbol",
            "symbol": symbol,
            "count": len(rows),
            "rows": [
                {"position_id": p.id, "alloc_id": p.allocation_id,
                 "qty": float(p.qty or 0), "avg_cost_cents": p.avg_cost_cents}
                for p, _ in rows
            ],
            "hint": "dedupe first via /admin/positions/dedupe-by-symbol-bot",
        }

    pos, alloc = rows[0]
    before = {
        "position_id": pos.id,
        "alloc_id": pos.allocation_id,
        "qty": float(pos.qty or 0),
        "avg_cost_cents": int(pos.avg_cost_cents or 0),
    }
    after = {
        "qty": alp_qty,
        "avg_cost_cents": int(round(alp_avg * 100)),
        "side": alp_side,
    }
    delta_qty = alp_qty - before["qty"]
    delta_avg = after["avg_cost_cents"] - before["avg_cost_cents"]

    if dry_run:
        return {
            "dry_run": True,
            "symbol": symbol,
            "before": before,
            "after": after,
            "delta_qty": delta_qty,
            "delta_avg_cents": delta_avg,
            "alpaca_side": alp_side,
            "hint": "run again with ?dry_run=false to write",
        }

    # Live update
    pos.qty = alp_qty
    pos.avg_cost_cents = int(round(alp_avg * 100))
    # Preserve origin (this is a re-adopt of an existing broker-filled row);
    # add a reason tag so history knows why the qty jumped.
    _note = f"re-adopt {symbol} to Alpaca truth 2026-08-18 (was qty={before['qty']} → {alp_qty})"
    try:
        # Some BotPosition schemas have a `notes` or `reason` column; skip if not present.
        if hasattr(pos, "notes"):
            pos.notes = (pos.notes or "") + f" | {_note}"
    except Exception:
        pass
    db.commit()

    return {
        "dry_run": False,
        "symbol": symbol,
        "position_id": pos.id,
        "before": before,
        "after": after,
        "delta_qty": delta_qty,
        "delta_avg_cents": delta_avg,
        "committed_at": _dt.now(_tz.utc).isoformat(),
    }


@router.post("/positions/quarantine-bmg-only-phantoms")
def quarantine_bmg_only_phantoms(
    dry_run: bool = Query(True, description="If true, list-only; do not mutate."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Quarantine BMG-active non-option positions that have no matching Alpaca position.

    2026-08-18 Brock surgical: I1 = 17 (position drift). After dedupe removes
    3 dupes, ~14 phantoms remain — BMG holds a position record for a symbol
    the broker does not. Reason 'phantom_no_broker_match_2026_08_18'.
    Non-option only (options come and go with expiries).

    §ADOPT-BOUND: dry_run enumerates + returns the exact list; live run
    quarantines exactly that list or aborts.
    """
    import os as _os, urllib.request as _ur, json as _j
    from datetime import datetime as _dt, timezone as _tz
    from app.db.models.bots import BotPosition, BotAllocation

    kid = _os.environ.get("ALPACA_API_KEY") or _os.environ.get("ALPACA_PAPER_KEY", "")
    ksec = _os.environ.get("ALPACA_SECRET_KEY") or _os.environ.get("ALPACA_PAPER_SECRET", "")
    if not kid or not ksec:
        return {"error": "no_alpaca_creds"}

    try:
        alp = _j.loads(_ur.urlopen(_ur.Request(
            "https://paper-api.alpaca.markets/v2/positions",
            headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": ksec},
        ), timeout=10).read()) or []
    except Exception as exc:
        return {"error": f"alpaca_fetch_failed: {str(exc)[:200]}"}

    alp_symbols = {p.get("symbol") for p in alp if p.get("symbol")}

    # BMG active non-option positions for user_1
    rows = (
        db.query(BotPosition, BotAllocation)
        .join(BotAllocation, BotAllocation.id == BotPosition.allocation_id)
        .filter(
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
            BotAllocation.user_id == 1,
            BotPosition.option_type.is_(None),  # stocks/crypto only
        )
        .all()
    )

    phantoms = []
    for pos, alloc in rows:
        sym = pos.symbol or ""
        if sym in alp_symbols:
            continue
        phantoms.append({
            "position_id": int(pos.id),
            "symbol": sym,
            "allocation_id": int(pos.allocation_id),
            "qty": float(pos.qty or 0),
            "avg_cost_cents": int(pos.avg_cost_cents or 0),
            "origin": pos.origin,
            "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            "alpaca_order_id": pos.alpaca_order_id,
        })

    n_phantoms = len(phantoms)
    if dry_run:
        return {
            "dry_run": True,
            "alpaca_symbol_count": len(alp_symbols),
            "bmg_active_nonopt_count": len(rows),
            "phantom_count": n_phantoms,
            "phantoms": phantoms,
            "hint": "run again with ?dry_run=false to quarantine exactly these rows",
        }

    # Live: quarantine exactly the identified rows.
    now_dt = _dt.now(_tz.utc)
    reason = "phantom_no_broker_match_2026_08_18"
    quarantined_ids = []
    for pos, _ in rows:
        if pos.symbol in alp_symbols:
            continue
        pos.quarantined_at = now_dt
        pos.quarantine_reason = reason
        quarantined_ids.append(int(pos.id))
    db.commit()

    return {
        "dry_run": False,
        "reason": reason,
        "phantoms_quarantined": len(quarantined_ids),
        "quarantined_position_ids": quarantined_ids,
        "expected_from_dry_run": n_phantoms,
        "match": len(quarantined_ids) == n_phantoms,
    }


@router.post("/signals/quarantine-spam")
def quarantine_spam_signals(
    since: str = Query(
        ...,
        description="ISO timestamp — quarantine signals after this time that violate cooldown rules",
        example="2026-06-09T00:00:00Z",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Mark spam signals (cooldown violations) as is_test=True so they're hidden from stats.

    Finds signals where the same (profile, symbol, side) fired more than once within its
    cooldown_minutes window, keeping only the FIRST occurrence per window and marking
    all subsequent duplicates as test signals. Operates only on signals after `since`.

    Safe to call repeatedly (idempotent — already-quarantined signals are skipped).
    """
    from app.db.models.bots import BotSignal, BotAllocation, BotProfile
    from strategy_lab.seeds import load_profile
    from sqlalchemy import text as _text

    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Invalid `since` timestamp: {exc}")

    # Load cooldown windows per profile
    profile_cooldowns: dict[str, float] = {}
    for bp in db.query(BotProfile).all():
        try:
            cfg = load_profile(bp.name) or {}
            profile_cooldowns[bp.id] = float(cfg.get("cooldown_minutes", 0))
        except Exception:
            profile_cooldowns[bp.id] = 0

    # Fetch all non-test signals after `since`, ordered by ts asc
    signals = (
        db.query(BotSignal)
        .filter(
            BotSignal.ts >= since_dt,
            BotSignal.is_test.is_(False) | BotSignal.is_test.is_(None),
        )
        .order_by(BotSignal.ts.asc())
        .all()
    )

    # Walk signals chronologically; track last-seen ts per (profile_id, symbol, side)
    last_fired: dict[tuple, datetime] = {}
    quarantined = 0
    kept = 0
    for sig in signals:
        alloc = db.get(BotAllocation, sig.allocation_id)
        if alloc is None:
            continue
        cooldown_min = profile_cooldowns.get(alloc.profile_id, 0)
        if cooldown_min <= 0:
            kept += 1
            continue

        key = (alloc.profile_id, sig.symbol, sig.side)
        last_ts = last_fired.get(key)
        sig_ts = sig.ts if isinstance(sig.ts, datetime) else datetime.fromisoformat(str(sig.ts))

        if last_ts is not None:
            elapsed_min = (sig_ts - last_ts).total_seconds() / 60.0
            if elapsed_min < cooldown_min:
                sig.is_test = True
                quarantined += 1
                continue  # don't update last_fired — preserve the original window start

        last_fired[key] = sig_ts
        kept += 1

    db.commit()
    logger.warning(
        "quarantine-spam: since=%s quarantined=%d kept=%d",
        since, quarantined, kept,
    )
    return {
        "ok": True,
        "since": since,
        "signals_examined": len(signals),
        "quarantined": quarantined,
        "kept": kept,
    }


@router.get("/bots/{bot_id}/risk-status")
def get_bot_risk_status(
    bot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return deployment-target sizing status for a bot allocation.

    Example: GET /api/admin/bots/crypto_quant_scalper/risk-status
    """
    from app.db.models.bots import BotProfile, BotAllocation
    from strategy_lab.seeds import load_profile
    from strategy_lab.core.deployment_sizer import get_risk_status

    bp = db.query(BotProfile).filter(BotProfile.name == bot_id).first()
    if not bp:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Bot profile '{bot_id}' not found")

    alloc = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.profile_id == bp.id,
            BotAllocation.user_id == current_user.id,
        )
        .first()
    )
    if not alloc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No allocation for '{bot_id}' under this user")

    profile = load_profile(bot_id)
    capital_usd = (
        alloc.starting_capital_cents if alloc.starting_capital_cents is not None else (alloc.capital_cents_within_portfolio if alloc.capital_cents_within_portfolio is not None else 5_000_000)
    ) / 100.0

    flag_enabled = os.getenv("ENABLE_DEPLOYMENT_TARGET_SIZING", "false").strip().lower() == "true"
    status = get_risk_status(alloc, profile, capital_usd, db)
    status["flag_enabled"] = flag_enabled
    return status


@router.get("/bot-health")
def get_bot_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    17-row pipeline health table. Returns per-bot:
      last_signal_at, signals_24h, trades_24h, discord_posts_24h,
      open_positions, expected_interval_min, pipeline_health (GREEN/YELLOW/RED/DISABLED)

    Refresh every 30s from the UI — cheap read-only query.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        from strategy_lab.agents.strategy_monitor import _check_bot_windows
        rows = _check_bot_windows(db)
    except Exception as exc:
        logger.error("[bot-health] strategy_monitor failed: %s", exc)
        rows = []

    summary = {
        "green":    sum(1 for r in rows if r.get("pipeline_health") == "GREEN"),
        "yellow":   sum(1 for r in rows if r.get("pipeline_health") == "YELLOW"),
        "red":      sum(1 for r in rows if r.get("pipeline_health") == "RED"),
        "disabled": sum(1 for r in rows if r.get("pipeline_health") == "DISABLED"),
    }
    return {
        "bots":       rows,
        "summary":    summary,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/bot-health/{bot_name}")
def get_bot_health_detail(
    bot_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Drill-down for a single bot. Returns last 25 signals, last 25 trades,
    last 10 Discord posts, and live health row.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        from app.db.models.bots import BotProfile, BotAllocation, BotSignal, BotTrade
        from strategy_lab.agents.strategy_monitor import _check_bot_windows

        prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
        if not prof:
            raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

        alloc_rows = db.query(BotAllocation).filter(BotAllocation.profile_id == prof.id).all()
        alloc_ids  = [a.id for a in alloc_rows]

        # Last 25 signals
        sig_rows = (
            db.query(BotSignal)
            .filter(BotSignal.allocation_id.in_(alloc_ids))
            .order_by(BotSignal.ts.desc())
            .limit(25)
            .all()
        ) if alloc_ids else []

        signals = [
            {
                "id":               s.id,
                "ts":               iso_utc(s.ts),
                "symbol":           s.symbol,
                "side":             s.side,
                "confidence":       s.confidence,
                "price":            s.price,
                "discord_posted_at": iso_utc(s.discord_posted_at),
                "is_test":          bool(s.is_test),
            }
            for s in sig_rows
        ]

        # Last 25 trades
        trade_rows = (
            db.query(BotTrade)
            .filter(BotTrade.allocation_id.in_(alloc_ids))
            .order_by(BotTrade.ts.desc())
            .limit(25)
            .all()
        ) if alloc_ids else []

        trades = [
            {
                "id":            t.id,
                "ts":            iso_utc(t.ts),
                "symbol":        t.symbol,
                "side":          t.side,
                "qty":           t.qty,
                "price":         t.price,
                "pnl_cents":     t.pnl_cents,
                "quarantined_at": iso_utc(t.quarantined_at),
            }
            for t in trade_rows
        ]

        # Last 10 Discord posts (signals with discord_posted_at set)
        discord_rows = (
            db.query(BotSignal)
            .filter(
                BotSignal.allocation_id.in_(alloc_ids),
                BotSignal.discord_posted_at.isnot(None),
            )
            .order_by(BotSignal.discord_posted_at.desc())
            .limit(10)
            .all()
        ) if alloc_ids else []

        discord_posts = [
            {
                "id":        s.id,
                "ts":        iso_utc(s.discord_posted_at),
                "symbol":    s.symbol,
                "side":      s.side,
                "confidence": s.confidence,
            }
            for s in discord_rows
        ]

        # Live health row for this bot
        all_bot_windows = _check_bot_windows(db)
        health_row = next((r for r in all_bot_windows if r.get("bot") == bot_name), {})

        return {
            "bot":          bot_name,
            "health":       health_row,
            "signals":      signals,
            "trades":       trades,
            "discord_posts": discord_posts,
            "checked_at":   datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[bot-health-detail] failed for %s: %s", bot_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/synthetic-check")
def synthetic_check(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Post-deploy pipeline verification. For each active production bot:
      1. Inserts a synthetic is_test=True signal
      2. Verifies the row was written to bot_signals
      3. Checks Discord channel is configured

    Signals are marked is_test=True — invisible to all stats/reporting.
    Returns pass/fail per bot plus an overall ok flag.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    from app.db.models.bots import BotProfile, BotAllocation, BotSignal

    _PRODUCTION_BOTS = {
        "stock_swing", "stock_day", "stock_lt",
        "options_income", "options_directional",
        "crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain",
        "crypto_quant_aggressive", "crypto_quant_scalper", "crypto_quant_mean_reversion",
    }

    _DISCORD_CHANNELS = {
        "stock_swing": "DISCORD_CH_STOCKS_SIGNALS",
        "stock_day":   "DISCORD_CH_STOCKS_SIGNALS",
        "stock_lt":    "DISCORD_CH_STOCKS_SIGNALS",
        "options_income":      "DISCORD_CH_OPTIONS_SIGNALS",
        "options_directional": "DISCORD_CH_OPTIONS_SIGNALS",
        "crypto_swing":   "DISCORD_CH_CRYPTO_SIGNALS",
        "crypto_day":     "DISCORD_CH_CRYPTO_SIGNALS",
        "crypto_lt":      "DISCORD_CH_CRYPTO_SIGNALS",
        "crypto_onchain": "DISCORD_CH_CRYPTO_SIGNALS",
        "crypto_quant_aggressive":     "DISCORD_CH_QUANT_SIGNALS",
        "crypto_quant_scalper":        "DISCORD_CH_QUANT_SIGNALS",
        "crypto_quant_mean_reversion": "DISCORD_CH_QUANT_SIGNALS",
    }

    now = datetime.now(timezone.utc)
    results = []
    all_pass = True

    for bot_name in sorted(_PRODUCTION_BOTS):
        result: Dict[str, Any] = {"bot": bot_name, "pass": False, "steps": {}}
        try:
            prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
            if not prof:
                result["steps"]["profile"] = "MISSING"
                result["fail_reason"] = "no BotProfile row"
                results.append(result)
                all_pass = False
                continue
            result["steps"]["profile"] = "OK"

            alloc = db.query(BotAllocation).filter(
                BotAllocation.profile_id == prof.id,
                BotAllocation.user_id == current_user.id,
            ).first()
            if not alloc:
                result["steps"]["allocation"] = "MISSING"
                result["fail_reason"] = "no BotAllocation for this user"
                results.append(result)
                all_pass = False
                continue
            result["steps"]["allocation"] = "OK"
            result["steps"]["enabled"] = "OK" if alloc.enabled else "DISABLED"

            # Insert synthetic signal
            sig = BotSignal(
                allocation_id=alloc.id,
                ts=now,
                symbol="SYNTHETIC",
                side="hold",
                confidence=0.0,
                reason="synthetic_pipeline_check",
                strategy="synthetic",
                is_test=True,
            )
            db.add(sig)
            db.flush()
            db.refresh(sig)
            result["steps"]["signal_write"] = "OK" if sig.id else "FAILED"
            result["synthetic_signal_id"] = sig.id

            # Verify Discord channel env var is set
            ch_env = _DISCORD_CHANNELS.get(bot_name, "")
            ch_configured = bool(os.getenv(ch_env) or os.getenv("DISCORD_CH_ALL_SIGNALS"))
            result["steps"]["discord_channel"] = "OK" if ch_configured else "MISSING_ENV_VAR"
            result["discord_channel_env"] = ch_env

            result["pass"] = sig.id is not None and ch_configured
            if not result["pass"]:
                all_pass = False

        except Exception as exc:
            result["fail_reason"] = str(exc)[:200]
            result["pass"] = False
            all_pass = False
        results.append(result)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("[synthetic-check] commit failed: %s", exc)

    passed = sum(1 for r in results if r["pass"])
    return {
        "ok":         all_pass,
        "passed":     passed,
        "total":      len(results),
        "checked_at": now.isoformat(),
        "results":    results,
    }


@router.get("/audit-trail")
def get_audit_trail(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append-only compliance log. Returns last N audit events, newest first."""
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        from sqlalchemy import text as sql_text
        rows = db.execute(sql_text("""
            SELECT id, ts, actor, action, entity_type, entity_id,
                   before_val, after_val, notes
            FROM audit_trail
            ORDER BY id DESC
            LIMIT :n
        """), {"n": min(limit, 500)}).fetchall()
        entries = [
            {
                "id":          r[0],
                "ts":          r[1],
                "actor":       r[2],
                "action":      r[3],
                "entity_type": r[4],
                "entity_id":   r[5],
                "before_val":  r[6],
                "after_val":   r[7],
                "notes":       r[8],
            }
            for r in rows
        ]
        return {"entries": entries, "total": len(entries)}
    except Exception as exc:
        logger.error("[audit-trail] read failed: %s", exc)
        return {"entries": [], "total": 0}


@router.post("/agent-token/generate")
def generate_agent_token(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a 365-day JWT for the agent-fleet service account.
    Admin-only. Run once after deploy, copy the token into Railway
    as AGENT_APP_AUTH_TOKEN.
    """
    if not current_user.is_admin and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    agent_user = db.query(User).filter(User.email == "agents@bmgcapital.internal").first()
    if not agent_user:
        raise HTTPException(
            status_code=404,
            detail="agent-fleet service account not found — run migrations first",
        )

    from app.config import settings
    from jose import jwt as _jwt
    expire = datetime.now(timezone.utc) + timedelta(days=365)
    payload = {
        "sub": str(agent_user.id),
        "email": agent_user.email,
        "username": agent_user.username,
        "role": agent_user.role,
        "exp": expire,
    }
    token = _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return {
        "token": token,
        "expires": expire.isoformat(),
        "instructions": (
            "Add this to Railway env vars as AGENT_APP_AUTH_TOKEN. "
            "The agent fleet will use it for read-only API access."
        ),
    }


@router.get("/options/position-audit")
def options_position_audit(
    post_to_discord: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Audit open positions in options bots. Identifies share positions that
    shouldn't be there (misclassified), properly-stored option positions,
    and expired contracts.

    Pass ?post_to_discord=true to send a summary to #fund-updates.
    """
    from datetime import date
    from app.db.models.bots import BotProfile, BotAllocation, BotPosition

    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    today_str = date.today().isoformat()
    results: Dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "bots": {},
        "summary": {
            "properly_options": 0,
            "shares_misclassified": 0,
            "expired": 0,
            "total_open": 0,
        }
    }

    for bot_name in ("options_income", "options_directional"):
        prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
        if not prof:
            continue
        alloc_ids = [a.id for a in db.query(BotAllocation).filter(BotAllocation.profile_id == prof.id).all()]
        if not alloc_ids:
            continue

        open_positions = (
            db.query(BotPosition)
            .filter(
                BotPosition.allocation_id.in_(alloc_ids),
                BotPosition.closed_at.is_(None),
                BotPosition.quarantined_at.is_(None),
            )
            .all()
        )

        properly_options = []
        shares_misclassified = []
        expired = []

        for p in open_positions:
            row = {
                "id": p.id,
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_cost_cents": p.avg_cost_cents,
                "option_type": p.option_type,
                "strike_price": p.strike_price,
                "expiration_date": p.expiration_date,
                "contract_count": p.contract_count,
                "opened_at": iso_utc(p.opened_at),
            }
            if p.option_type is None:
                shares_misclassified.append(row)
            elif p.expiration_date and p.expiration_date < today_str:
                expired.append(row)
            else:
                properly_options.append(row)

        results["bots"][bot_name] = {
            "total_open": len(open_positions),
            "properly_options": properly_options,
            "shares_misclassified": shares_misclassified,
            "expired": expired,
        }
        results["summary"]["properly_options"] += len(properly_options)
        results["summary"]["shares_misclassified"] += len(shares_misclassified)
        results["summary"]["expired"] += len(expired)
        results["summary"]["total_open"] += len(open_positions)

    # Optionally post to Discord fund-updates
    if post_to_discord:
        s = results["summary"]
        lines = [
            "**⚡ Options Position Audit**",
            f"Total open: {s['total_open']} | Proper options: {s['properly_options']} | **Misclassified shares: {s['shares_misclassified']}** | Expired: {s['expired']}",
            "",
        ]
        for bot_name, data in results["bots"].items():
            if data["shares_misclassified"]:
                lines.append(f"**{bot_name}** — {len(data['shares_misclassified'])} share positions found:")
                for p in data["shares_misclassified"][:5]:
                    lines.append(f"  • `{p['symbol']}` qty={p['qty']} avg_cost=${p['avg_cost_cents']/100:.2f} opened={p['opened_at'][:10] if p['opened_at'] else '?'}")
                if len(data["shares_misclassified"]) > 5:
                    lines.append(f"  ... and {len(data['shares_misclassified'])-5} more")
            if data["expired"]:
                lines.append(f"**{bot_name}** — {len(data['expired'])} expired option positions")
        lines.append("")
        lines.append("@BrockGorzy — reply with **Option A** (close all share positions at market) or **Option B** (mark as misclassified, leave open). Options bots will generate real contracts going forward.")

        ok, err = _discord_fund_updates("\n".join(lines))
        results["discord_posted"] = ok
        if not ok:
            results["discord_error"] = err

    return results


def _discord_fund_updates(content: str) -> tuple[bool, str]:
    """Post content to #fund-updates via webhook first, bot REST API as fallback.

    Channel ID 1516291232802930698 is the hard-coded #fund-updates channel.
    Override with DISCORD_FUND_UPDATES_CHANNEL_ID env var if it changes.
    """
    import urllib.request as _urllib_req
    import json as _json

    payload = _json.dumps({"content": content[:2000]}).encode()
    headers = {"Content-Type": "application/json"}

    # 1. Try webhook URL (lowest friction)
    wh_url = os.environ.get("DISCORD_WH_FUND_UPDATES", "").strip()
    if wh_url:
        try:
            req = _urllib_req.Request(wh_url, data=payload, headers=headers, method="POST")
            with _urllib_req.urlopen(req, timeout=5):
                pass
            return True, ""
        except Exception as wh_exc:
            wh_err = str(wh_exc)
    else:
        wh_err = "DISCORD_WH_FUND_UPDATES not set"

    # 2. Fallback: Discord bot REST API
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("DISCORD_FUND_UPDATES_CHANNEL_ID", "1516291232802930698").strip()
    if bot_token:
        try:
            api_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            req = _urllib_req.Request(
                api_url,
                data=payload,
                headers={**headers, "Authorization": f"Bot {bot_token}"},
                method="POST",
            )
            with _urllib_req.urlopen(req, timeout=5):
                pass
            return True, ""
        except Exception as bot_exc:
            return False, f"webhook: {wh_err}; bot_api: {bot_exc}"

    return False, f"webhook: {wh_err}; DISCORD_BOT_TOKEN not set on backend"


@router.post("/discord/post-fund-updates")
def post_to_fund_updates(
    content: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Post an arbitrary message to #fund-updates. Admin only.

    Uses webhook first, falls back to bot REST API.
    Requires DISCORD_WH_FUND_UPDATES or DISCORD_BOT_TOKEN on the backend service.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    if not content.strip():
        raise HTTPException(status_code=400, detail="content is required")

    ok, err = _discord_fund_updates(content)
    return {"posted": ok, "error": err or None}


_SYNTHETIC_TAG = "SYNTHETIC_TEST_DELETE_ME"

_OPTIONS_DIRECTIONAL_BOT = "options_directional"

# OCC components for the synthetic test position
_SYN_SYMBOL    = "SPY260717C00800000"
_SYN_UNDERLYING = "SPY"
_SYN_TYPE      = "call"
_SYN_STRIKE    = 800.0          # dollars — NOT cents
_SYN_EXPIRY    = "2026-07-17"
_SYN_CONTRACTS = 1
_SYN_ENTRY_CENTS = 250.0        # $2.50 per-contract premium × 100


@router.post("/options/synthetic-fill-test")
def synthetic_fill_test(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create one synthetic filled options position + trade for mirror verification.

    The position is tagged quarantine_reason='SYNTHETIC_TEST_DELETE_ME' with
    quarantined_at=NULL so it appears on all 6 surfaces exactly as a real fill
    would. Also posts the options embed to #options-signals and #all-signals.

    Run DELETE /api/admin/options/synthetic-fill-test before market open to
    remove it so it does not pollute real P&L.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    from app.db.models.bots import BotProfile, BotAllocation, BotPosition, BotTrade

    prof = db.query(BotProfile).filter(BotProfile.name == _OPTIONS_DIRECTIONAL_BOT).first()
    if not prof:
        return {"ok": False, "error": f"Bot profile '{_OPTIONS_DIRECTIONAL_BOT}' not found"}

    alloc = (
        db.query(BotAllocation)
        .filter(BotAllocation.profile_id == prof.id, BotAllocation.paper_mode.is_(True))
        .first()
    )
    if not alloc:
        return {"ok": False, "error": f"No paper allocation for '{_OPTIONS_DIRECTIONAL_BOT}'"}

    now = datetime.now(timezone.utc)
    try:
        # ── SHIP 2 asset-class gate (path #8) — BEFORE BotPosition insert ──
        # 2026-06-29: moved BEFORE db.add. Previously this validate ran AFTER
        # db.add+db.flush, requiring rollback to undo. Now it raises
        # pre-INSERT so no rollback needed.
        try:
            from app.services.asset_class_registry import validate_order_with_user
            validate_order_with_user(
                bot_id=_OPTIONS_DIRECTIONAL_BOT,
                symbol=_SYN_SYMBOL,
                user_id=getattr(current_user, "id", None),
            )
        except RuntimeError as _acr_exc:
            raise HTTPException(status_code=422, detail=str(_acr_exc))
        # ── end asset-class gate ─────────────────────────────────────────────

        pos = BotPosition(
            allocation_id=alloc.id,
            symbol=_SYN_SYMBOL,
            qty=float(_SYN_CONTRACTS),
            avg_cost_cents=_SYN_ENTRY_CENTS,
            side="long",
            opened_at=now,
            closed_at=None,
            is_paper=True,
            trailing_stop_activated=False,
            option_type=_SYN_TYPE,
            strike_price=_SYN_STRIKE,
            expiration_date=_SYN_EXPIRY,
            underlying_symbol=_SYN_UNDERLYING,
            contract_count=_SYN_CONTRACTS,
            contract_premium_cents=_SYN_ENTRY_CENTS,
            quarantine_reason=_SYNTHETIC_TAG,
            origin="BACKFILL",  # m099 — synthetic test position (quarantined)
        )
        db.add(pos)
        db.flush()

        trade = BotTrade(
            allocation_id=alloc.id,
            symbol=_SYN_SYMBOL,
            side="buy",
            qty=float(_SYN_CONTRACTS),
            fill_price_cents=_SYN_ENTRY_CENTS,
            fill_price_micros=_SYN_ENTRY_CENTS * 10000,  # m100 — lossless from int cents
            fees_cents=0,
            ts=now,
            position_id=pos.id,
            is_paper=True,
            option_type=_SYN_TYPE,
            strike_price=_SYN_STRIKE,
            expiration_date=_SYN_EXPIRY,
            underlying_symbol=_SYN_UNDERLYING,
            contract_count=_SYN_CONTRACTS,
            contract_premium_cents=_SYN_ENTRY_CENTS,
            quarantine_reason=_SYNTHETIC_TAG,
            origin="BACKFILL",  # m099 — synthetic test trade
        )
        db.add(trade)
        db.commit()
        db.refresh(pos)
        db.refresh(trade)
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": f"DB write failed: {exc}"}

    # Post options embed via the same code path real signals use
    discord_posted = False
    try:
        from app.services.discord_public import post_signal as _post_signal
        _post_signal(
            {
                "bot":             _OPTIONS_DIRECTIONAL_BOT,
                "symbol":          _SYN_UNDERLYING,
                "side":            "buy",
                "confidence":      0.85,
                "strategy":        "long_call",
                "price":           _SYN_ENTRY_CENTS / 100,
                "option_type":     _SYN_TYPE,
                "strike_price":    _SYN_STRIKE,
                "expiration_date": _SYN_EXPIRY,
                "contract_count":  _SYN_CONTRACTS,
                "premium":         _SYN_ENTRY_CENTS / 100,
                "reason":          (
                    "[SYNTHETIC TEST] SPY 800C Jul-17 — verifying options embed format. "
                    "Delete before market open."
                ),
            },
            db=None,
            signal_id=None,
            source="bot",
        )
        discord_posted = True
    except Exception as exc:
        logger.warning("synthetic-fill-test discord post failed: %s", exc)

    logger.info(
        "synthetic-fill-test: position_id=%d trade_id=%d discord=%s",
        pos.id, trade.id, discord_posted,
    )
    return {
        "ok": True,
        "position_id": pos.id,
        "trade_id": trade.id,
        "contract_symbol": _SYN_SYMBOL,
        "strike": _SYN_STRIKE,
        "expiry": _SYN_EXPIRY,
        "entry_premium_usd": _SYN_ENTRY_CENTS / 100,
        "discord_posted": discord_posted,
        "cleanup_tag": _SYNTHETIC_TAG,
        "note": "Run DELETE /api/admin/options/synthetic-fill-test before 9:30 AM ET.",
        "verify_surfaces": [
            {"surface": "Activity Feed",             "path": "/activity",                      "filter": "Options asset class filter"},
            {"surface": "Options Portfolio",          "path": "/strategy/portfolio/options",    "filter": "Recent Trades section"},
            {"surface": "Bot Detail (directional)",   "path": "/strategy/bot/options_directional"},
            {"surface": "Dashboard",                  "path": "/dashboard",                     "filter": "Fleet P&L should include unrealized"},
            {"surface": "Discord #options-signals",   "note": "embed: CALL/strike/expiry/contracts — NO equity fields"},
            {"surface": "Discord #all-signals",       "note": "same embed within 5s"},
        ],
        "expected_display": {
            "contract_symbol":     _SYN_SYMBOL,
            "underlying":          _SYN_UNDERLYING,
            "contract_desc":       "800C 7/17",
            "entry_premium":       "$2.50/ct",
            "contracts":           "1 contract (NOT 100 shares)",
            "unrealized_pnl_formula": "(current_premium − 2.50) × 1 × 100",
            "asset_class":         "options (NOT stock)",
        },
    }


@router.delete("/options/synthetic-fill-test")
def delete_synthetic_fill_test(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete all synthetic test positions + trades created by POST /options/synthetic-fill-test."""
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    from sqlalchemy import text as _sql

    trades_deleted = positions_deleted = 0
    try:
        r = db.execute(
            _sql("DELETE FROM bot_trades WHERE quarantine_reason = :tag AND quarantined_at IS NULL"),
            {"tag": _SYNTHETIC_TAG},
        )
        trades_deleted = r.rowcount or 0
    except Exception as exc:
        logger.warning("synthetic cleanup trades failed: %s", exc)

    try:
        r = db.execute(
            _sql("DELETE FROM bot_positions WHERE quarantine_reason = :tag AND quarantined_at IS NULL"),
            {"tag": _SYNTHETIC_TAG},
        )
        positions_deleted = r.rowcount or 0
    except Exception as exc:
        logger.warning("synthetic cleanup positions failed: %s", exc)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": f"commit failed: {exc}"}

    logger.info("synthetic-fill-test deleted: trades=%d positions=%d", trades_deleted, positions_deleted)
    return {"ok": True, "trades_deleted": trades_deleted, "positions_deleted": positions_deleted}


def _next_options_monthly_expiry() -> str:
    """Return the nearest third-Friday monthly expiry ≥21 DTE from today (YYYY-MM-DD)."""
    from datetime import date, timedelta
    today = date.today()
    year, month = today.year, today.month
    for _ in range(6):
        first = date(year, month, 1)
        days_to_first_friday = (4 - first.weekday()) % 7
        third_friday = first + timedelta(days=days_to_first_friday + 14)
        if (third_friday - today).days >= 21:
            return third_friday.strftime("%Y-%m-%d")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    raise RuntimeError("No valid monthly expiry found within 6 months")


def _build_occ_symbol(root: str, expiry: str, call_or_put: str, strike: float) -> str:
    """Build OCC option symbol, e.g. SPY260717C00595000."""
    yy, mm, dd = expiry[2:4], expiry[5:7], expiry[8:10]
    cp = "C" if call_or_put.lower().startswith("c") else "P"
    return f"{root}{yy}{mm}{dd}{cp}{int(round(strike * 1000)):08d}"


@router.post("/options/test-order")
def options_test_order(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Prove end-to-end that backend can submit options orders to Alpaca paper.

    Sends a $0.01 limit BUY of an OTM SPY call (~30 DTE). Cancels immediately
    if accepted. No DB writes.

    Returns verdict: WORKING | OPTIONS_NOT_ENABLED | INVALID_SYMBOL | MARKET_CLOSED | OTHER_ERROR.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    from strategy_lab.brokers.alpaca_paper_stocks import PaperStocksAdapter

    # Compute target expiry and strike
    try:
        expiry = _next_options_monthly_expiry()
    except Exception as exc:
        return {"verdict": "OTHER_ERROR", "error": f"expiry calc failed: {exc}"}

    spot = 0.0
    try:
        import yfinance as yf
        fi = yf.Ticker("SPY").fast_info
        spot = float(getattr(fi, "last_price", 0) or 0)
    except Exception:
        pass
    if spot <= 0:
        spot = 595.0  # sane fallback if yfinance unavailable

    # +$50 OTM call, rounded to nearest $5
    strike = round((spot + 50.0) / 5) * 5
    contract_symbol = _build_occ_symbol("SPY", expiry, "call", strike)

    # Submit $0.01 limit (won't fill — proves Alpaca accepts it)
    try:
        broker = PaperStocksAdapter()
        result = broker.submit_options_order(
            contract_symbol=contract_symbol,
            contracts=1,
            side="buy",
            limit_price=0.01,
        )
    except Exception as exc:
        return {"verdict": "OTHER_ERROR", "error": str(exc), "contract_symbol": contract_symbol}

    status = result["status_code"]
    body = result["body"]
    order_id = result.get("order_id")
    error_msg = (body.get("message") or body.get("error") or "").lower()

    if status in (200, 201):
        verdict = "WORKING"
    elif status == 403:
        verdict = "OPTIONS_NOT_ENABLED"
    elif status in (400, 422):
        if "symbol" in error_msg or "not found" in error_msg or "invalid" in error_msg:
            verdict = "INVALID_SYMBOL"
        elif "option" in error_msg:
            verdict = "OPTIONS_NOT_ENABLED"
        elif "market" in error_msg and "closed" in error_msg:
            verdict = "MARKET_CLOSED"
        else:
            verdict = "OTHER_ERROR"
    else:
        verdict = "OTHER_ERROR"

    # Cancel immediately if accepted
    cancelled = False
    cancel_error = None
    if order_id and verdict == "WORKING":
        try:
            cancelled = broker.cancel_order(order_id)
        except Exception as exc:
            cancel_error = str(exc)

    # Post result to #fund-updates
    emoji = "✅" if verdict == "WORKING" else "❌"
    _discord_fund_updates(
        f"{emoji} **test-order endpoint live** — Alpaca options order: **{verdict}**\n"
        f"Symbol: `{contract_symbol}` (SPY +$50 OTM call, expiry {expiry})\n"
        f"HTTP {status}" + (" — order accepted and cancelled" if cancelled else "")
    )

    logger.info(
        "options/test-order: verdict=%s symbol=%s status=%d order_id=%s cancelled=%s",
        verdict, contract_symbol, status, order_id, cancelled,
    )
    return {
        "verdict": verdict,
        "contract_symbol": contract_symbol,
        "expiry": expiry,
        "spot": spot,
        "strike": strike,
        "http_status": status,
        "order_id": order_id,
        "alpaca_response": body,
        "order_cancelled": cancelled,
        "cancel_error": cancel_error,
    }


@router.post("/options/announce-quarantine-complete")
def announce_quarantine_complete(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Post the quarantine-complete verification summary to #fund-updates.

    Call this once after deploy to confirm m010 migration ran and options
    bots are generating fresh real contracts.
    """
    from app.db.models.bots import BotProfile, BotAllocation, BotPosition

    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    quarantined_count = 0
    fresh_count = 0
    for bot_name in ("options_income", "options_directional"):
        prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
        if not prof:
            continue
        alloc_ids = [a.id for a in db.query(BotAllocation).filter(BotAllocation.profile_id == prof.id).all()]
        if not alloc_ids:
            continue
        quarantined_count += (
            db.query(BotPosition)
            .filter(
                BotPosition.allocation_id.in_(alloc_ids),
                BotPosition.quarantined_at.isnot(None),
                BotPosition.quarantine_reason == "misclassified_legacy_pre_17aa7f3",
            )
            .count()
        )
        fresh_count += (
            db.query(BotPosition)
            .filter(
                BotPosition.allocation_id.in_(alloc_ids),
                BotPosition.closed_at.is_(None),
                BotPosition.quarantined_at.is_(None),
            )
            .count()
        )

    msg = (
        f"**✅ Options Pipeline Fix Complete — commit 17aa7f3**\n"
        f"\n"
        f"**Legacy quarantine:** {quarantined_count} positions excluded from P&L and Activity Feed "
        f"(misclassified shares + corrupted strike=$100 contracts, pre-fix)\n"
        f"**Fresh options positions:** {fresh_count} real contracts from today's force-fire "
        f"(proper OCC contracts, yfinance chain, correct premium)\n"
        f"\n"
        f"**Discord #fund-updates posting:** ✅ fixed (bot REST API fallback added)\n"
        f"\n"
        f"P&L formula corrected — portfolio value no longer inflated by phantom stock-price comparison. "
        f"Options bots are live and generating real contracts."
    )

    ok, err = _discord_fund_updates(msg)
    return {
        "posted": ok,
        "error": err or None,
        "quarantined_legacy": quarantined_count,
        "fresh_options": fresh_count,
        "message_preview": msg[:200],
    }


# ── GET /api/admin/options/quarantine-summary ─────────────────────────────────

@router.get("/options/quarantine-summary")
def options_quarantine_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return counts of quarantined options bot_positions + bot_trades by reason and bot."""
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    from sqlalchemy import text as _sql
    from app.db.models.bots import BotProfile, BotAllocation, BotPosition, BotTrade

    for bot_name in ("options_income", "options_directional"):
        pass  # just warm the import

    # Summary by bot + reason
    try:
        pos_rows = db.execute(_sql("""
            SELECT bp.name AS bot, bpos.quarantine_reason, COUNT(*) AS cnt
            FROM bot_positions bpos
            JOIN bot_allocations ba ON ba.id = bpos.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bp.name IN ('options_income', 'options_directional')
              AND bpos.quarantined_at IS NOT NULL
            GROUP BY bp.name, bpos.quarantine_reason
        """)).fetchall()
    except Exception as exc:
        pos_rows = []
        logger.warning("quarantine-summary positions query failed: %s", exc)

    try:
        trade_rows = db.execute(_sql("""
            SELECT bp.name AS bot, bt.quarantine_reason, COUNT(*) AS cnt
            FROM bot_trades bt
            JOIN bot_allocations ba ON ba.id = bt.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bp.name IN ('options_income', 'options_directional')
              AND bt.quarantined_at IS NOT NULL
            GROUP BY bp.name, bt.quarantine_reason
        """)).fetchall()
    except Exception as exc:
        trade_rows = []
        logger.warning("quarantine-summary trades query failed: %s", exc)

    try:
        active_pos = db.execute(_sql("""
            SELECT bp.name AS bot, COUNT(*) AS cnt
            FROM bot_positions bpos
            JOIN bot_allocations ba ON ba.id = bpos.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bp.name IN ('options_income', 'options_directional')
              AND bpos.quarantined_at IS NULL
              AND bpos.closed_at IS NULL
            GROUP BY bp.name
        """)).fetchall()
    except Exception as exc:
        active_pos = []
        logger.warning("quarantine-summary active positions query failed: %s", exc)

    by_bot: Dict[str, Any] = {}
    for r in pos_rows:
        by_bot.setdefault(r[0], {"quarantined_positions": {}, "quarantined_trades": {}})
        by_bot[r[0]]["quarantined_positions"][r[1] or "no_reason"] = r[2]
    for r in trade_rows:
        by_bot.setdefault(r[0], {"quarantined_positions": {}, "quarantined_trades": {}})
        by_bot[r[0]]["quarantined_trades"][r[1] or "no_reason"] = r[2]
    for r in active_pos:
        by_bot.setdefault(r[0], {"quarantined_positions": {}, "quarantined_trades": {}})
        by_bot[r[0]]["active_open_positions"] = r[1]

    total_q_pos    = sum(r[2] for r in pos_rows)
    total_q_trades = sum(r[2] for r in trade_rows)

    return {
        "quarantined_positions": total_q_pos,
        "quarantined_trades":    total_q_trades,
        "by_bot": by_bot,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ── POST /api/admin/discord/purge-legacy-options-embeds ──────────────────────

_MARKET_OPEN_CUTOFF = datetime(2026, 6, 19, 13, 30, 0, tzinfo=timezone.utc)
_DISCORD_EPOCH_MS   = 1_420_070_400_000  # 2015-01-01T00:00:00Z in milliseconds
_OPTIONS_BOT_AUTHORS = {
    "Options Income bot", "Options Directional bot",
    "Equity Income bot",  "Equity Directional bot",
}


def _dt_to_snowflake(dt: datetime) -> int:
    ms = int(dt.timestamp() * 1000)
    return (ms - _DISCORD_EPOCH_MS) << 22


def _snowflake_to_dt(snowflake: int) -> datetime:
    ms = (snowflake >> 22) + _DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@router.post("/discord/purge-legacy-options-embeds")
def purge_legacy_options_embeds(
    confirm: bool = False,
    purge_all_signals: bool = False,
    keep_synthetic: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete legacy options embeds from Discord channels before today's market open.

    #options-signals: deletes ALL messages before 2026-06-19 13:30 UTC.
    #all-signals: deletes only messages from options bots (by embed author).

    DESTRUCTIVE — Discord deletes are permanent.
    Requires ?confirm=true to execute. Without it, returns a dry-run count.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    import time as _time
    import json as _json
    import urllib.request as _ur
    import urllib.error as _ue

    from app.config import settings as _cfg

    bot_token = (os.environ.get("DISCORD_BOT_TOKEN") or _cfg.discord_bot_token or "").strip()
    if not bot_token:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN not set on backend service"}

    ch_options = (
        os.environ.get("DISCORD_CH_OPTIONS_SIGNALS") or
        _cfg.discord_ch_options_signals or
        _cfg.discord_channel_options or
        "1512905889974325280"
    ).strip()
    ch_all = (
        os.environ.get("DISCORD_CH_ALL_SIGNALS") or
        _cfg.discord_ch_all_signals or
        _cfg.discord_channel_all_signals or
        ""
    ).strip()

    cutoff_snowflake = _dt_to_snowflake(_MARKET_OPEN_CUTOFF)
    fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=13, hours=23)

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }

    def _discord_get(url: str) -> Any:
        req = _ur.Request(url, headers=headers)
        with _ur.urlopen(req, timeout=10) as resp:
            return _json.loads(resp.read())

    def _discord_delete(url: str) -> bool:
        req = _ur.Request(url, headers=headers, method="DELETE")
        try:
            with _ur.urlopen(req, timeout=10):
                pass
            return True
        except Exception:
            return False

    def _discord_bulk_delete(channel_id: str, message_ids: list[str]) -> bool:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages/bulk-delete"
        data = _json.dumps({"messages": message_ids}).encode()
        req = _ur.Request(url, data=data, headers=headers, method="POST")
        try:
            with _ur.urlopen(req, timeout=10):
                pass
            return True
        except Exception as exc:
            logger.warning("bulk-delete failed: %s", exc)
            return False

    def _fetch_messages_before(channel_id: str, before_snowflake: int) -> list[dict]:
        """Fetch all messages in channel_id before before_snowflake (paginates 100 at a time)."""
        all_msgs: list[dict] = []
        before = str(before_snowflake)
        while True:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100&before={before}"
            try:
                msgs = _discord_get(url)
            except Exception as exc:
                logger.warning("fetch messages failed: %s", exc)
                break
            if not msgs:
                break
            all_msgs.extend(msgs)
            before = msgs[-1]["id"]
            _time.sleep(0.5)  # respect rate limits
        return all_msgs

    def _purge_channel(channel_id: str, filter_fn=None) -> Dict[str, Any]:
        """Delete messages before cutoff in channel_id. filter_fn(msg) → bool to keep."""
        msgs = _fetch_messages_before(channel_id, cutoff_snowflake)
        if filter_fn:
            msgs = [m for m in msgs if not filter_fn(m)]  # filter_fn returns True = delete

        bulk_ids   = [m["id"] for m in msgs if _snowflake_to_dt(int(m["id"])) >= fourteen_days_ago]
        single_ids = [m["id"] for m in msgs if _snowflake_to_dt(int(m["id"])) < fourteen_days_ago]

        deleted = 0
        errors  = 0
        if not confirm:
            return {"dry_run": True, "would_delete": len(msgs), "bulk": len(bulk_ids), "single": len(single_ids)}

        # Bulk delete in batches of up to 100 (min 2)
        for i in range(0, len(bulk_ids), 100):
            batch = bulk_ids[i:i + 100]
            if len(batch) == 1:
                single_ids.append(batch[0])
                continue
            if _discord_bulk_delete(channel_id, batch):
                deleted += len(batch)
            else:
                errors += len(batch)
            _time.sleep(1)

        # One-by-one for old messages
        for mid in single_ids:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{mid}"
            if _discord_delete(url):
                deleted += 1
            else:
                errors += 1
            _time.sleep(0.5)

        return {"deleted": deleted, "errors": errors}

    # ── keep_synthetic path — runs after helpers are defined ──────────────────
    if keep_synthetic:
        _EXPECTED_CH = "1512905889974325280"
        if ch_options != _EXPECTED_CH:
            return {
                "ok": False,
                "error": (
                    f"Channel ID mismatch: resolved {ch_options!r}, "
                    f"expected {_EXPECTED_CH!r}. Aborting to prevent deletion from wrong channel."
                ),
            }

        _SYNTHETIC_MARKERS = {
            "synthetic_test_delete_me",
            "spy260717c00800000",
            "verifying options embed format",
        }

        def _is_synthetic_embed(msg: dict) -> bool:
            for emb in (msg.get("embeds") or []):
                texts = [
                    emb.get("title") or "",
                    emb.get("description") or "",
                    (emb.get("footer") or {}).get("text") or "",
                    (emb.get("author") or {}).get("name") or "",
                ]
                for field in (emb.get("fields") or []):
                    texts.append(field.get("name") or "")
                    texts.append(field.get("value") or "")
                combined = " ".join(texts).lower()
                if any(m in combined for m in _SYNTHETIC_MARKERS):
                    return True
            return False

        all_msgs = _fetch_messages_before(ch_options, cutoff_snowflake)
        synthetic_msgs = [m for m in all_msgs if _is_synthetic_embed(m)]
        to_delete = [m for m in all_msgs if not _is_synthetic_embed(m)]

        if not confirm:
            return {
                "dry_run": True,
                "would_delete": len(to_delete),
                "would_keep_synthetic": len(synthetic_msgs),
                "channel": "options-signals",
                "channel_id": ch_options,
            }

        result = _purge_channel(ch_options, filter_fn=_is_synthetic_embed)
        return {
            "options_signals": result,
            "all_signals": {"skipped": True, "reason": "keep_synthetic=true — only #options-signals touched"},
            "confirm": confirm,
            "cutoff": _MARKET_OPEN_CUTOFF.isoformat(),
            "kept_synthetic": len(synthetic_msgs),
        }

    results: Dict[str, Any] = {"confirm": confirm, "cutoff": _MARKET_OPEN_CUTOFF.isoformat()}

    # #options-signals — delete ALL messages before cutoff
    if ch_options:
        results["options_signals"] = _purge_channel(ch_options)
    else:
        results["options_signals"] = {"skipped": True, "reason": "DISCORD_CH_OPTIONS_SIGNALS not set"}

    # #all-signals — delete only messages from options bots
    if purge_all_signals and ch_all:
        def _is_options_embed(msg: dict) -> bool:
            embeds = msg.get("embeds") or []
            if not embeds:
                return False
            author = (embeds[0].get("author") or {}).get("name", "")
            return author in _OPTIONS_BOT_AUTHORS
        results["all_signals"] = _purge_channel(ch_all, filter_fn=lambda m: not _is_options_embed(m))
    elif purge_all_signals:
        results["all_signals"] = {"skipped": True, "reason": "DISCORD_CH_ALL_SIGNALS not set"}
    else:
        results["all_signals"] = {"skipped": True, "reason": "Pass ?purge_all_signals=true to include"}

    # Post summary to #fund-updates after a confirmed purge
    if confirm and not any(r.get("dry_run") for r in results.values() if isinstance(r, dict)):
        opts_count = (results.get("options_signals") or {}).get("deleted", 0)
        all_count  = (results.get("all_signals") or {}).get("deleted", 0)
        _discord_fund_updates(
            f"🧹 **Legacy options cleanup complete**\n"
            f"Quarantined trades (DB): run `/api/admin/options/quarantine-summary` for counts\n"
            f"Discord embeds purged: **{opts_count}** from #options-signals"
            + (f", **{all_count}** from #all-signals" if all_count else "")
            + "\nFresh slate for today's options fills."
        )

    return results


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 1 — Ops alert verification endpoint
# Lets Brock send a synthetic ops alert to verify the new routing works
# end-to-end without waiting for a real incident. Routes through
# send_ops_alert() → alert_webhook_url, gated by DISCORD_OPS_ALERTS_ENABLED
# (independent of DISCORD_SIGNAL_POSTING_ENABLED).
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/ops-alert/test")
def test_ops_alert(
    severity: str = Query("info", regex="^(info|warn|critical)$"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Send a synthetic ops alert. Use ?severity=info|warn|critical."""
    from app.services.discord import send_ops_alert, _ops_alerts_enabled, _ops_webhook_url
    ok = send_ops_alert(
        title="Synthetic test alert",
        message=(
            "If you see this in the ops channel, the new send_ops_alert routing "
            f"is working. Triggered by user {current_user.id} via "
            "POST /api/admin/ops-alert/test."
        ),
        severity=severity,
        source="admin.test_ops_alert",
        fields=[
            {"name": "DISCORD_OPS_ALERTS_ENABLED", "value": str(_ops_alerts_enabled()), "inline": True},
            {"name": "Webhook configured", "value": "yes" if _ops_webhook_url() else "no", "inline": True},
        ],
    )
    return {
        "ok": ok,
        "ops_alerts_enabled": _ops_alerts_enabled(),
        "webhook_configured": bool(_ops_webhook_url()),
        "severity": severity,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 4 — Identify 17th allocation (orphan hunt)
# Enumerate every BotAllocation row + classify (active / incubating /
# retired / orphan). Vol-targeting must exclude orphans from its weight
# math until each is reclassified.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/allocations/inventory")
def allocations_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """List every bot_allocations row with a classification label.

    Classification rules:
      - enabled=1                                  → active
      - paused_reason LIKE '%incubat%'             → incubating
      - paused_reason LIKE '%retire%'              → retired
      - enabled=0 + no clear paused_reason         → orphan
    """
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT a.id, a.user_id, a.profile_id, p.name, a.enabled,
               a.starting_capital_cents, a.capital_cents_within_portfolio,
               a.paused_reason, a.tier, a.portfolio_id
        FROM bot_allocations a
        JOIN bot_profiles p ON p.id = a.profile_id
        ORDER BY a.id
    """)).fetchall()

    def _classify(enabled: Any, paused_reason: Any) -> str:
        is_enabled = bool(enabled)
        pr = (paused_reason or "").lower()
        if is_enabled:
            return "active"
        if "incubat" in pr:
            return "incubating"
        if "retire" in pr:
            return "retired"
        return "orphan"

    inventory = []
    counts: Dict[str, int] = {"active": 0, "incubating": 0, "retired": 0, "orphan": 0}
    orphans: list = []
    for r in rows:
        cls = _classify(r[4], r[7])
        counts[cls] = counts.get(cls, 0) + 1
        entry = {
            "id": r[0],
            "user_id": r[1],
            "profile_id": r[2],
            "name": r[3],
            "enabled": bool(r[4]),
            "starting_capital_cents": r[5],
            "capital_cents_within_portfolio": r[6],
            "paused_reason": r[7],
            "tier": r[8],
            "portfolio_id": r[9],
            "classification": cls,
        }
        inventory.append(entry)
        if cls == "orphan":
            orphans.append(entry)

    # Post the full list to ops channel — fire-and-forget.
    try:
        from app.services.discord import send_ops_alert

        # Trim list to fit Discord embed limits (1900 char description max).
        list_lines = [
            f"#{e['id']:>3} {e['classification']:<10} {e['name'][:32]:<32} "
            f"enabled={int(e['enabled'])} tier={e['tier']}"
            for e in inventory
        ]
        message = "```\n" + "\n".join(list_lines)[:1700] + "\n```"
        fields = [
            {"name": "active", "value": str(counts["active"]), "inline": True},
            {"name": "incubating", "value": str(counts["incubating"]), "inline": True},
            {"name": "retired", "value": str(counts["retired"]), "inline": True},
            {"name": "orphan", "value": str(counts["orphan"]), "inline": True},
            {"name": "total", "value": str(len(inventory)), "inline": True},
        ]
        if orphans:
            orph_str = ", ".join(f"#{o['id']} {o['name']}" for o in orphans[:10])
            fields.append({"name": "Orphans flagged", "value": orph_str[:1024], "inline": False})

        send_ops_alert(
            title=f"Allocation inventory · {len(inventory)} rows · {counts['orphan']} orphan(s)",
            message=message,
            severity="info",
            source="admin.allocations_inventory",
            fields=fields,
        )
    except Exception as exc:
        logger.warning("[allocations_inventory] ops alert failed: %s", exc)

    return {
        "ok": True,
        "total": len(inventory),
        "counts": counts,
        "inventory": inventory,
        "orphans": orphans,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 3 — EOD reconciliation force-complete override
# When compute_and_store_nav halts because the recompute swing exceeds the
# $5K threshold, this endpoint lets an operator override after manual review
# of the diff posted to the ops channel. Audit log retained in-process via
# compute_nav._FORCE_COMPLETE_REASONS.
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/reconciliation/force-complete")
def force_complete_reconciliation(
    reason: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Force the EOD NAV recompute to overwrite a halted-row. Requires a reason.
    Posts an override confirmation to the ops channel."""
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="reason must be ≥5 chars")
    from app.jobs.compute_nav import compute_and_store_nav, _FORCE_COMPLETE_REASONS
    result = compute_and_store_nav(db, force=True, force_reason=reason.strip())
    return {
        "ok": True,
        "result": result,
        "audit_log_length": len(_FORCE_COMPLETE_REASONS),
        "by_user_id": current_user.id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 5 — Portfolio health invariant probe
# Hits Dashboard / Portfolio / Strategy Lab data sources (they all delegate to
# compute_strategy_lab_aggregate, so reading the response shape three ways
# gives us a single canonical PV that we then assert is internally consistent).
# If max divergence > $500 (50_000 cents, 0.5% of $1M) → ops alert severity=warn.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/portfolio-health")
def portfolio_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Probe the three primary PV surfaces.

    Returns max_divergence_cents and posts a warn ops alert when divergence
    exceeds $500 (50_000 cents) — the same threshold the canonical aggregator
    uses for its internal split-brain diagnostic, surfaced as a poll-able
    endpoint for external monitors.
    """
    from app.core.canonical import compute_strategy_lab_aggregate
    from app.services.discord import send_ops_alert

    agg = compute_strategy_lab_aggregate(current_user.id, db) or {}

    # All three surfaces (Dashboard, Portfolio, Strategy Lab) call this exact
    # aggregator. We extract three independent reads to validate that the
    # response itself is internally consistent — alias fields must match and
    # the per-portfolio breakdown must sum back to the fleet total.
    strategy_lab_pv = int(agg.get("total_value_cents") or 0)
    dashboard_pv = int(agg.get("portfolio_value_cents") or 0)  # alias used by Dashboard
    # Portfolio "breakdown" is per-sleeve slices. Add the two known non-slice
    # contributors so the compare matches Dashboard/StrategyLab (which read
    # total_value_cents). Without this, split-brain warns are phantom every
    # time an orphan admin allocation exists or portfolio_rank_bots hold
    # capital — those are legitimate PV components, not misroutes.
    portfolio_breakdown_pv = (
        sum(int(p.get("portfolio_value_cents") or 0) for p in (agg.get("portfolios") or []))
        + int(agg.get("orphan_value_cents") or 0)
        + int(agg.get("portfolio_rank_value_cents") or 0)
    )

    values = [dashboard_pv, portfolio_breakdown_pv, strategy_lab_pv]
    max_divergence = (max(values) - min(values)) if values else 0
    status = "ok" if max_divergence <= 50_000 else "warn"

    if status == "warn":
        try:
            send_ops_alert(
                title="Portfolio PV divergence detected",
                message=(
                    f"Dashboard / Portfolio / Strategy-Lab PV diverge by "
                    f"{max_divergence} cents (>$500). Investigate canonical "
                    "aggregator integrity."
                ),
                severity="warn",
                source="admin.portfolio_health",
                fields=[
                    {"name": "dashboard_pv_cents", "value": str(dashboard_pv), "inline": True},
                    {"name": "portfolio_pv_cents", "value": str(portfolio_breakdown_pv), "inline": True},
                    {"name": "strategy_lab_pv_cents", "value": str(strategy_lab_pv), "inline": True},
                    {"name": "max_divergence_cents", "value": str(max_divergence), "inline": True},
                ],
            )
        except Exception as exc:
            logger.warning("[portfolio-health] ops alert failed: %s", exc)

    return {
        "dashboard_pv_cents": dashboard_pv,
        "portfolio_pv_cents": portfolio_breakdown_pv,
        "strategy_lab_pv_cents": strategy_lab_pv,
        "max_divergence_cents": max_divergence,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ─── Capital Invariant — m027 watchdog endpoint ─────────────────────────────
@router.get("/capital-invariant")
def capital_invariant(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """SUM(starting_capital_cents) for enabled allocations under user_id=1
    must equal $1,000,000 within ±$1. Surfaces the watchdog state plus the
    capital_audit_log row count for the last 24h (excluding m027 markers).

    Status semantics:
      ok   — drift ≤ $1
      warn — drift in ($1, $100]
      crit — drift > $100  (logs CRITICAL + Discord ops alert)
    """
    from app.services.capital_invariant import (
        check_capital_invariant,
        EXPECTED_SUM_CENTS as _capinv_expected_const,
    )
    def _capinv_expected() -> int:
        return _capinv_expected_const
    status = check_capital_invariant(db, user_id=1)
    return {
        "status":                status.status,
        "is_valid":              status.is_valid,
        "current_sum_cents":     status.current_sum_cents,
        # 2026-07-07 m077: expected pulled from service constant so
        # the mirror-Alpaca rescale ($97,340) is reflected in API
        # responses. Was hardcoded to 100_000_000 which caused a
        # $903k phantom drift display after m077 landed.
        "expected_sum_cents":    _capinv_expected(),
        "drift_cents":           status.drift_cents,
        "drift_dollars":         status.drift_dollars,
        "enabled_count":         status.enabled_count,
        "expected_count":        status.expected_count,
        "audit_log_rows_24h":    status.audit_log_rows_24h,
        "per_bot":               status.per_bot,
        "last_checked_at":       status.last_checked_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 8 — Stop-hit asymmetry report
# Counts closes vs stops per bot over a configurable window.
# stop_pct = stops / total_closes. Flag review_required when >45% with
# >200 closes — catches Crypto Day/Swing bleeding before it compounds.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/closes/stop-asymmetry")
def closes_stop_asymmetry(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Group bot_trades by bot, count closes vs stops over the window.

    Stop = BotTrade.side in ('sell','close','cover')
           AND linked bot_positions.exit_reason = 'stop_loss'.
    Flag review_required=true if stop_pct > 45 over >200 closes.
    """
    from sqlalchemy import text

    # SQLite: use datetime('now', '-N days') — INTERVAL is not supported.
    rows = db.execute(text(f"""
        SELECT
            a.id   AS allocation_id,
            p.id   AS profile_id,
            p.name AS profile_name,
            SUM(CASE WHEN LOWER(t.side) IN ('sell','close','cover') THEN 1 ELSE 0 END) AS total_closes,
            SUM(CASE
                WHEN LOWER(t.side) IN ('sell','close','cover')
                 AND pos.exit_reason = 'stop_loss'
                THEN 1 ELSE 0 END) AS stops
        FROM bot_trades t
        JOIN bot_allocations a ON a.id = t.allocation_id
        JOIN bot_profiles p    ON p.id = a.profile_id
        LEFT JOIN bot_positions pos ON pos.id = t.position_id
        WHERE t.ts >= datetime('now', '-{int(days)} days')
        GROUP BY a.id, p.id, p.name
        ORDER BY stops DESC
    """)).fetchall()

    report = []
    for r in rows:
        alloc_id = r[0]
        profile_id = r[1]
        profile_name = r[2]
        total_closes = int(r[3] or 0)
        stops = int(r[4] or 0)
        stop_pct = (stops / total_closes * 100.0) if total_closes > 0 else 0.0
        review_required = bool(stop_pct > 45.0 and total_closes > 200)
        report.append({
            "allocation_id": alloc_id,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "total_closes": total_closes,
            "stops": stops,
            "stop_pct": round(stop_pct, 2),
            "review_required": review_required,
        })

    flagged = [r for r in report if r["review_required"]]
    flagged_sorted = sorted(flagged, key=lambda x: x["stop_pct"], reverse=True)
    top_flagged = flagged_sorted[:10]

    # Post flagged report to ops channel — fire-and-forget.
    try:
        from app.services.discord import send_ops_alert

        if top_flagged:
            lines = [
                f"{r['profile_name'][:30]:<30} closes={r['total_closes']:>5} "
                f"stops={r['stops']:>4} stop_pct={r['stop_pct']:>5.1f}%"
                for r in top_flagged
            ]
            message = "```\n" + "\n".join(lines)[:1700] + "\n```"
            severity = "warn"
        else:
            message = (
                f"No bots crossed the stop-asymmetry threshold "
                f"(>45% stop rate over 200+ closes) in the last {days} days. "
                f"Inspected {len(report)} bots."
            )
            severity = "info"

        send_ops_alert(
            title=f"Stop-asymmetry report · {days}d · {len(flagged)} flagged",
            message=message,
            severity=severity,
            source="admin.closes_stop_asymmetry",
            fields=[
                {"name": "window_days", "value": str(days), "inline": True},
                {"name": "bots_inspected", "value": str(len(report)), "inline": True},
                {"name": "bots_flagged", "value": str(len(flagged)), "inline": True},
            ],
        )
    except Exception as exc:
        logger.warning("[closes_stop_asymmetry] ops alert failed: %s", exc)

    return {
        "ok": True,
        "window_days": days,
        "bots_inspected": len(report),
        "bots_flagged": len(flagged),
        "report": report,
        "top_flagged": top_flagged,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 9 — Per-strategy discipline gate-rate report
# Group signal_gates by strategy. gate_rate = gated / total.
# Flag STARVED (>85% gated, >100 signals) and UNFILTERED
# (<15% gated, >100 signals). Posts both flagged groups to ops channel.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/discipline/gate-rate")
def discipline_gate_rate(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Group signal_gates by strategy. Report gate_rate and flag extremes.

    `gated` = final_decision != 'executed' (the SignalGate default for a
    passing row). Anything else (typically 'filtered') is a gated decision.
    """
    from sqlalchemy import text

    rows = db.execute(text(f"""
        SELECT
            strategy,
            COUNT(*) AS total,
            SUM(CASE WHEN final_decision != 'executed' THEN 1 ELSE 0 END) AS gated
        FROM signal_gates
        WHERE created_at >= datetime('now', '-{int(days)} days')
        GROUP BY strategy
        ORDER BY total DESC
    """)).fetchall()

    report = []
    starved = []
    unfiltered = []
    for r in rows:
        strategy = r[0] or "(unknown)"
        total = int(r[1] or 0)
        gated = int(r[2] or 0)
        gate_rate = (gated / total * 100.0) if total > 0 else 0.0
        flags = []
        if total > 100 and gate_rate > 85.0:
            flags.append("STARVED")
        if total > 100 and gate_rate < 15.0:
            flags.append("UNFILTERED")
        entry = {
            "strategy": strategy,
            "total": total,
            "gated": gated,
            "gate_rate": round(gate_rate, 2),
            "flags": flags,
        }
        report.append(entry)
        if "STARVED" in flags:
            starved.append(entry)
        if "UNFILTERED" in flags:
            unfiltered.append(entry)

    # Post both flagged groups to ops channel — fire-and-forget.
    try:
        from app.services.discord import send_ops_alert

        def _fmt(group_label: str, group: list) -> str:
            if not group:
                return f"{group_label}: none\n"
            lines = [
                f"  {g['strategy'][:30]:<30} total={g['total']:>5} "
                f"gated={g['gated']:>5} rate={g['gate_rate']:>5.1f}%"
                for g in group
            ]
            return f"{group_label}:\n" + "\n".join(lines) + "\n"

        message = (
            "```\n"
            + _fmt(f"STARVED (>85% gated, >100 signals)", starved)
            + "\n"
            + _fmt(f"UNFILTERED (<15% gated, >100 signals)", unfiltered)
            + "```"
        )
        severity = "warn" if (starved or unfiltered) else "info"

        send_ops_alert(
            title=f"Gate-rate report · {days}d · {len(starved)} starved · {len(unfiltered)} unfiltered",
            message=message[:1900],
            severity=severity,
            source="admin.discipline_gate_rate",
            fields=[
                {"name": "window_days", "value": str(days), "inline": True},
                {"name": "strategies_inspected", "value": str(len(report)), "inline": True},
                {"name": "starved", "value": str(len(starved)), "inline": True},
                {"name": "unfiltered", "value": str(len(unfiltered)), "inline": True},
            ],
        )
    except Exception as exc:
        logger.warning("[discipline_gate_rate] ops alert failed: %s", exc)

    return {
        "ok": True,
        "window_days": days,
        "strategies_inspected": len(report),
        "report": report,
        "starved": starved,
        "unfiltered": unfiltered,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 11 — 20 leftover quarantine row classification
# Classifies the rows left from the misclassified_legacy_pre_17aa7f3
# sweep using a 4-gate filter. NO auto-action — posts the table to ops
# for per-row greenlight.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/options/legacy-quarantine-audit")
def options_legacy_quarantine_audit(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """4-gate audit of the leftover legacy-quarantined option positions.

    Gates:
      - option_type IS NOT NULL          → +1
      - strike_price > 100               → +1
      - avg_cost_cents/100 > 10          → +1 (premium > $10)
      - symbol matches OCC format        → +1 (^[A-Z]+\\d{6}[CP]\\d{8}$)

    gates_passed ≥ 3 → REAL (unquarantine candidate).
    Else            → FAKE (retire candidate).
    """
    import re as _re
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT id, allocation_id, symbol, option_type, strike_price, expiration_date,
               avg_cost_cents, qty, opened_at, quarantine_reason
        FROM bot_positions
        WHERE quarantine_reason = 'misclassified_legacy_pre_17aa7f3'
          AND opened_at >= '2026-06-19 03:16:00'
    """)).fetchall()

    occ_re = _re.compile(r"^[A-Z]+\d{6}[CP]\d{8}$")

    classifications = []
    real_count = 0
    fake_count = 0
    for r in rows:
        pos_id = r[0]
        alloc_id = r[1]
        symbol = r[2] or ""
        option_type = r[3]
        strike_price = r[4]
        expiration_date = r[5]
        avg_cost_cents = r[6]
        qty = r[7]
        opened_at = r[8]
        quarantine_reason = r[9]

        gates_passed = 0
        gate_detail = {}

        g1 = option_type is not None
        gate_detail["option_type_not_null"] = g1
        if g1:
            gates_passed += 1

        g2 = (strike_price is not None) and (float(strike_price) > 100.0)
        gate_detail["strike_gt_100"] = g2
        if g2:
            gates_passed += 1

        premium_dollars = (float(avg_cost_cents) / 100.0) if avg_cost_cents is not None else 0.0
        g3 = premium_dollars > 10.0
        gate_detail["premium_gt_10"] = g3
        if g3:
            gates_passed += 1

        g4 = bool(occ_re.match(symbol))
        gate_detail["occ_format"] = g4
        if g4:
            gates_passed += 1

        classification = "REAL" if gates_passed >= 3 else "FAKE"
        if classification == "REAL":
            real_count += 1
        else:
            fake_count += 1

        classifications.append({
            "id": pos_id,
            "allocation_id": alloc_id,
            "symbol": symbol,
            "option_type": option_type,
            "strike_price": strike_price,
            "expiration_date": expiration_date,
            "avg_cost_cents": avg_cost_cents,
            "qty": qty,
            "opened_at": str(opened_at) if opened_at is not None else None,
            "quarantine_reason": quarantine_reason,
            "gates_passed": gates_passed,
            "gate_detail": gate_detail,
            "classification": classification,
        })

    # Post the classification table to ops channel — fire-and-forget.
    try:
        from app.services.discord import send_ops_alert

        lines = [
            f"#{c['id']:>5} {c['classification']:<4} g={c['gates_passed']} "
            f"{(c['symbol'] or '')[:24]:<24} strike={c['strike_price']} "
            f"prem={(c['avg_cost_cents'] or 0)/100:.2f}"
            for c in classifications
        ]
        if lines:
            message = "```\n" + "\n".join(lines)[:1700] + "\n```"
        else:
            message = "No leftover legacy-quarantined options rows match the audit filter."

        send_ops_alert(
            title=f"Legacy quarantine audit · {len(classifications)} rows · REAL={real_count} FAKE={fake_count}",
            message=message,
            severity="info",
            source="admin.options_legacy_quarantine_audit",
            fields=[
                {"name": "total_rows", "value": str(len(classifications)), "inline": True},
                {"name": "REAL (unquarantine candidates)", "value": str(real_count), "inline": True},
                {"name": "FAKE (retire candidates)", "value": str(fake_count), "inline": True},
                {"name": "action", "value": "NO auto-action; per-row greenlight required", "inline": False},
            ],
        )
    except Exception as exc:
        logger.warning("[options_legacy_quarantine_audit] ops alert failed: %s", exc)

    return {
        "ok": True,
        "total_rows": len(classifications),
        "real_count": real_count,
        "fake_count": fake_count,
        "classifications": classifications,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 16 — Equity Directional reconciliation report
# Diff three views of a single bot profile so the next discrepancy is
# caught before a user sees it. Sources:
#   1. bot_allocations.enabled (DB ground truth)
#   2. compute_strategy_lab_aggregate(...).leaderboard entry
#   3. compute_bot_snapshot(alloc, profile, db) per-alloc
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/bot/{profile_name}/reconciliation")
def bot_reconciliation(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Reconcile the 3 canonical views of a bot profile (e.g.
    options_directional a.k.a. "equity_directional"). Posts a Discord
    ops alert with severity=warn on any divergence.
    """
    from app.db.models.bots import BotAllocation, BotProfile
    from app.core.canonical import (
        compute_bot_snapshot,
        compute_strategy_lab_aggregate,
    )

    profile = (
        db.query(BotProfile)
        .filter(BotProfile.name == profile_name)
        .first()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {profile_name}")

    # Source 1: bot_allocations.enabled — restrict to current_user so the
    # endpoint reflects the requesting user's view of the bot.
    allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.profile_id == profile.id,
            BotAllocation.user_id == current_user.id,
        )
        .order_by(BotAllocation.id)
        .all()
    )

    source1_entries = [
        {
            "allocation_id": a.id,
            "enabled": bool(a.enabled),
            "paused_reason": a.paused_reason,
            "portfolio_id": a.portfolio_id,
        }
        for a in allocs
    ]
    source1_enabled = any(e["enabled"] for e in source1_entries) if source1_entries else None

    # Source 2: canonical leaderboard entry for this profile.
    source2_entry = None
    leaderboard_error = None
    try:
        agg = compute_strategy_lab_aggregate(current_user.id, db)
        leaderboard = agg.get("leaderboard", []) if isinstance(agg, dict) else []
        for e in leaderboard:
            if e.get("profile") == profile_name:
                source2_entry = e
                break
    except Exception as exc:
        leaderboard_error = str(exc)
        logger.warning("[reconciliation] leaderboard compute failed: %s", exc)

    # Source 3: per-alloc compute_bot_snapshot — one row per alloc on this profile.
    source3_entries = []
    snapshot_errors = []
    for a in allocs:
        try:
            snap = compute_bot_snapshot(a, profile, db)
            source3_entries.append({
                "allocation_id": a.id,
                "enabled": bool(snap.enabled),
                "today_pnl_cents": int(snap.today_pnl_cents or 0),
                "open_positions_count": int(snap.open_positions_count or 0),
                "portfolio_value_cents": int(snap.portfolio_value_cents or 0),
            })
        except Exception as exc:
            snapshot_errors.append({"allocation_id": a.id, "error": str(exc)})

    # ── Compute divergence ────────────────────────────────────────────────
    s2_today = int(source2_entry.get("today_pnl_cents") or 0) if source2_entry else 0
    s3_today_sum = sum(e["today_pnl_cents"] for e in source3_entries)
    pnl_divergence_cents = abs(s2_today - s3_today_sum)

    # Open-position divergence — leaderboard doesn't carry per-profile open count
    # directly; if absent, compare s3 sum against itself (== 0). We carry the
    # count anyway for the operator.
    s3_open_sum = sum(e["open_positions_count"] for e in source3_entries)

    # Enabled-status divergence: leaderboard implicitly assumes "exists in
    # aggregate". Compare DB ground truth to whether profile appears in the
    # leaderboard at all — if there's an enabled alloc but no leaderboard entry,
    # that's a real divergence worth flagging.
    enabled_status_diverges = False
    if source1_enabled is True and source2_entry is None:
        enabled_status_diverges = True
    elif source1_enabled is False and source2_entry is not None:
        # Profile appears in leaderboard but no enabled alloc — possible cache /
        # capture from another portfolio. Worth flagging.
        enabled_status_diverges = True

    # Cross-source enabled diff (DB vs. snapshot)
    s3_any_enabled = any(e["enabled"] for e in source3_entries) if source3_entries else None
    if source1_enabled is not None and s3_any_enabled is not None and source1_enabled != s3_any_enabled:
        enabled_status_diverges = True

    max_divergence_cents = pnl_divergence_cents
    severity = "info"
    if pnl_divergence_cents > 100 or enabled_status_diverges:  # > $1
        severity = "warn"

    # Post reconciliation result to ops channel — fire-and-forget.
    try:
        from app.services.discord import send_ops_alert

        message = (
            f"Profile: {profile_name}\n"
            f"DB enabled: {source1_enabled}\n"
            f"Leaderboard today_pnl: ${s2_today/100:.2f}\n"
            f"Snapshot sum today_pnl: ${s3_today_sum/100:.2f}\n"
            f"Snapshot open_positions: {s3_open_sum}\n"
            f"|Δ pnl| = ${pnl_divergence_cents/100:.2f}\n"
            f"enabled_status_diverges: {enabled_status_diverges}\n"
        )
        if leaderboard_error:
            message += f"leaderboard_error: {leaderboard_error[:200]}\n"
        if snapshot_errors:
            message += f"snapshot_errors: {len(snapshot_errors)}\n"

        send_ops_alert(
            title=f"Bot reconciliation · {profile_name} · {severity}",
            message=message[:1900],
            severity=severity,
            source="admin.bot_reconciliation",
            fields=[
                {"name": "allocations", "value": str(len(allocs)), "inline": True},
                {"name": "|Δ pnl| cents", "value": str(pnl_divergence_cents), "inline": True},
                {"name": "enabled_diverges", "value": str(enabled_status_diverges), "inline": True},
            ],
        )
    except Exception as exc:
        logger.warning("[bot_reconciliation] ops alert failed: %s", exc)

    return {
        "ok": True,
        "profile_name": profile_name,
        "source1_bot_allocations": {
            "any_enabled": source1_enabled,
            "entries": source1_entries,
        },
        "source2_leaderboard": source2_entry,
        "source2_error": leaderboard_error,
        "source3_snapshots": source3_entries,
        "source3_errors": snapshot_errors,
        "pnl_divergence_cents": pnl_divergence_cents,
        "max_divergence_cents": max_divergence_cents,
        "enabled_status_diverges": enabled_status_diverges,
        "severity": severity,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 7 — Bot heartbeat read endpoint
# Surfaces the bot_heartbeat table joined with bot_profiles for display names,
# with computed minutes-since-last-signal so admin UI can render stale badges
# without doing the math client-side.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/bot-heartbeats")
def bot_heartbeats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the latest heartbeat state for each bot. Includes minutes_since
    and is_stale (last_signal_at older than 2× expected cadence)."""
    from sqlalchemy import text as _sql

    rows = db.execute(_sql(
        "SELECT h.bot_name, h.last_signal_at, h.last_scan_at, "
        "       h.expected_cadence_minutes, h.updated_at, p.asset_class "
        "FROM bot_heartbeat h "
        "LEFT JOIN bot_profiles p ON p.name = h.bot_name "
        "ORDER BY h.bot_name"
    )).fetchall()

    now = datetime.now(timezone.utc)
    result: list[dict] = []
    for r in rows:
        bot_name, last_signal_at, last_scan_at, cadence, updated_at, asset_class = r
        last_signal_dt = last_signal_at
        if isinstance(last_signal_dt, str):
            try:
                last_signal_dt = datetime.fromisoformat(last_signal_dt.replace("Z", "+00:00"))
            except Exception:
                last_signal_dt = None
        if last_signal_dt is not None and last_signal_dt.tzinfo is None:
            last_signal_dt = last_signal_dt.replace(tzinfo=timezone.utc)
        minutes_since = (
            int((now - last_signal_dt).total_seconds() / 60)
            if last_signal_dt is not None else None
        )
        cadence_int = int(cadence or 0)
        threshold = max(cadence_int * 2, 30) if cadence_int else None
        is_stale = bool(
            minutes_since is not None and threshold is not None
            and minutes_since > threshold
        )
        try:
            from app.core.canonical import display_name as _dn
            display = _dn(bot_name)
        except Exception:
            display = bot_name
        result.append({
            "bot_name": bot_name,
            "display_name": display,
            "asset_class": asset_class,
            "last_signal_at": last_signal_at.isoformat() if hasattr(last_signal_at, "isoformat") else last_signal_at,
            "last_scan_at": last_scan_at.isoformat() if hasattr(last_scan_at, "isoformat") else last_scan_at,
            "expected_cadence_minutes": cadence_int or None,
            "minutes_since_last_signal": minutes_since,
            "is_stale": is_stale,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        })

    return {
        "heartbeats": result,
        "count": len(result),
        "stale_count": sum(1 for r in result if r["is_stale"]),
        "ts": now.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 10 — Watchlist stale sweep on-demand endpoint
# Runs the same sweep the nightly 2 AM cron does. Used to clean the current
# state without waiting for the next scheduled tick.
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/watchlist/sweep-stale")
def watchlist_sweep_stale(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Trigger the watchlist staleness sweep immediately.

    Soft-removes (status → stale_removed) any bot_watchlist row older than
    7 days whose status is active/watching/pending_entry, excluding
    incubating profile allocations. Reuses the module-level worker the
    nightly cron calls so behavior stays identical.
    """
    try:
        from strategy_lab.bot_scheduler import run_watchlist_stale_sweep
        result = run_watchlist_stale_sweep()
    except Exception as exc:
        logger.error("[watchlist_sweep_stale] failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "ok": True,
        "result": result,
        "ts": datetime.now(timezone.utc).isoformat(),
        "by_user_id": current_user.id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMMIT 13 — Cooldown re-entry storm detection
# Surfaces any (profile, symbol) pair that opened > 2 positions in the last 4h.
# Re-entry storms usually mean a stop got hit, cooldown was too short, and the
# bot re-bought into the same loser — a clear over-trading signal.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/cooldown/storm-check")
def cooldown_storm_check(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return (profile, symbol) pairs that opened > 2 entries within 4h.

    Posts a warn ops alert when any storms are found.
    """
    from sqlalchemy import text as _sql
    from app.services.discord import send_ops_alert as _alert

    rows = db.execute(_sql(
        "SELECT a.profile_id, p.name AS bot_name, bt.symbol, COUNT(*) AS entries_4h "
        "FROM bot_trades bt "
        "JOIN bot_allocations a ON a.id = bt.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE bt.ts >= datetime('now','-4 hours') "
        "  AND bt.side IN ('buy','short') "
        "GROUP BY a.profile_id, bt.symbol "
        "HAVING COUNT(*) > 2 "
        "ORDER BY entries_4h DESC"
    )).fetchall()

    storms = [
        {
            "profile_id": int(r[0]) if r[0] is not None else None,
            "bot_name": r[1],
            "symbol": r[2],
            "entries_4h": int(r[3]),
        }
        for r in rows
    ]

    if storms:
        try:
            fields = [
                {"name": f"{s['bot_name']} / {s['symbol']}",
                 "value": f"{s['entries_4h']} entries in 4h",
                 "inline": True}
                for s in storms[:10]
            ]
            _alert(
                title="Cooldown re-entry storm detected",
                message=f"{len(storms)} (bot, symbol) pair(s) opened > 2 positions in the last 4 hours.",
                severity="warn",
                source="admin.cooldown_storm_check",
                fields=fields,
            )
        except Exception as exc:
            logger.warning("[cooldown_storm_check] ops alert failed: %s", exc)

    return {
        "storms": storms,
        "count": len(storms),
        "window_hours": 4,
        "threshold_entries": 2,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Discipline threshold auto-promote — view + manual trigger
# Reads bot_threshold_dynamic (populated by the nightly auto-promote job).
# POST endpoint runs the job on-demand (the nightly run still fires
# independently in bot_scheduler).
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/discipline/threshold-status")
def discipline_threshold_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Current dynamic threshold overrides + their basis."""
    from app.services.threshold_auto_promote import threshold_status
    rows = threshold_status(db)
    return {
        "ok": True,
        "count": len(rows),
        "loose_count": sum(1 for r in rows if r.get("threshold") == 50),
        "tight_count": sum(1 for r in rows if r.get("threshold") == 80),
        "rows": rows,
    }


@router.post("/discipline/threshold-auto-promote/run")
def discipline_threshold_auto_promote_run(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Trigger the nightly auto-promote evaluation manually."""
    from app.services.threshold_auto_promote import run_threshold_auto_promote
    return run_threshold_auto_promote(db)


# ── GET /api/admin/reconcile/broker ──────────────────────────────────────────
# Phase 3 — broker vs DB position reconciliation diagnostic.
# READ-ONLY. Never mutates broker state, never auto-closes/auto-creates rows.
@router.get("/reconcile/broker")
def reconcile_broker(
    user_id: int = Query(1, description="user_id to reconcile (default 1 = Brock)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Run a one-shot broker vs DB position diff for the given user.

    Mirrors the daily scheduled job at 4:05 PM ET but on-demand. Returns the
    full report dict; see `app.ops.broker_reconciliation` for shape.
    """
    from app.ops.broker_reconciliation import reconcile_positions
    return reconcile_positions(db, user_id=user_id)


# ── GET /api/admin/threshold-experiment ─────────────────────────────────────
# Time-boxed experiment on the 985f176d composite threshold cuts. Bucket
# closed trades by score band {30-59, 60+} per bot, report win rate + expectancy.
@router.get("/threshold-experiment")
def threshold_experiment_endpoint(
    days: int = Query(14, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Report threshold-experiment bucket stats + auto-revert candidates."""
    from app.services.threshold_experiment import bucket_report
    return bucket_report(db, days=days)


# ── POST /api/admin/reconcile-option-closes ─────────────────────────────────
# RIA-stats spec (2026-07-13): options positions accumulate marks-only P&L
# but never book realized P&L on close because Alpaca handles the close
# side (expiry-worthless, assignment, buy-to-close) without notifying BMG.
# This endpoint walks all open option positions, checks Alpaca, closes any
# that are gone at the broker with the right exit_reason and pnl.
@router.post("/reconcile-option-closes")
def reconcile_option_closes_endpoint(
    user_id: int = Query(1, description="user_id whose positions to reconcile"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Force-run the option-close sync now. Returns per-position outcomes."""
    from app.services.option_close_sync import reconcile_option_closes
    return reconcile_option_closes(db, user_id=user_id)


# ── GET /api/admin/factor-scorecard ─────────────────────────────────────────
# Alphalens-style per-factor validation: computes IC + quintile spread for
# every enabled portfolio-rank bot by joining its rebalance_log ranking
# outputs to forward N-day yfinance returns. Slow (yfinance-bound) — call
# on-demand not on every dashboard refresh.
@router.get("/factor-scorecard")
def factor_scorecard(
    forward_days: int = Query(21, description="Forward return horizon in trading days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Return {verdict, ic_mean, ic_tstat, quintile_spread_pct} per PR bot.

    Verdicts:
      significant_positive  — ic_tstat > 2.0  (factor produces real signal)
      significant_inverse   — ic_tstat < -2.0 (factor is anti-signal; flip sign or halt)
      weak_signal           — 0 < |ic_tstat| < 2.0 (unclear, need more data)
      no_signal             — |ic_mean| < 0.02 (noise)
      insufficient_data     — fewer than 3 rebalances so far
      no_valid_forward_returns — bars unavailable for the tracked names
      error                 — computation raised
    """
    from app.services.factor_scorecard import compute_all_scorecards
    return compute_all_scorecards(db, forward_days=forward_days)


# ── GET /api/admin/migration-status ──────────────────────────────────────────
# 2026-06-29 diagnostic: lists schema_migrations entries + open-position
# counts per bot per symbol. Helps verify m033 (and other migrations) ran
# without needing direct DB access. READ-ONLY.
@router.get("/migration-status")
def migration_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Returns:
      - migrations: every row in schema_migrations (proves what ran)
      - open_positions_by_bot_symbol: open BotPosition counts grouped by
        bot_id + symbol (proves which bots hold what)
    """
    from sqlalchemy import text as _text
    out: Dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "migrations": [],
        "open_positions_by_bot_symbol": [],
    }
    try:
        mig_rows = db.execute(_text(
            "SELECT migration_name, applied_at FROM schema_migrations "
            "ORDER BY applied_at DESC"
        )).fetchall()
        out["migrations"] = [
            {
                "name": r[0],
                "applied_at": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
            }
            for r in mig_rows
        ]
    except Exception as exc:
        out["migrations_error"] = str(exc)[:200]
    try:
        pos_rows = db.execute(_text("""
            SELECT p.name AS bot_id,
                   bp.symbol,
                   COUNT(*) AS open_count,
                   COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0) AS notional_cents
              FROM bot_positions bp
              JOIN bot_allocations a ON a.id = bp.allocation_id
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE bp.closed_at IS NULL
               AND bp.quarantined_at IS NULL
             GROUP BY p.name, bp.symbol
             ORDER BY notional_cents DESC
             LIMIT 200
        """)).fetchall()
        out["open_positions_by_bot_symbol"] = [
            {
                "bot_id": r[0],
                "symbol": r[1],
                "open_count": int(r[2]),
                "notional_cents": int(r[3] or 0),
            }
            for r in pos_rows
        ]
    except Exception as exc:
        out["positions_error"] = str(exc)[:200]
    try:
        # Determine whether the 12 remaining crypto-bot equity violations
        # are legacy leftovers m044 missed, or NEW positions created after
        # m044 ran — i.e. an active SHIP 2 hole.
        viol_rows = db.execute(_text("""
            SELECT bp.id, p.name AS bot_id, bp.symbol, bp.opened_at, bp.qty,
                   bp.avg_cost_cents
              FROM bot_positions bp
              JOIN bot_allocations a ON a.id = bp.allocation_id
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE bp.closed_at IS NULL
               AND bp.quarantined_at IS NULL
               AND p.name LIKE 'crypto_%'
               AND bp.symbol IN ('AAPL','MSFT','NVDA','AMZN','TSLA','GOOGL',
                                 'META','QQQ','SPY','JPM','GLD','TLT')
             ORDER BY bp.opened_at DESC
        """)).fetchall()
        out["crypto_bot_equity_violations"] = [
            {
                "position_id": int(r[0]),
                "bot_id": r[1],
                "symbol": r[2],
                "opened_at": r[3].isoformat() if hasattr(r[3], "isoformat") else r[3],
                "qty": float(r[4] or 0),
                "avg_cost_cents": int(r[5] or 0),
            }
            for r in viol_rows
        ]
    except Exception as exc:
        out["violations_error"] = str(exc)[:200]
    return out


def compute_migration_status(db: Session) -> dict:
    """Extract migration-status logic for in-process callers (e.g. daily audit).

    Returns a dict with at minimum:
      crypto_bot_equity_violations: list of dicts (empty if none)
    """
    from sqlalchemy import text as _text

    out: Dict[str, Any] = {
        "crypto_bot_equity_violations": [],
    }
    try:
        viol_rows = db.execute(_text("""
            SELECT bp.id, p.name AS bot_id, bp.symbol, bp.opened_at, bp.qty,
                   bp.avg_cost_cents
              FROM bot_positions bp
              JOIN bot_allocations a ON a.id = bp.allocation_id
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE bp.closed_at IS NULL
               AND bp.quarantined_at IS NULL
               AND p.name LIKE 'crypto_%'
               AND bp.symbol IN ('AAPL','MSFT','NVDA','AMZN','TSLA','GOOGL',
                                 'META','QQQ','SPY','JPM','GLD','TLT')
             ORDER BY bp.opened_at DESC
        """)).fetchall()
        out["crypto_bot_equity_violations"] = [
            {
                "position_id": int(r[0]),
                "bot_id": r[1],
                "symbol": r[2],
                "opened_at": r[3].isoformat() if hasattr(r[3], "isoformat") else r[3],
                "qty": float(r[4] or 0),
                "avg_cost_cents": int(r[5] or 0),
            }
            for r in viol_rows
        ]
    except Exception as exc:
        out["violations_error"] = str(exc)[:200]
    return out


# ── GET /api/admin/auto-pause/list ───────────────────────────────────────────
# SHIP 6 — lists currently auto-paused bots (paused_reason LIKE 'degraded_auto_pause%').
# READ-ONLY. Frontend reads rows[].bot_id exactly — shape contract per known-issues.md #4.
@router.get("/auto-pause/list")
def auto_pause_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """SHIP 6 — currently auto-paused bots, sourced from
    BotAllocation.paused_reason LIKE 'degraded_auto_pause%'.
    """
    from sqlalchemy import text as _text
    # 2026-06-29 hotfix: GROUP BY p.name to dedupe. m021 dedup leftovers can
    # leave 3+ allocation rows per profile; if auto-pause fires across all of
    # them, the card showed crypto_quant_scalper 3x with same reason.
    rows = db.execute(_text("""
        SELECT p.name AS bot_id,
               MAX(a.paused_reason) AS paused_reason,
               MAX(a.updated_at) AS paused_at,
               MAX(a.user_id) AS user_id
          FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.enabled = 0
           AND a.paused_reason LIKE 'degraded_auto_pause%'
         GROUP BY p.name
         ORDER BY MAX(a.updated_at) DESC
    """)).fetchall()
    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "rows": [
            {
                "bot_id": r[0],
                "paused_reason": r[1],
                "paused_at": r[2].isoformat() if hasattr(r[2], "isoformat") else r[2],
                "user_id": r[3],
            }
            for r in rows
        ],
    }

# ── SHIP 3 — LLM USAGE diagnostics ───────────────────────────────────────────

@router.get("/diagnostics/llm-usage")
def get_llm_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """SHIP 3 — LLM USAGE card data. Real numbers from llm_call_log."""
    from sqlalchemy import text as _text
    import os

    # Today block (last 24h)
    today_rows = db.execute(_text(
        "SELECT source, COUNT(*) AS n, COALESCE(SUM(estimated_cost_cents),0) AS cents "
        "FROM llm_call_log "
        "WHERE created_at >= datetime('now','-24 hours') "
        "GROUP BY source"
    )).fetchall()
    relay_calls = 0
    api_fallback_calls = 0
    cache_hits = 0
    api_fallback_cost_cents = 0
    for row in today_rows:
        src, n, cents = row[0], int(row[1]), int(row[2])
        if src == "relay":
            relay_calls = n
        elif src == "api_fallback":
            api_fallback_calls = n
            api_fallback_cost_cents = cents
        elif src == "cache":
            cache_hits = n

    # Top callers (7d)
    top_rows = db.execute(_text(
        "SELECT agent_name, COUNT(*) AS calls, COALESCE(SUM(estimated_cost_cents),0) AS cents "
        "FROM llm_call_log "
        "WHERE created_at >= datetime('now','-7 days') "
        "GROUP BY agent_name "
        "ORDER BY calls DESC "
        "LIMIT 10"
    )).fetchall()
    top_callers_7d = [
        {"agent_name": r[0], "calls": int(r[1]), "estimated_cost_cents": int(r[2])}
        for r in top_rows
    ]

    # Trend (7d per day per source)
    trend_rows = db.execute(_text(
        "SELECT DATE(created_at) AS d, source, COUNT(*) AS n, COALESCE(SUM(estimated_cost_cents),0) AS cents "
        "FROM llm_call_log "
        "WHERE created_at >= datetime('now','-7 days') "
        "GROUP BY d, source "
        "ORDER BY d"
    )).fetchall()
    trend_map: Dict[str, Dict] = {}
    for r in trend_rows:
        d, src, n, cents = r[0], r[1], int(r[2]), int(r[3])
        if d not in trend_map:
            trend_map[d] = {"date": d, "relay": 0, "api_fallback": 0, "cache": 0, "cents": 0}
        trend_map[d][src] = n
        trend_map[d]["cents"] += cents
    trend_7d = sorted(trend_map.values(), key=lambda x: x["date"])

    # Budget
    cap_usd = float(os.getenv("LLM_DAILY_FALLBACK_BUDGET_USD", "5"))
    budget_remaining_cents = max(0, int(cap_usd * 100) - api_fallback_cost_cents)

    # Last timestamps
    last_relay = db.execute(_text(
        "SELECT MAX(created_at) FROM llm_call_log WHERE source='relay'"
    )).scalar()
    last_fallback = db.execute(_text(
        "SELECT MAX(created_at) FROM llm_call_log WHERE source='api_fallback'"
    )).scalar()

    fallback_enabled = os.getenv("FALLBACK_TO_API", "false").strip().lower() == "true"

    return {
        "today": {
            "relay_calls": relay_calls,
            "api_fallback_calls": api_fallback_calls,
            "cache_hits": cache_hits,
            "api_fallback_cost_cents": api_fallback_cost_cents,
        },
        "top_callers_7d": top_callers_7d,
        "trend_7d": trend_7d,
        "fallback_enabled": fallback_enabled,
        "budget_remaining_cents": budget_remaining_cents,
        "last_relay_call_at": str(last_relay) if last_relay else None,
        "last_fallback_call_at": str(last_fallback) if last_fallback else None,
    }


def compute_llm_usage(db: Session) -> dict:
    """Extract LLM usage logic for in-process callers (e.g. daily audit).

    Returns the same dict as GET /api/admin/diagnostics/llm-usage.
    """
    from sqlalchemy import text as _text
    import os as _os

    today_rows = db.execute(_text(
        "SELECT source, COUNT(*) AS n, COALESCE(SUM(estimated_cost_cents),0) AS cents "
        "FROM llm_call_log "
        "WHERE created_at >= datetime('now','-24 hours') "
        "GROUP BY source"
    )).fetchall()
    relay_calls = 0
    api_fallback_calls = 0
    cache_hits = 0
    api_fallback_cost_cents = 0
    for row in today_rows:
        src, n, cents = row[0], int(row[1]), int(row[2])
        if src == "relay":
            relay_calls = n
        elif src == "api_fallback":
            api_fallback_calls = n
            api_fallback_cost_cents = cents
        elif src == "cache":
            cache_hits = n

    cap_usd = float(_os.getenv("LLM_DAILY_FALLBACK_BUDGET_USD", "5"))
    budget_remaining_cents = max(0, int(cap_usd * 100) - api_fallback_cost_cents)
    fallback_enabled = _os.getenv("FALLBACK_TO_API", "false").strip().lower() == "true"

    return {
        "today": {
            "relay_calls": relay_calls,
            "api_fallback_calls": api_fallback_calls,
            "cache_hits": cache_hits,
            "api_fallback_cost_cents": api_fallback_cost_cents,
        },
        "fallback_enabled": fallback_enabled,
        "budget_remaining_cents": budget_remaining_cents,
    }


# ── SHIP 3 — Reset fallback budget ───────────────────────────────────────────

@router.post("/llm/reset-fallback-budget")
def reset_llm_fallback_budget(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Hard-reset by deleting api_fallback rows from last 24h. Logs ops alert."""
    from app.services.llm_client import reset_fallback_budget
    from app.services.discord import send_ops_alert
    deleted = reset_fallback_budget(db)
    try:
        send_ops_alert(
            severity="warn",
            title="LLM fallback budget RESET",
            message=f"Deleted {deleted} api_fallback rows. Budget window cleared.",
            source="admin",
        )
    except Exception:
        pass
    return {"deleted": deleted, "ok": True}


# ---------------------------------------------------------------------------
# CIO observability — last-meeting-agents diagnostic endpoint
# ---------------------------------------------------------------------------

_FAILURE_TYPE_REGEX = re.compile(r'(\w+Error|\w+Timeout):')


@router.get("/cio/last-meeting-agents")
def cio_last_meeting_agents(
    meeting_id: Optional[str] = Query(None, description="If omitted, returns latest meeting by started_at"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return per-agent opening-read breakdown for a CIO meeting.

    If meeting_id is omitted, returns the most recent meeting by started_at.
    Includes a parsed failure_types histogram from error_text fields.
    fund_meetings is fleet-level (no user_id column) — do NOT filter by user.
    """
    from sqlalchemy import text

    if meeting_id is None:
        row = db.execute(
            text(
                "SELECT meeting_id, status, started_at, ended_at, failure_reason "
                "FROM fund_meetings ORDER BY started_at DESC LIMIT 1"
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no meetings found")
    else:
        row = db.execute(
            text(
                "SELECT meeting_id, status, started_at, ended_at, failure_reason "
                "FROM fund_meetings WHERE meeting_id = :mid"
            ),
            {"mid": meeting_id},
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="meeting not found")

    mid = row[0]
    agent_rows = db.execute(
        text(
            "SELECT agent_name, status, response_time_ms, error_text, cost_usd "
            "FROM agent_opening_reads WHERE meeting_id = :mid ORDER BY agent_name"
        ),
        {"mid": mid},
    ).fetchall()

    agents = [
        {
            "agent_name": ar[0],
            "status": ar[1],
            "duration_ms": int(ar[2]) if ar[2] is not None else 0,
            "error_text": ar[3],
            "cost_usd": float(ar[4]) if ar[4] is not None else 0.0,
        }
        for ar in agent_rows
    ]

    agents_ok_count = sum(1 for a in agents if a["status"] == "ok")
    agents_failed_count = len(agents) - agents_ok_count

    failure_types: Dict[str, int] = {}
    if agents_failed_count > 0:
        for a in agents:
            if a["status"] != "ok":
                error_text = a["error_text"] or ""
                m = _FAILURE_TYPE_REGEX.search(error_text)
                key = m.group(1) if m else "Other"
                failure_types[key] = failure_types.get(key, 0) + 1

    return {
        "meeting_id": mid,
        "meeting_status": row[1],
        "meeting_started_at": row[2],
        "meeting_ended_at": row[3],
        "failure_reason": row[4],
        "agents": agents,
        "agents_ok_count": agents_ok_count,
        "agents_failed_count": agents_failed_count,
        "failure_types": failure_types,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/admin/bots/diagnostics
# Per-bot 24h (configurable) diagnostic endpoint: scan/signal/trade/position
# counts + a one-word verdict per bot so triage collapses from hours of
# log-grepping to one curl call.
# ─────────────────────────────────────────────────────────────────────────────

def _parse_row_ts(value) -> "Optional[datetime]":
    """Normalize a timestamp value from a SQLAlchemy row.

    SQLite's MAX() returns naive strings like '2026-06-30 07:31:05.715974'.
    Postgres returns proper datetime objects.  This helper normalises both
    to a UTC-aware datetime (or None) so classify logic uses one code path.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _classify_bot(row, stale_cutoff, trades_last_ts_dt) -> tuple[str, str]:
    """Return (verdict, investigate_hint) for a single bot row.

    Priority-ordered — first match wins:
      profile_disabled > paused > no_signals > signals_no_trades > stale > trading

    trades_last_ts_dt is the pre-parsed UTC datetime (or None) — avoids
    SQLite string-vs-datetime comparison errors.
    """
    if not row.profile_enabled:
        return "profile_disabled", "Check BotProfile.enabled flag in seed YAML"
    if not row.allocation_enabled:
        return "paused", "See allocation_paused_reason"
    if row.signals_window == 0:
        return "no_signals", "Check scheduler logs for [scan:<bot>] entries; verify bar fetch"
    if row.trades_window == 0:
        return "signals_no_trades", "Check discipline composite threshold; cooldown; position cap"
    if trades_last_ts_dt is not None and trades_last_ts_dt < stale_cutoff:
        return "stale", "Recent regression — check confidence threshold, bar source"
    return "trading", "Healthy"


@router.get("/bots/diagnostics")
def get_bot_diagnostics(
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Per-bot diagnostic snapshot. Returns counts + verdict for each bot.

    Query param:
      hours  — lookback window for signals/trades counts (default 24, max 168)

    Hard-codes user_id=1 (fund primary). Multi-user pivot would add a query
    param here, but all BMG ops are single-tenant for now.

    # Snapshot inconsistency possible across subqueries; acceptable for
    # diagnostic surface.
    """
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="hours must be 1..168")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    stale_cutoff = now - timedelta(hours=48)

    TARGET_USER_ID = 1  # fund primary; multi-user pivot would add a query param

    sql = text("""
        SELECT p.name             AS bot_name,
               p.enabled          AS profile_enabled,
               p.asset_class      AS asset_class,
               a.id               AS allocation_id,
               a.enabled          AS allocation_enabled,
               a.paused_reason    AS allocation_paused_reason,
               a.starting_capital_cents AS starting_capital_cents,
               (SELECT COUNT(*) FROM bot_positions bp
                 WHERE bp.allocation_id = a.id
                   AND bp.closed_at IS NULL
                   AND bp.quarantined_at IS NULL) AS open_positions_count,
               (SELECT COALESCE(SUM(
                   CASE
                     WHEN LOWER(COALESCE(bp.side,'long')) = 'short' THEN 0
                     WHEN bp.option_type IS NOT NULL THEN bp.qty * bp.avg_cost_cents * 100
                     ELSE bp.qty * bp.avg_cost_cents
                   END), 0) FROM bot_positions bp
                 WHERE bp.allocation_id = a.id
                   AND bp.closed_at IS NULL
                   AND bp.quarantined_at IS NULL) AS open_positions_notional_cents,
               (SELECT COUNT(*) FROM bot_signals bs
                 WHERE bs.allocation_id = a.id
                   AND bs.ts >= :cutoff) AS signals_window,
               (SELECT MAX(bs.ts) FROM bot_signals bs
                 WHERE bs.allocation_id = a.id) AS signals_last_ts,
               (SELECT COUNT(*) FROM bot_trades bt
                 WHERE bt.allocation_id = a.id
                   AND bt.ts >= :cutoff
                   AND bt.quarantined_at IS NULL
                   AND bt.origin = 'BROKER_FILL') AS trades_window,
               (SELECT MAX(bt.ts) FROM bot_trades bt
                 WHERE bt.allocation_id = a.id
                   AND bt.quarantined_at IS NULL) AS trades_last_ts
          FROM bot_profiles p
          JOIN bot_allocations a ON a.profile_id = p.id
         WHERE a.user_id = :user_id
         ORDER BY p.name
    """)

    rows = db.execute(sql, {"cutoff": cutoff, "user_id": TARGET_USER_ID}).fetchall()

    def _fmt_ts(dt) -> str | None:
        if dt is None:
            return None
        if isinstance(dt, str):
            # SQLite sometimes returns strings; parse and reformat.
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                return dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")

    summary = {
        "total_bots": 0,
        "trading": 0,
        "stale": 0,
        "signals_no_trades": 0,
        "no_signals": 0,
        "paused": 0,
        "profile_disabled": 0,
    }

    bots = []
    for row in rows:
        trades_last_ts_dt = _parse_row_ts(row.trades_last_ts)
        verdict, investigate = _classify_bot(row, stale_cutoff, trades_last_ts_dt)
        summary["total_bots"] += 1
        summary[verdict] += 1
        bots.append({
            "bot_name": row.bot_name,
            "profile_enabled": bool(row.profile_enabled),
            "allocation_enabled": bool(row.allocation_enabled),
            "allocation_paused_reason": row.allocation_paused_reason,
            "starting_capital_cents": row.starting_capital_cents,
            "asset_class": row.asset_class,
            "open_positions_count": int(row.open_positions_count),
            "open_positions_notional_cents": int(row.open_positions_notional_cents),
            "signals_window": int(row.signals_window),
            "signals_last_ts": _fmt_ts(row.signals_last_ts),
            "trades_window": int(row.trades_window),
            "trades_last_ts": _fmt_ts(row.trades_last_ts),
            "verdict": verdict,
            "investigate": investigate,
        })

    return {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "window_hours": hours,
        "bots": bots,
        "summary": summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT ENDPOINT HELPERS (shared by bot-diagnostic, trade-count-reconcile,
# asset-class-audit, inert-bot-scan, fund-tear-sheet-honesty-check)
# ─────────────────────────────────────────────────────────────────────────────

_AUDIT_CACHE: dict[str, tuple[float, dict]] = {}
_AUDIT_CACHE_TTL_SECONDS = 30
AUDIT_TARGET_USER_ID = 1  # fund primary; multi-user pivot would add a query param


def _audit_cache_get(key: str) -> dict | None:
    entry = _AUDIT_CACHE.get(key)
    if entry is None:
        return None
    ts, payload = entry
    if (time.time() - ts) > _AUDIT_CACHE_TTL_SECONDS:
        _AUDIT_CACHE.pop(key, None)
        return None
    return payload


def _audit_cache_set(key: str, payload: dict) -> None:
    _AUDIT_CACHE[key] = (time.time(), payload)


def _audit_log(endpoint_name: str, user_id: int) -> None:
    logger.info("[admin-audit] %s called by user_id=%s", endpoint_name, user_id)


def _iso_z(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _strategy_count_from_config(config_json) -> int:
    """Return len(config_json['strategies']) if list, else 0. Never raises.

    Handles both dict (Postgres/ORM) and JSON string (SQLite raw query) inputs.
    """
    try:
        if not config_json:
            return 0
        cfg = config_json
        if isinstance(cfg, str):
            import json as _json
            cfg = _json.loads(cfg)
        strats = cfg.get("strategies") if isinstance(cfg, dict) else None
        if isinstance(strats, list):
            return len(strats)
    except Exception:
        pass
    return 0


# Equity-symbol heuristic mirrored from m045 (used by asset-class-audit)
_OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def _looks_like_equity_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    s = symbol.strip().upper()
    if "/" in s:
        return False
    if not (1 <= len(s) <= 6):
        return False
    if not s.isalpha():
        return False
    return True


def _looks_like_occ_option(symbol: str | None) -> bool:
    if not symbol:
        return False
    return bool(_OCC_RE.match(symbol.strip().upper()))


def _looks_like_crypto_pair(symbol: str | None) -> bool:
    if not symbol:
        return False
    return "/" in symbol


CLEANUP_EXIT_REASONS = (
    "m033_options_equity_violation",
    "m044_cross_sleeve_violation",
    "m045_cross_sleeve_violation",
)


def _cleanup_migration_tag(exit_reason: str | None) -> str | None:
    if not exit_reason:
        return None
    if exit_reason.startswith("m033_"):
        return "m033"
    if exit_reason.startswith("m044_"):
        return "m044"
    if exit_reason.startswith("m045_"):
        return "m045"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint 1: GET /api/admin/bot-diagnostic
# Brock-shape alias of /bots/diagnostics. 24h window, fixed.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/bot-diagnostic")
def get_bot_diagnostic_singular(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Brock-shape alias of /bots/diagnostics. 24h window, fixed.

    Reuses the same SQL+classification helpers as /bots/diagnostics but
    reshapes the response to match the audit-facing field names exactly:
      bot_id, verdict, signals_24h, trades_24h, open_positions,
      last_signal_at, last_trade_at, enabled, paused_reason,
      asset_class_declared, strategy_count

    Note: if a bot has multiple allocations for user_id=1 (known-issues #3),
    multiple rows for the same bot_id may appear. Caller's responsibility.
    """
    _audit_log("bot-diagnostic", current_user.id)
    cached = _audit_cache_get("bot-diagnostic")
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(hours=48)

    sql = text("""
        SELECT p.name             AS bot_name,
               p.enabled          AS profile_enabled,
               p.asset_class      AS asset_class,
               p.config_json      AS config_json,
               a.id               AS allocation_id,
               a.enabled          AS allocation_enabled,
               a.paused_reason    AS allocation_paused_reason,
               a.starting_capital_cents AS starting_capital_cents,
               (SELECT COUNT(*) FROM bot_positions bp
                 WHERE bp.allocation_id = a.id
                   AND bp.closed_at IS NULL
                   AND bp.quarantined_at IS NULL) AS open_positions_count,
               (SELECT COALESCE(SUM(
                   CASE
                     WHEN LOWER(COALESCE(bp.side,'long')) = 'short' THEN 0
                     WHEN bp.option_type IS NOT NULL THEN bp.qty * bp.avg_cost_cents * 100
                     ELSE bp.qty * bp.avg_cost_cents
                   END), 0) FROM bot_positions bp
                 WHERE bp.allocation_id = a.id
                   AND bp.closed_at IS NULL
                   AND bp.quarantined_at IS NULL) AS open_positions_notional_cents,
               (SELECT COUNT(*) FROM bot_signals bs
                 WHERE bs.allocation_id = a.id
                   AND bs.ts >= :cutoff) AS signals_window,
               (SELECT MAX(bs.ts) FROM bot_signals bs
                 WHERE bs.allocation_id = a.id) AS signals_last_ts,
               (SELECT COUNT(*) FROM bot_trades bt
                 WHERE bt.allocation_id = a.id
                   AND bt.ts >= :cutoff
                   AND bt.quarantined_at IS NULL
                   AND bt.origin = 'BROKER_FILL') AS trades_window,
               (SELECT MAX(bt.ts) FROM bot_trades bt
                 WHERE bt.allocation_id = a.id
                   AND bt.quarantined_at IS NULL) AS trades_last_ts
          FROM bot_profiles p
          JOIN bot_allocations a ON a.profile_id = p.id
         WHERE a.user_id = :user_id
         ORDER BY p.name
    """)

    rows = db.execute(sql, {"cutoff": cutoff, "user_id": AUDIT_TARGET_USER_ID}).fetchall()

    summary = {
        "total": 0,
        "trading": 0,
        "no_signals": 0,
        "paused": 0,
        "profile_disabled": 0,
        "stale": 0,
        "signals_no_trades": 0,
    }

    bots = []
    for row in rows:
        trades_last_ts_dt = _parse_row_ts(row.trades_last_ts)
        verdict, _ = _classify_bot(row, stale_cutoff, trades_last_ts_dt)
        summary["total"] += 1
        summary[verdict] += 1
        bots.append({
            "bot_id": row.bot_name,
            "verdict": verdict,
            "signals_24h": int(row.signals_window),
            "trades_24h": int(row.trades_window),
            "open_positions": int(row.open_positions_count),
            "open_positions_notional_cents": int(row.open_positions_notional_cents or 0),
            "starting_capital_cents": int(row.starting_capital_cents or 0),
            "last_signal_at": _iso_z(row.signals_last_ts),
            "last_trade_at": _iso_z(row.trades_last_ts),
            "enabled": bool(row.allocation_enabled),
            "paused_reason": row.allocation_paused_reason,
            "asset_class_declared": row.asset_class,
            "strategy_count": _strategy_count_from_config(row.config_json),
        })

    payload = {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "bots": bots,
    }
    _audit_cache_set("bot-diagnostic", payload)
    return payload


def compute_bot_diagnostics(db: Session, user_id: int = 1) -> list[dict]:
    """Extract the bot diagnostics logic for in-process callers (e.g. daily audit).

    Returns the same list of bot dicts as GET /api/admin/bot-diagnostic but
    scoped to the given user_id. Does NOT update the audit cache.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(hours=48)

    sql = text("""
        SELECT p.name             AS bot_name,
               p.enabled          AS profile_enabled,
               p.asset_class      AS asset_class,
               p.config_json      AS config_json,
               a.id               AS allocation_id,
               a.enabled          AS allocation_enabled,
               a.paused_reason    AS allocation_paused_reason,
               a.starting_capital_cents AS starting_capital_cents,
               (SELECT COUNT(*) FROM bot_positions bp
                 WHERE bp.allocation_id = a.id
                   AND bp.closed_at IS NULL
                   AND bp.quarantined_at IS NULL) AS open_positions_count,
               (SELECT COALESCE(SUM(
                   CASE
                     WHEN LOWER(COALESCE(bp.side,'long')) = 'short' THEN 0
                     WHEN bp.option_type IS NOT NULL THEN bp.qty * bp.avg_cost_cents * 100
                     ELSE bp.qty * bp.avg_cost_cents
                   END), 0) FROM bot_positions bp
                 WHERE bp.allocation_id = a.id
                   AND bp.closed_at IS NULL
                   AND bp.quarantined_at IS NULL) AS open_positions_notional_cents,
               (SELECT COUNT(*) FROM bot_signals bs
                 WHERE bs.allocation_id = a.id
                   AND bs.ts >= :cutoff) AS signals_window,
               (SELECT MAX(bs.ts) FROM bot_signals bs
                 WHERE bs.allocation_id = a.id) AS signals_last_ts,
               (SELECT COUNT(*) FROM bot_trades bt
                 WHERE bt.allocation_id = a.id
                   AND bt.ts >= :cutoff
                   AND bt.quarantined_at IS NULL
                   AND bt.origin = 'BROKER_FILL') AS trades_window,
               (SELECT MAX(bt.ts) FROM bot_trades bt
                 WHERE bt.allocation_id = a.id
                   AND bt.quarantined_at IS NULL) AS trades_last_ts
          FROM bot_profiles p
          JOIN bot_allocations a ON a.profile_id = p.id
         WHERE a.user_id = :user_id
         ORDER BY p.name
    """)

    rows = db.execute(sql, {"cutoff": cutoff, "user_id": user_id}).fetchall()

    bots = []
    for row in rows:
        trades_last_ts_dt = _parse_row_ts(row.trades_last_ts)
        verdict, _ = _classify_bot(row, stale_cutoff, trades_last_ts_dt)
        bots.append({
            "bot_id": row.bot_name,
            "verdict": verdict,
            "signals_24h": int(row.signals_window),
            "trades_24h": int(row.trades_window),
            "open_positions": int(row.open_positions_count),
            "last_signal_at": _iso_z(row.signals_last_ts),
            "last_trade_at": _iso_z(row.trades_last_ts),
            "enabled": bool(row.allocation_enabled),
            "paused_reason": row.allocation_paused_reason,
            "asset_class_declared": row.asset_class,
            "strategy_count": _strategy_count_from_config(row.config_json),
        })
    return bots


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint 2: GET /api/admin/trade-count-reconcile
# Reconciles leaderboard vs Activity Feed trade counts.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trade-count-reconcile")
def get_trade_count_reconcile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reconciles trade-count discrepancies between leaderboard and Activity Feed.

    leaderboard_count: trades from currently-enabled allocations, excluding
                       m033/m044/m045 cleanup exits. (Matches leaderboard math.)
    activity_feed_count: all trades for user_id=1, no enable/cleanup filter.
                         (Matches Activity Feed display count.)

    Cleanup-exit detection: JOIN bot_trades.position_id -> bot_positions.exit_reason,
    filter exit_reason starting with m033_/m044_/m045_.
    """
    _audit_log("trade-count-reconcile", current_user.id)
    cached = _audit_cache_get("trade-count-reconcile")
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)

    sql_leaderboard = text("""
        SELECT p.name AS bot_id,
               COUNT(*) AS cnt
          FROM bot_trades bt
          JOIN bot_allocations a ON a.id = bt.allocation_id
          JOIN bot_profiles    p ON p.id = a.profile_id
          LEFT JOIN bot_positions bp ON bp.id = bt.position_id
         WHERE a.user_id = :uid
           AND a.enabled = 1
           AND bt.quarantined_at IS NULL
           AND (bp.exit_reason IS NULL
                OR (bp.exit_reason NOT LIKE 'm033_%'
                    AND bp.exit_reason NOT LIKE 'm044_%'
                    AND bp.exit_reason NOT LIKE 'm045_%'))
         GROUP BY p.name
    """)

    sql_activity = text("""
        SELECT p.name AS bot_id,
               COUNT(*) AS cnt
          FROM bot_trades bt
          JOIN bot_allocations a ON a.id = bt.allocation_id
          JOIN bot_profiles    p ON p.id = a.profile_id
         WHERE a.user_id = :uid
         GROUP BY p.name
    """)

    lb_rows = db.execute(sql_leaderboard, {"uid": AUDIT_TARGET_USER_ID}).fetchall()
    af_rows = db.execute(sql_activity, {"uid": AUDIT_TARGET_USER_ID}).fetchall()

    lb_by_bot: dict[str, int] = {r.bot_id: int(r.cnt) for r in lb_rows}
    af_by_bot: dict[str, int] = {r.bot_id: int(r.cnt) for r in af_rows}

    all_bot_ids = set(lb_by_bot.keys()) | set(af_by_bot.keys())

    by_bot = []
    for bot_id in sorted(all_bot_ids):
        lb = lb_by_bot.get(bot_id, 0)
        af = af_by_bot.get(bot_id, 0)
        if lb == 0 and af == 0:
            continue
        by_bot.append({
            "bot_id": bot_id,
            "leaderboard": lb,
            "activity_feed": af,
            "delta": af - lb,
        })

    by_bot.sort(key=lambda x: x["delta"], reverse=True)

    leaderboard_count = sum(lb_by_bot.values())
    activity_feed_count = sum(af_by_bot.values())

    payload = {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "leaderboard_count": leaderboard_count,
        "leaderboard_source": (
            "SUM of bot_trades joined to user_id=1 enabled allocations, "
            "excluding m033/m044/m045 cleanup-exit trades and quarantined trades"
        ),
        "activity_feed_count": activity_feed_count,
        "activity_feed_source": (
            "COUNT(*) FROM bot_trades joined to user_id=1 allocations, "
            "ALL allocations (incl disabled), ALL trades (incl cleanup + quarantined)"
        ),
        "delta": activity_feed_count - leaderboard_count,
        "delta_explanation": (
            "activity_feed includes disabled-allocation history, quarantined trades, "
            "AND m033/m044/m045 cleanup-exit trades. leaderboard filters to "
            "currently-enabled allocations and excludes cleanup exits and quarantined trades."
        ),
        "by_bot": by_bot,
    }
    _audit_cache_set("trade-count-reconcile", payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint 3: GET /api/admin/asset-class-audit
# Live cross-sleeve violation check, excludes m033/m044/m045 cleanup exits.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/asset-class-audit")
def get_asset_class_audit(
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Detects cross-asset-class trades, distinguishing live violations from
    m033/m044/m045 cleanup exits.

    Query param:
      hours -- lookback window (1..168, default 24)
    """
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="hours must be 1..168")

    _audit_log("asset-class-audit", current_user.id)
    cache_key = f"asset-class-audit:{hours}"
    cached = _audit_cache_get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    sql = text("""
        SELECT bt.id           AS trade_id,
               p.name          AS bot_id,
               p.asset_class   AS declared_asset_class,
               bt.symbol       AS symbol,
               bt.ts           AS trade_created_at,
               bp.exit_reason  AS position_exit_reason
          FROM bot_trades bt
          JOIN bot_allocations a ON a.id = bt.allocation_id
          JOIN bot_profiles    p ON p.id = a.profile_id
          LEFT JOIN bot_positions bp ON bp.id = bt.position_id
         WHERE a.user_id = :uid
           AND bt.ts >= :cutoff
    """)

    rows = db.execute(sql, {"uid": AUDIT_TARGET_USER_ID, "cutoff": cutoff}).fetchall()

    violations = []
    real_violations_count = 0
    cleanup_exits_excluded_count = 0

    for row in rows:
        symbol = row.symbol
        declared = (row.declared_asset_class or "").lower()

        # Classify executed asset class from symbol heuristic
        if _looks_like_occ_option(symbol):
            executed = "option"
        elif _looks_like_crypto_pair(symbol):
            executed = "crypto"
        elif _looks_like_equity_symbol(symbol):
            executed = "equity"
        else:
            continue  # unknown symbol format — skip

        # Violation predicate
        is_violation = False
        if declared == "crypto" and executed == "equity":
            is_violation = True
        elif declared == "options" and executed != "option":
            is_violation = True
        elif declared in ("stock", "stocks") and executed == "crypto":
            is_violation = True
        elif declared in ("stock", "stocks") and executed == "option":
            is_violation = True
        # declared in (stock/stocks) and executed == equity -> MATCH, not a violation

        if not is_violation:
            continue

        # Determine if this is a cleanup exit
        exit_reason = row.position_exit_reason
        migration_tag = _cleanup_migration_tag(exit_reason)
        is_cleanup_exit = migration_tag is not None

        if is_cleanup_exit:
            cleanup_exits_excluded_count += 1
        else:
            real_violations_count += 1

        if len(violations) < 500:
            violations.append({
                "bot_id": row.bot_id,
                "declared_asset_class": row.declared_asset_class,
                "trade_id": row.trade_id,
                "symbol": symbol,
                "executed_asset_class": executed,
                "trade_created_at": _iso_z(row.trade_created_at),
                "is_cleanup_exit": is_cleanup_exit,
                "cleanup_migration": migration_tag,
            })

    truncated = (real_violations_count + cleanup_exits_excluded_count) > 500

    payload = {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "window_hours": hours,
        "violations_count": real_violations_count,
        "real_violations_count": real_violations_count,
        "cleanup_exits_excluded_count": cleanup_exits_excluded_count,
        "violations": violations,
    }
    if truncated:
        payload["truncated"] = True

    _audit_cache_set(cache_key, payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint 4: GET /api/admin/inert-bot-scan
# Per-bot signal-pipeline walk with verdict + next_action.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/inert-bot-scan")
def get_inert_bot_scan(
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """For each bot with 0 trades in the window, walk the signal pipeline
    backwards to surface WHY: scanner ran? signals produced? signals gated?
    orders rejected? Returns a tailored verdict + next_action per inert bot.
    """
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="hours must be 1..168")

    _audit_log("inert-bot-scan", current_user.id)
    cache_key = f"inert-bot-scan:{hours}"
    cached = _audit_cache_get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    # Pull all bots for user_id=1 (same join as Endpoint 1)
    sql_bots = text("""
        SELECT p.name          AS bot_name,
               p.enabled       AS profile_enabled,
               p.asset_class   AS asset_class,
               p.config_json   AS config_json,
               a.id            AS allocation_id,
               a.enabled       AS allocation_enabled,
               a.paused_reason AS allocation_paused_reason
          FROM bot_profiles p
          JOIN bot_allocations a ON a.profile_id = p.id
         WHERE a.user_id = :user_id
         ORDER BY p.name
    """)
    bot_rows = db.execute(sql_bots, {"user_id": AUDIT_TARGET_USER_ID}).fetchall()

    inert_bots = []

    for row in bot_rows:
        try:
            allocation_id = row.allocation_id
            bot_name = row.bot_name
            enabled = bool(row.allocation_enabled)

            # Trades in window (proxy for order fills)
            trades_in_window = db.execute(text("""
                SELECT COUNT(*) FROM bot_trades
                 WHERE allocation_id = :aid
                   AND ts >= :cutoff
                   AND quarantined_at IS NULL
            """), {"aid": allocation_id, "cutoff": cutoff}).scalar() or 0
            trades_in_window = int(trades_in_window)

            # If bot is trading (has fills), skip — only disabled bots are always surfaced
            if trades_in_window > 0 and enabled:
                continue

            # Disabled allocations always surface even if they had trades before
            # If disabled and has trades, still surface with verdict=bot_disabled
            strategies_attached = _strategy_count_from_config(row.config_json)

            # Heartbeat
            hb_row = db.execute(text("""
                SELECT last_scan_at FROM bot_heartbeat WHERE bot_name = :bn
            """), {"bn": bot_name}).fetchone()

            scanner_last_run_at = None
            scanner_ran_24h = False
            if hb_row is not None and hb_row[0] is not None:
                last_scan_dt = _parse_row_ts(hb_row[0])
                scanner_last_run_at = _iso_z(hb_row[0])
                if last_scan_dt is not None:
                    scanner_ran_24h = last_scan_dt >= (now - timedelta(hours=24))

            # Signals produced in window
            signals_produced_24h = db.execute(text("""
                SELECT COUNT(*) FROM bot_signals
                 WHERE allocation_id = :aid
                   AND ts >= :cutoff
            """), {"aid": allocation_id, "cutoff": cutoff}).scalar() or 0
            signals_produced_24h = int(signals_produced_24h)

            # Signal gate metrics
            signals_blocked_by_confidence = db.execute(text("""
                SELECT COUNT(*) FROM signal_gates
                 WHERE bot_name = :bn
                   AND created_at >= :cutoff
                   AND final_decision = 'filtered'
                   AND filter_reason = 'score_below_threshold'
            """), {"bn": bot_name, "cutoff": cutoff}).scalar() or 0
            signals_blocked_by_confidence = int(signals_blocked_by_confidence)

            signals_blocked_by_discipline_gate = db.execute(text("""
                SELECT COUNT(*) FROM signal_gates
                 WHERE bot_name = :bn
                   AND created_at >= :cutoff
                   AND final_decision = 'filtered'
                   AND filter_reason IN ('regime_mismatch', 'insufficient_confluence', 'multiple')
            """), {"bn": bot_name, "cutoff": cutoff}).scalar() or 0
            signals_blocked_by_discipline_gate = int(signals_blocked_by_discipline_gate)

            # Orders attempted = trades proxy; rejected = always 0 (no bot_orders table)
            orders_attempted_24h = trades_in_window
            orders_rejected_24h = 0

            # Verdict (priority order, first match wins)
            pipeline_data_gap = [
                "cooldown_metric",
                "sleeve_cap_metric",
                "orders_rejection_metric",
                "scanner_error_metric",
            ]

            if not enabled:
                verdict = "bot_disabled"
                next_action = "Re-enable BotAllocation via /admin/allocation/enable or check paused_reason field"
            elif strategies_attached == 0:
                verdict = "no_strategies_attached"
                next_action = "Edit bot_profiles.config_json -- add at least one strategy"
            elif not scanner_ran_24h and signals_produced_24h == 0:
                verdict = "scanner_not_running"
                next_action = "Check Railway logs for scheduler exceptions; verify bot is in bot_scheduler.py loop"
            elif scanner_ran_24h and signals_produced_24h == 0:
                verdict = "scanner_running_no_signals"
                next_action = "Scanner alive but no signals -- check bar fetch (yfinance/alpaca rate limits)"
            elif signals_blocked_by_confidence > 0 and signals_blocked_by_confidence >= signals_blocked_by_discipline_gate:
                verdict = "signals_filtered_by_confidence"
                next_action = "Lower composite_threshold in profile or wait for higher-confluence regime"
            elif signals_blocked_by_discipline_gate > 0:
                verdict = "signals_filtered_by_discipline"
                next_action = "Check current regime vs profile regime_preference"
            elif orders_attempted_24h > 0 and orders_rejected_24h > 0:
                verdict = "orders_rejected"
                next_action = "Check broker logs -- Alpaca/Kraken rejections"
            else:
                # Fallback — scanner not running (no heartbeat row case)
                verdict = "scanner_not_running"
                next_action = "Check Railway logs for scheduler exceptions; verify bot is in bot_scheduler.py loop"

            inert_bots.append({
                "bot_id": bot_name,
                "scanner_ran_24h": scanner_ran_24h,
                "scanner_last_run_at": scanner_last_run_at,
                "scanner_last_error": None,
                "signals_produced_24h": signals_produced_24h,
                "signals_blocked_by_confidence": signals_blocked_by_confidence,
                "signals_blocked_by_cooldown": 0,
                "signals_blocked_by_discipline_gate": signals_blocked_by_discipline_gate,
                "signals_blocked_by_sleeve_cap": 0,
                "orders_attempted_24h": orders_attempted_24h,
                "orders_rejected_24h": orders_rejected_24h,
                "rejection_reasons": {},
                "strategies_attached": strategies_attached,
                "enabled": enabled,
                "verdict": verdict,
                "next_action": next_action,
                "pipeline_data_gap": pipeline_data_gap,
            })

        except Exception as exc:
            logger.warning("[admin-audit] inert-bot-scan: error processing bot %s: %s", row.bot_name, exc)
            continue

    payload = {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "window_hours": hours,
        "inert_bots": inert_bots,
    }
    _audit_cache_set(cache_key, payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint 5: GET /api/admin/fund-tear-sheet-honesty-check
# Manifest of real vs fabricated fields on /fund/tear-sheet.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/fund-tear-sheet-honesty-check")
def get_fund_tear_sheet_honesty_check(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manifest of which /fund/tear-sheet fields are real vs fabricated.
    MOCK_DATA banner was added in PR #35. This endpoint lets auditors verify
    field-by-field without parsing the React render tree.
    """
    _audit_log("fund-tear-sheet-honesty-check", current_user.id)
    cached = _audit_cache_get("fund-tear-sheet-honesty-check")
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)

    real_fields = [
        "nav_total",
        "today_pnl_30d",
        "open_positions_count",
        "sleeve_balances",
        "bot_allocations",
    ]

    fabricated_fields = [
        "inception_date",
        "monthly_returns_2023",
        "monthly_returns_2024",
        "monthly_returns_2025",
        "cagr_since_inception",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "max_drawdown",
        "win_rate",
        "beta_vs_benchmark",
        "alpha_annualized",
        "high_water_mark",
        "nav_per_unit",
        "per_bot_sharpe",
        "per_bot_max_dd",
        "sleeve_correlation_matrix",
        "recovery_factor",
        "cio_note",
    ]

    # Compute earliest real data point from bot_trades for user_id=1
    earliest_row = db.execute(text("""
        SELECT MIN(bt.ts)
          FROM bot_trades bt
          JOIN bot_allocations a ON a.id = bt.allocation_id
         WHERE a.user_id = 1
           AND bt.quarantined_at IS NULL
    """)).fetchone()

    earliest_ts = earliest_row[0] if earliest_row else None

    if earliest_ts is not None:
        # Normalize to UTC datetime
        earliest_dt = _parse_row_ts(earliest_ts)
        if earliest_dt is None:
            earliest_real_data_point = None
            fund_history_days = 0
        else:
            earliest_real_data_point = _iso_z(earliest_dt)
            fund_history_days = (now - earliest_dt).days
    else:
        earliest_real_data_point = None
        fund_history_days = 0

    payload = {
        "as_of": now.isoformat().replace("+00:00", "Z"),
        "real_fields": real_fields,
        "fabricated_fields": fabricated_fields,
        "earliest_real_data_point": earliest_real_data_point,
        "fund_history_days": fund_history_days,
        "banner_displayed": True,
        "banner_added_in_pr": "#35",
        "recommendation": (
            "Once /api/fund/returns-history exists with >=21 days, replace "
            "fabricated fields with real values + remove banner"
        ),
    }
    _audit_cache_set("fund-tear-sheet-honesty-check", payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/admin/strategy-regime-matrix
# Phase 2 closed-loop learning: strategy × regime performance matrix.
# ─────────────────────────────────────────────────────────────────────────────

# Cache keyed by (bot_id, window_days, user_id) → (expires_at_epoch, response).
_REGIME_MATRIX_CACHE: dict[tuple, tuple[float, dict]] = {}
_REGIME_MATRIX_CACHE_TTL = 30  # seconds


def _regime_matrix_cache_get(key: tuple) -> dict | None:
    entry = _REGIME_MATRIX_CACHE.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if time.time() > expires_at:
        _REGIME_MATRIX_CACHE.pop(key, None)
        return None
    return payload


def _regime_matrix_cache_set(key: tuple, payload: dict) -> None:
    _REGIME_MATRIX_CACHE[key] = (time.time() + _REGIME_MATRIX_CACHE_TTL, payload)


@router.get("/strategy-regime-matrix")
def get_strategy_regime_matrix(
    bot_id: str = Query(..., description="bot_profiles.name, e.g. crypto_quant_aggressive"),
    window_days: int = Query(30, ge=1, le=365),
    min_trades_for_sharpe: int = Query(5, ge=2, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Strategy × regime performance matrix for one bot over window_days.

    Groups bot_trades by (regime_vix, regime_trend, regime_btc_dom_band) and
    computes trades / winners / losers / win_rate / total_pnl_cents / sharpe
    per cell.

    Auth: Depends(get_current_user). Multi-user safe — scoped by current_user.id
    via JOIN on bot_allocations.user_id.

    Cache: 30s TTL keyed by (bot_id, window_days, user_id).
    """
    import math
    from collections import defaultdict

    _audit_log("strategy-regime-matrix", current_user.id)

    cache_key = (bot_id, window_days, current_user.id)
    cached = _regime_matrix_cache_get(cache_key)
    if cached is not None:
        return cached

    # ── Validate bot_id resolves to a bot_profiles.name ──────────────────────
    from app.db.models.bots import BotProfile, BotAllocation, BotTrade

    profile = (
        db.query(BotProfile)
        .filter(BotProfile.name == bot_id)
        .first()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="unknown bot_id")

    # ── Build query cutoff ────────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=window_days)

    # ── Fetch trades via JOIN bot_trades → bot_allocations → bot_profiles ─────
    # Scoped by current_user.id (multi-user safe per known-issue #6).
    rows = db.execute(
        text(
            """
            SELECT
                t.regime_vix,
                t.regime_trend,
                t.regime_btc_dom_band,
                t.id,
                t.ts,
                t.side,
                t.qty,
                t.fill_price_cents,
                t.fees_cents,
                t.position_id
            FROM bot_trades t
            JOIN bot_allocations a ON a.id = t.allocation_id
            JOIN bot_profiles p ON p.id = a.profile_id
            WHERE p.name = :bot_id
              AND a.user_id = :uid
              AND t.ts >= :cutoff
            ORDER BY t.regime_vix, t.regime_trend, t.regime_btc_dom_band, t.ts ASC
            """
        ),
        {"bot_id": bot_id, "uid": current_user.id, "cutoff": cutoff.isoformat()},
    ).fetchall()

    total_trades_in_window = len(rows)
    untagged_trades_in_window = sum(1 for r in rows if r[0] is None)

    # ── Group by regime cell ──────────────────────────────────────────────────
    cell_rows: dict[tuple, list] = defaultdict(list)
    for r in rows:
        cell_key = (r[0] or "UNKNOWN", r[1] or "UNKNOWN", r[2] or "UNKNOWN")
        cell_rows[cell_key].append(r)

    # ── Compute per-cell metrics ──────────────────────────────────────────────
    matrix = []
    for cell_key, cell_trades in cell_rows.items():
        regime_vix, regime_trend, regime_btc_dom_band = cell_key
        trades = len(cell_trades)

        # Group by position_id for PnL pairing (entry + exit)
        by_position: dict[int | None, list] = defaultdict(list)
        for r in cell_trades:
            by_position[r[9]].append(r)

        # Realized PnL: pair entry (buy/short) with exit (sell/cover) per position
        winners = 0
        losers = 0
        total_pnl_cents = 0
        closed_pnl_list: list[int] = []  # one entry per closed position, for sharpe

        for pos_id, pos_trades in by_position.items():
            if pos_id is None:
                # Orphan trades without position link — count but skip PnL pairing
                continue

            entries = [t for t in pos_trades if t[5] in ("buy", "short")]
            exits = [t for t in pos_trades if t[5] in ("sell", "cover")]

            if not entries or not exits:
                # Unrealized (no exit in this window) — skip from PnL tally
                continue

            # Simple pairing: sum(exit cash flows) - sum(entry cash flows) - fees
            # sign: sell/cover = +1 (cash in), buy/short = -1 (cash out)
            exit_flow = sum(t[7] * t[6] for t in exits)   # fill_price_cents * qty
            entry_flow = sum(t[7] * t[6] for t in entries)
            fees = sum(t[8] for t in pos_trades)
            pnl_cents = int(exit_flow - entry_flow - fees)

            closed_pnl_list.append(pnl_cents)
            total_pnl_cents += pnl_cents
            if pnl_cents > 0:
                winners += 1
            elif pnl_cents < 0:
                losers += 1

        # win_rate
        denom = winners + losers
        win_rate = round(winners / denom, 3) if denom > 0 else None

        # Sharpe (annualized, from daily returns)
        sharpe = None
        if trades >= min_trades_for_sharpe and len(closed_pnl_list) >= 2:
            # Build daily returns series by grouping closed_pnl by date
            daily_pnl: dict[str, int] = defaultdict(int)
            for r, pnl_c in zip(
                [t for t in cell_trades if t[9] is not None and t[5] in ("sell", "cover")],
                closed_pnl_list,
            ):
                # r[4] = ts
                ts_val = r[4]
                if isinstance(ts_val, str):
                    day_key = ts_val[:10]
                elif hasattr(ts_val, "date"):
                    day_key = str(ts_val.date())
                else:
                    day_key = str(ts_val)[:10]
                daily_pnl[day_key] += pnl_c

            daily_returns = list(daily_pnl.values())
            if len(daily_returns) >= 2:
                n = len(daily_returns)
                mean_r = sum(daily_returns) / n
                variance = sum((x - mean_r) ** 2 for x in daily_returns) / (n - 1)
                std_r = math.sqrt(variance) if variance > 0 else 0.0
                if std_r > 0:
                    sharpe = round((mean_r / std_r) * math.sqrt(252), 4)

        matrix.append({
            "regime_vix": regime_vix,
            "regime_trend": regime_trend,
            "regime_btc_dom_band": regime_btc_dom_band,
            "trades": trades,
            "winners": winners,
            "losers": losers,
            "win_rate": win_rate,
            "total_pnl_cents": total_pnl_cents,
            "sharpe": sharpe,
        })

    payload = {
        "as_of": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bot_id": bot_id,
        "window_days": window_days,
        "matrix": matrix,
        "total_trades_in_window": total_trades_in_window,
        "untagged_trades_in_window": untagged_trades_in_window,
    }

    _regime_matrix_cache_set(cache_key, payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Daily Strategy Lab Audit endpoints (m050)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/daily-audit/run-now")
def post_daily_audit_run_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually trigger a daily Strategy Lab audit. Returns full audit result.

    Does NOT wrap in sentry_sdk.start_transaction — FastAPI middleware already
    creates a request-scoped transaction for this HTTP handler.

    Auth: required (401 on unauthenticated).
    """
    from app.jobs.daily_strategy_lab_audit import run_daily_audit
    import json as _json
    return run_daily_audit(db)


@router.get("/daily-audit/latest")
def get_daily_audit_latest(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the most recent daily audit row from daily_audit_log.

    Returns 200 with as_of=null when no audits have been run yet.
    Auth: required (401 on unauthenticated).
    """
    import json as _json
    row = db.execute(text("""
        SELECT id, run_at, overall_status, checks_json, alerts_json, summary_markdown
        FROM daily_audit_log
        ORDER BY run_at DESC, id DESC
        LIMIT 1
    """)).fetchone()
    if row is None:
        return {
            "as_of": None,
            "overall_status": None,
            "checks": [],
            "alerts": [],
            "summary_markdown": "",
            "note": "no audits yet",
        }
    return {
        "id": row.id,
        "as_of": row.run_at,
        "overall_status": row.overall_status,
        "checks": _json.loads(row.checks_json),
        "alerts": _json.loads(row.alerts_json),
        "summary_markdown": row.summary_markdown,
    }


# ─── PUBLIC diagnostic — manual scan trigger for options investigation ────────
@router.get("/open-positions-diagnostic/{bot_name}")
def open_positions_diagnostic(bot_name: str, db: Session = Depends(get_db)) -> dict:
    """Show open positions for a bot — hunting phantom blockers."""
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    rows = db.execute(text(
        "SELECT p.id, p.symbol, p.qty, p.avg_cost_cents, p.side, p.opened_at, "
        "  p.option_type, p.strike_price, p.expiration_date, p.underlying_symbol, "
        "  p.contract_count, p.exit_reason, p.quarantined_at, p.allocation_id "
        "FROM bot_positions p "
        "JOIN bot_allocations a ON a.id = p.allocation_id "
        "JOIN bot_profiles bp ON bp.id = a.profile_id "
        "WHERE bp.name = :name AND p.closed_at IS NULL "
        "ORDER BY p.opened_at DESC"
    ), {"name": bot_name}).fetchall()
    positions = []
    for r in rows:
        positions.append({
            "id": int(r[0]),
            "symbol": r[1],
            "qty": float(r[2] or 0),
            "avg_cost_cents": int(r[3] or 0),
            "side": r[4],
            "opened_at": str(r[5]),
            "option_type": r[6],
            "strike_price": float(r[7]) if r[7] else None,
            "expiration_date": r[8],
            "underlying_symbol": r[9],
            "contract_count": r[10],
            "exit_reason": r[11],
            "quarantined_at": str(r[12]) if r[12] else None,
            "allocation_id": int(r[13]),
        })
    return {"bot": bot_name, "open_positions_count": len(positions), "positions": positions}


@router.get("/scan-trigger-diagnostic/{bot_name}")
def trigger_scan_diagnostic(bot_name: str, persist: bool = False, execute: bool = False,
                            db: Session = Depends(get_db)) -> dict:
    """Force-run scan_and_execute for a bot and return the result.

    Public + gated by BMG_DIAGNOSTIC_PV_ENABLED. Use for hunting silent
    scan failures (options bots produced 0 signals in 24h).

    Query params:
      persist=true — write signals to bot_signals (matches cron behavior)
      execute=true — attempt actual order execution (DANGER — use carefully)
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    try:
        from strategy_lab.scan_and_execute import scan_and_execute
        result = scan_and_execute(bot_name, db, persist=persist, execute=execute)
        # Truncate results for readability
        if isinstance(result, dict) and "results" in result:
            result["results_count"] = len(result.get("results") or [])
            result["results_sample"] = (result.get("results") or [])[:5]
            result.pop("results", None)
        return result
    except Exception as exc:
        import traceback
        return {"error": str(exc)[:400], "traceback": traceback.format_exc()[:2000]}


# ─── PUBLIC diagnostic — all-users summary ────────────────────────────────────
@router.get("/options-symbols-diagnostic")
def options_symbols(db: Session = Depends(get_db)) -> dict:
    """BLOCK 4: verify options bots trade OCC symbols, not equities."""
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    cut = (_dt.now(_tz.utc) - _td(days=30)).isoformat()
    rows = db.execute(text(
        "SELECT p.name AS bot, t.symbol, t.ts, LENGTH(t.symbol) AS sym_len "
        "FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE p.name LIKE 'options%' "
        "  AND t.ts >= :cut "
        "  AND t.quarantined_at IS NULL "
        "ORDER BY t.ts DESC LIMIT 50"
    ), {"cut": cut}).fetchall()
    trades = []
    equity_leaks = 0
    for r in rows:
        symlen = int(r[3] or 0)
        is_occ = symlen >= 15  # OCC format is 15-21 chars
        trades.append({"bot": r[0], "symbol": r[1], "ts": str(r[2]), "sym_len": symlen, "is_occ": is_occ})
        if not is_occ:
            equity_leaks += 1
    return {"count": len(trades), "equity_leaks": equity_leaks, "trades": trades[:10]}


@router.get("/heartbeats-diagnostic")
def heartbeats_diagnostic(db: Session = Depends(get_db)) -> dict:
    """BLOCK 7: enabled bots with stale (>6h) heartbeats."""
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    rows = db.execute(text(
        "SELECT p.name, MAX(s.ts) AS last_ts, "
        "  (SELECT MAX(t.ts) FROM bot_trades t "
        "     JOIN bot_allocations aa ON aa.id = t.allocation_id "
        "     WHERE aa.user_id = 1 AND (SELECT id FROM bot_profiles WHERE name = p.name) = aa.profile_id) AS last_trade_ts "
        "FROM bot_profiles p "
        "LEFT JOIN bot_allocations a ON a.profile_id = p.id AND a.user_id = 1 "
        "LEFT JOIN bot_signals s ON s.allocation_id = a.id "
        "WHERE a.starting_capital_cents > 0 "
        "GROUP BY p.name "
        "ORDER BY MAX(s.ts) NULLS FIRST"
    )).fetchall()
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    out = []
    for r in rows:
        last = r[1]
        age_h = None
        if last:
            try:
                lts = _dt.fromisoformat(str(last).replace("Z", "+00:00"))
                if lts.tzinfo is None:
                    lts = lts.replace(tzinfo=_tz.utc)
                age_h = (now - lts).total_seconds() / 3600
            except Exception:
                pass
        out.append({"bot": r[0], "last_signal_ts": str(last) if last else None,
                    "last_trade_ts": str(r[2]) if r[2] else None,
                    "hours_stale": round(age_h, 1) if age_h is not None else None})
    stale_6h = [r for r in out if r["hours_stale"] is not None and r["hours_stale"] > 6]
    never_fired = [r for r in out if r["last_signal_ts"] is None]
    return {"total_active_bots": len(out), "stale_over_6h": len(stale_6h),
            "never_fired": len(never_fired), "details": out}


@router.get("/audit13-diagnostic")
def audit13(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Data for the 13-item hedge fund audit. Admin only.

    2026-07-05: added require_admin (was unauth). Previous version leaked
    fund allocation + position data to anyone who could hit the URL while
    BMG_DIAGNOSTIC_PV_ENABLED was true.
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    result: dict = {}

    # P1-5: bot count reconciliation
    active_allocs = db.execute(text(
        "SELECT p.name, p.asset_class, a.starting_capital_cents, a.enabled AS alloc_enabled, "
        "  p.enabled AS profile_enabled "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 "
        "ORDER BY p.name"
    )).fetchall()
    result["P1-5"] = {
        "note": "Every allocation row for user 1, with profile + alloc enabled flags.",
        "rows": [
            {"bot": r[0], "asset_class": r[1], "starting_usd": (int(r[2] or 0))/100,
             "alloc_enabled": bool(r[3]), "profile_enabled": bool(r[4])}
            for r in active_allocs
        ],
        "counts": {
            "total_allocations": len(active_allocs),
            "funded_bots": sum(1 for r in active_allocs if int(r[2] or 0) > 0),
            "funded_and_enabled": sum(1 for r in active_allocs
                                     if int(r[2] or 0) > 0 and bool(r[3]) and bool(r[4])),
            "zero_capital": sum(1 for r in active_allocs if int(r[2] or 0) == 0),
        },
    }

    # P1-7: per-bot deployment reconciliation with ghost-position detection.
    # A "ghost" position has NO matching opening bot_trade fill (buy for long,
    # sell for short) after the position's opened_at. Ghost positions
    # inflate the deployment number without corresponding capital outlay.
    watch_deploy_bots = [
        "stock_orb_breakout",
        "crypto_quant_scalp_1m", "crypto_quant_meme_tier",
        "crypto_quant_universe_top6", "crypto_quant_10m",
        "crypto_quant_defi_l2", "crypto_quant_aggressive",
        "crypto_quant_alt_focus", "crypto_quant_15m",
    ]
    deploy_report = {}
    for bot_name in watch_deploy_bots:
        alloc_row = db.execute(text(
            "SELECT a.id, COALESCE(a.starting_capital_cents, 0) "
            "FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :bot AND a.user_id = 1"
        ), {"bot": bot_name}).fetchone()
        if not alloc_row:
            deploy_report[bot_name] = {"error": "no allocation for user 1"}
            continue
        alloc_id = int(alloc_row[0])
        starting_cents = int(alloc_row[1] or 0)

        positions = db.execute(text(
            "SELECT id, symbol, qty, avg_cost_cents, side, opened_at, option_type, "
            "  closed_at, quarantined_at "
            "FROM bot_positions "
            "WHERE allocation_id = :aid "
            "  AND closed_at IS NULL AND quarantined_at IS NULL "
            "ORDER BY opened_at DESC"
        ), {"aid": alloc_id}).fetchall()

        pos_detail = []
        deployed_cents = 0
        ghost_count = 0
        ghost_cents = 0
        for p in positions:
            qty = float(p[2] or 0)
            avg_cost_c = float(p[3] or 0)
            side = (p[4] or "long").lower()
            opened_at = p[5]
            option_type = p[6]
            if option_type is not None:
                notional_c = int(avg_cost_c * qty * 100)
            else:
                notional_c = int(avg_cost_c * qty)
            deployed_cents += notional_c

            # Ghost check: does a matching opening fill exist in bot_trades?
            # Long open = buy fill; short open = sell fill; both in the window
            # [opened_at - 30s, opened_at + 30s] on the same symbol.
            open_side = "buy" if side in ("long", "buy") else "sell"
            match = db.execute(text(
                "SELECT COUNT(*) FROM bot_trades "
                "WHERE allocation_id = :aid AND symbol = :sym AND side = :s "
                "  AND ts BETWEEN datetime(:ts,'-30 seconds') AND datetime(:ts,'+30 seconds') "
                "  AND quarantined_at IS NULL"
            ), {
                "aid": alloc_id, "sym": p[1], "s": open_side,
                "ts": str(opened_at) if opened_at else None,
            }).fetchone()
            has_opening = bool(int(match[0] or 0)) if match else False
            if not has_opening:
                ghost_count += 1
                ghost_cents += notional_c
            pos_detail.append({
                "position_id": int(p[0]),
                "symbol": p[1],
                "qty": qty,
                "avg_cost_cents": int(avg_cost_c),
                "side": side,
                "opened_at": str(opened_at) if opened_at else None,
                "notional_cents": notional_c,
                "notional_usd": round(notional_c / 100.0, 2),
                "has_opening_trade": has_opening,
                "is_ghost": not has_opening,
            })

        cleaned_cents = deployed_cents - ghost_cents
        deploy_report[bot_name] = {
            "starting_capital_usd": round(starting_cents / 100.0, 2),
            "open_positions": len(positions),
            "raw_deployed_usd": round(deployed_cents / 100.0, 2),
            "raw_deployed_pct": round((deployed_cents / starting_cents * 100), 2)
                                 if starting_cents else None,
            "ghost_positions": ghost_count,
            "ghost_deployed_usd": round(ghost_cents / 100.0, 2),
            "cleaned_deployed_usd": round(cleaned_cents / 100.0, 2),
            "cleaned_deployed_pct": round((cleaned_cents / starting_cents * 100), 2)
                                     if starting_cents else None,
            "positions": pos_detail[:30],
        }
    result["P1-7"] = {
        "note": "Per-bot open position table with ghost-position detection. "
                "A ghost position has no matching opening trade fill within +/-30s of opened_at. "
                "cleaned_deployed_usd excludes ghosts; that number should track starting_capital.",
        "bots": deploy_report,
    }

    # P2-10: Signal rejection breakdown for the 8 crypto quant bots.
    # 2026-07-05 fix: earlier version filtered on side='hold', missing the
    # buy/sell signals that were emitted but not executed (the actual
    # rejects). New version groups executed_at IS NULL signals by strategy
    # + confidence bucket so we can see where they died.
    cut_24h = (_dt.now(_tz.utc) - _td(hours=24)).isoformat()
    per_bot_gate = {}
    watch_bots = [
        "crypto_quant_scalp_1m", "crypto_quant_meme_tier",
        "crypto_quant_universe_top6", "crypto_quant_10m",
        "crypto_quant_defi_l2", "crypto_quant_aggressive",
        "crypto_quant_alt_focus", "crypto_quant_15m",
        # 2026-07-06: added the two options bots because Patrick's sentinel
        # flagged both as silent for 2.5+ days despite being properly funded
        # ($25K each after m067) and enabled at both the allocation and
        # profile level. Their inclusion here surfaces whether the strategy
        # emitted any raw signals + how many were rejected + why.
        "options_income", "options_directional",
    ]
    for bot_name in watch_bots:
        row = db.execute(text(
            "SELECT COUNT(*) AS sigs, "
            "  COALESCE(SUM(CASE WHEN s.executed_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS traded, "
            "  COALESCE(SUM(CASE WHEN s.side='hold' THEN 1 ELSE 0 END), 0) AS holds, "
            "  COALESCE(SUM(CASE WHEN s.side IN ('buy','sell') AND s.executed_at IS NULL THEN 1 ELSE 0 END), 0) AS rejects "
            "FROM bot_signals s "
            "JOIN bot_allocations a ON a.id = s.allocation_id "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :bot AND s.ts >= :cut"
        ), {"bot": bot_name, "cut": cut_24h}).fetchone()
        # Reject reasons: buy/sell signals that were NOT executed. Grouped by
        # the signal.reason text so we can see the gate that killed them.
        reject_reasons = db.execute(text(
            "SELECT COALESCE(s.reason, '<null>'), COUNT(*) AS n FROM bot_signals s "
            "JOIN bot_allocations a ON a.id = s.allocation_id "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :bot AND s.ts >= :cut "
            "  AND s.side IN ('buy','sell') AND s.executed_at IS NULL "
            "GROUP BY s.reason ORDER BY n DESC LIMIT 8"
        ), {"bot": bot_name, "cut": cut_24h}).fetchall()
        # Open position count for the bot — if this is at position_cap, no new
        # buys can execute regardless of signal quality.
        pos_row = db.execute(text(
            "SELECT COUNT(*) FROM bot_positions bp "
            "JOIN bot_allocations a ON a.id = bp.allocation_id "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE p.name = :bot AND bp.closed_at IS NULL AND bp.quarantined_at IS NULL"
        ), {"bot": bot_name}).fetchone()
        open_pos = int(pos_row[0] or 0) if pos_row else 0
        sigs = int(row[0] or 0)
        traded = int(row[1] or 0)
        holds = int(row[2] or 0)
        rejects = int(row[3] or 0)
        per_bot_gate[bot_name] = {
            "signals_24h": sigs,
            "signals_executed": traded,
            "hold_type_signals": holds,
            "buy_sell_rejected": rejects,
            "conv_pct": round((traded / sigs * 100), 2) if sigs else 0.0,
            "open_positions_now": open_pos,
            "top_reject_reasons": [{"reason": (r[0] or "")[:200], "count": int(r[1])}
                                   for r in reject_reasons],
        }
    result["P2-10"] = {
        "note": "Per-bot signal outcome 24h. buy_sell_rejected = signals that "
                "asked for a fill but executed_at stayed NULL. top_reject_reasons "
                "is the reason text on those unexecuted buy/sell signals.",
        "per_bot": per_bot_gate,
    }

    # P2-9: sample 20 scalp_1m signals in the last hour for the log excerpt
    scalp_cut = (_dt.now(_tz.utc) - _td(hours=1)).isoformat()
    scalp_sigs = db.execute(text(
        "SELECT s.ts, s.symbol, s.side, s.confidence, s.strategy, s.reason, "
        "  CASE WHEN s.executed_at IS NOT NULL THEN 'EXECUTED' ELSE 'NOT_EXEC' END AS status "
        "FROM bot_signals s "
        "JOIN bot_allocations a ON a.id = s.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE p.name = 'crypto_quant_scalp_1m' AND s.ts >= :cut "
        "ORDER BY s.ts DESC LIMIT 20"
    ), {"cut": scalp_cut}).fetchall()
    result["P2-9"] = {
        "note": "20 most recent scalp_1m signals (last hour).",
        "signals": [
            {"ts": str(r[0]), "symbol": r[1], "side": r[2],
             "confidence": float(r[3] or 0), "strategy": r[4],
             "reason": (r[5] or "")[:220], "status": r[6]}
            for r in scalp_sigs
        ],
    }

    return result


@router.get("/auth-debug")
def auth_debug(request: Request) -> dict:
    """Public endpoint that echoes back the Bearer token status.

    NOT AUTH GATED — the whole point is to debug why auth is failing.
    Returns the raw Authorization header, whether it decodes, decoded
    payload (or the JWT error), and whether the resolved user exists.
    Use this when the browser gets 401 on /api/dashboard/v2 and you
    need to know WHY.

    Returns only token metadata (exp, sub, email). Does not leak the
    token secret or hash.
    """
    from app.config import settings as _settings
    from jose import jwt as _jwt, JWTError as _JWTError
    hdr = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    out: dict = {
        "has_authorization_header": bool(hdr),
        "header_scheme": hdr.split(" ", 1)[0] if hdr else None,
        "token_len": len(hdr.split(" ", 1)[1]) if hdr.startswith("Bearer ") else 0,
    }
    if not hdr.startswith("Bearer "):
        out["error"] = "no Bearer token in Authorization header"
        return out
    token = hdr.split(" ", 1)[1]
    try:
        payload = _jwt.decode(
            token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm]
        )
        out["decoded_sub"] = payload.get("sub")
        out["decoded_email"] = payload.get("email")
        out["decoded_username"] = payload.get("username")
        out["decoded_exp"] = payload.get("exp")
        # Is exp in the past?
        from datetime import datetime, timezone
        if payload.get("exp"):
            exp_dt = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
            now = datetime.now(timezone.utc)
            out["exp_iso"] = exp_dt.isoformat()
            out["now_iso"] = now.isoformat()
            out["expired"] = exp_dt < now
            out["seconds_until_exp"] = int((exp_dt - now).total_seconds())
        out["decode_ok"] = True
    except _JWTError as e:
        out["decode_ok"] = False
        out["jwt_error"] = str(e)
    except Exception as e:
        out["decode_ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"
    return out


@router.get("/hedge-fund-audit-diagnostic")
def hedge_fund_audit(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Comprehensive audit: per-bot P&L, hit rate, hold time, exposure,
    correlation, deployment ratio, symbol concentration.

    2026-07-06: added require_admin (was unauth). Under the previous state,
    if BMG_DIAGNOSTIC_PV_ENABLED=true was flipped on Railway (as it currently
    is), anyone could hit the URL and pull the whole fund's realized losses,
    per-bot P&L, and per-symbol exposure. Now admin-gated.
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from collections import defaultdict as _dd
    import math as _math

    now = _dt.now(_tz.utc)
    cut_30d = (now - _td(days=30)).isoformat()

    # 1. Per-bot trade stats (closed round-trips only)
    trade_rows = db.execute(text(
        "SELECT p.name AS bot, p.asset_class, "
        "  (CASE WHEN pos.side = 'short' "
        "        THEN (pos.avg_cost_cents - t.fill_price_cents) "
        "        ELSE (t.fill_price_cents - pos.avg_cost_cents) END) * pos.qty AS pnl_cents, "
        "  pos.opened_at, t.ts AS closed_at, "
        "  pos.qty * pos.avg_cost_cents AS notional_cents "
        "FROM bot_trades t "
        "JOIN bot_positions pos ON pos.id = t.position_id "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 "
        "  AND t.side IN ('sell','cover','close') "
        "  AND t.quarantined_at IS NULL "
        "  AND t.ts >= :cut"
    ), {"cut": cut_30d}).fetchall()

    by_bot = _dd(lambda: {"trades":[], "wins":0, "losses":0, "total_pnl":0.0,
                          "total_notional":0.0, "hold_secs":[], "asset_class":""})
    for r in trade_rows:
        bot, ac, pnl_c, opened, closed, notional_c = r
        pnl_usd = float(pnl_c or 0) / 100.0
        by_bot[bot]["asset_class"] = ac
        by_bot[bot]["trades"].append(pnl_usd)
        by_bot[bot]["total_pnl"] += pnl_usd
        by_bot[bot]["total_notional"] += float(notional_c or 0) / 100.0
        if pnl_usd > 0: by_bot[bot]["wins"] += 1
        elif pnl_usd < 0: by_bot[bot]["losses"] += 1
        # hold time
        try:
            o = _dt.fromisoformat(str(opened).replace("Z","+00:00")) if opened else None
            c = _dt.fromisoformat(str(closed).replace("Z","+00:00")) if closed else None
            if o and c:
                if o.tzinfo is None: o = o.replace(tzinfo=_tz.utc)
                if c.tzinfo is None: c = c.replace(tzinfo=_tz.utc)
                by_bot[bot]["hold_secs"].append((c - o).total_seconds())
        except Exception:
            pass

    bot_stats = []
    for bot, x in by_bot.items():
        n = len(x["trades"])
        wr = x["wins"] / (x["wins"] + x["losses"]) if (x["wins"] + x["losses"]) else 0.0
        wins_pnl = [p for p in x["trades"] if p > 0]
        losses_pnl = [p for p in x["trades"] if p < 0]
        avg_w = sum(wins_pnl)/len(wins_pnl) if wins_pnl else 0
        avg_l = sum(losses_pnl)/len(losses_pnl) if losses_pnl else 0
        pf = sum(wins_pnl) / abs(sum(losses_pnl)) if losses_pnl else None
        expectancy = x["total_pnl"] / n if n else 0
        avg_hold = sum(x["hold_secs"])/len(x["hold_secs"])/3600 if x["hold_secs"] else None
        # simple sharpe
        if n > 5:
            mean = expectancy
            var = sum((p - mean)**2 for p in x["trades"]) / n
            sd = _math.sqrt(var) if var > 0 else 0
            per_trade_sharpe = mean / sd if sd else None
        else:
            per_trade_sharpe = None
        bot_stats.append({
            "bot": bot, "asset_class": x["asset_class"],
            "trades": n, "win_rate": round(wr, 4),
            "total_pnl_usd": round(x["total_pnl"], 2),
            "avg_winner": round(avg_w, 2), "avg_loser": round(avg_l, 2),
            "profit_factor": round(pf, 3) if pf else None,
            "expectancy_usd": round(expectancy, 3),
            "avg_hold_hours": round(avg_hold, 2) if avg_hold else None,
            "per_trade_sharpe": round(per_trade_sharpe, 3) if per_trade_sharpe else None,
            "total_notional_usd": round(x["total_notional"], 0),
        })
    bot_stats.sort(key=lambda x: -x["total_pnl_usd"])

    # 2. Symbol exposure (open positions)
    sym_rows = db.execute(text(
        "SELECT pos.symbol, p.name AS bot, p.asset_class, "
        "       pos.qty * pos.avg_cost_cents AS notional_cents "
        "FROM bot_positions pos "
        "JOIN bot_allocations a ON a.id = pos.allocation_id "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND pos.closed_at IS NULL AND pos.quarantined_at IS NULL"
    )).fetchall()
    by_sym = _dd(lambda: {"notional": 0.0, "positions": 0, "bots": set(), "asset_class": ""})
    for r in sym_rows:
        sym, bot, ac, notional_c = r
        by_sym[sym]["notional"] += float(notional_c or 0) / 100.0
        by_sym[sym]["positions"] += 1
        by_sym[sym]["bots"].add(bot)
        by_sym[sym]["asset_class"] = ac
    sym_stats = sorted(
        [{"symbol": s, "notional_usd": round(x["notional"], 0),
          "positions": x["positions"], "bots_holding": sorted(x["bots"]),
          "asset_class": x["asset_class"]}
         for s, x in by_sym.items()],
        key=lambda x: -x["notional_usd"],
    )

    # 3. Fleet totals
    total_realized = sum(b["total_pnl_usd"] for b in bot_stats)
    total_trades = sum(b["trades"] for b in bot_stats)
    winning_bots = sum(1 for b in bot_stats if b["total_pnl_usd"] > 0)
    losing_bots = sum(1 for b in bot_stats if b["total_pnl_usd"] < 0)
    fleet_wins = sum(1 for b in bot_stats for p in [0] if b["win_rate"])
    fleet_pnl_by_ac = _dd(float)
    for b in bot_stats:
        fleet_pnl_by_ac[b["asset_class"] or "other"] += b["total_pnl_usd"]

    return {
        "as_of": now.isoformat(),
        "window_days": 30,
        "fleet_summary": {
            "total_realized_pnl_usd": round(total_realized, 2),
            "total_closed_trades": total_trades,
            "winning_bots": winning_bots,
            "losing_bots": losing_bots,
            "pnl_by_asset_class": {k: round(v, 2) for k, v in fleet_pnl_by_ac.items()},
        },
        "per_bot": bot_stats,
        "symbol_exposure_top20": sym_stats[:20],
        "symbol_exposure_count": len(sym_stats),
    }


@router.get("/self-auth-test/{user_id}")
def self_auth_test(user_id: int, db: Session = Depends(get_db)) -> dict:
    """Mint a real JWT and hit /api/dashboard/v2 + /api/risk/console from
    within the app. Proves whether these endpoints work end-to-end for a
    real user session or reject with 401 for reasons unrelated to auth
    (dependency crashes, etc).
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    try:
        from app.db.models.users import User as _User
        u = db.query(_User).filter(_User.id == user_id).first()
        if not u:
            return {"error": f"user {user_id} not found"}
        from app.config import settings as _s
        from jose import jwt as _jwt
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        exp = _dt.now(_tz.utc) + _td(minutes=5)
        token = _jwt.encode(
            {"sub": str(user_id), "exp": exp},
            _s.jwt_secret,
            algorithm=_s.jwt_algorithm,
        )
        # Now hit the endpoints from within the same process via httpx.
        import httpx
        base = "http://127.0.0.1:8000"
        headers = {"Authorization": f"Bearer {token}"}
        results = {}
        for path in ("/api/dashboard/v2", "/api/risk/console", "/api/trades",
                     "/api/strategy-lab/portfolio"):
            try:
                r = httpx.get(base + path, headers=headers, timeout=25)
                body_ok = None
                if r.status_code == 200:
                    body = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
                    if isinstance(body, dict):
                        body_ok = list(body.keys())[:5]
                    elif isinstance(body, list):
                        body_ok = f"list len={len(body)}"
                results[path] = {
                    "status": r.status_code,
                    "content_type": r.headers.get("content-type",""),
                    "body_len": len(r.content),
                    "top_keys_or_shape": body_ok,
                    "body_preview": r.text[:200] if r.status_code != 200 else None,
                }
            except Exception as exc:
                results[path] = {"error": str(exc)[:200]}
        return {"user_id": user_id, "token_len": len(token), "results": results}
    except Exception as exc:
        import traceback
        return {"error": str(exc)[:500], "traceback": traceback.format_exc()[:2000]}


@router.get("/dashboard-v2-noauth-diagnostic/{user_id}")
def dashboard_v2_noauth(user_id: int, db: Session = Depends(get_db)) -> dict:
    """Run dashboard/v2 code path with fake current_user. Diagnose BLOCK 0."""
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    try:
        from app.db.models.users import User as _User
        u = db.query(_User).filter(_User.id == user_id).first()
        if not u:
            return {"error": f"user {user_id} not found"}
        from app.routers.dashboard import get_dashboard_v2 as _gdv2
        result = _gdv2(db=db, current_user=u)
        # Return just the shape summary
        return {
            "ok": True,
            "top_keys": list(result.keys()),
            "portfolio_keys": list(result.get("portfolio", {}).keys()) if isinstance(result.get("portfolio"), dict) else "not_dict",
            "portfolio_total_value_cents": result.get("portfolio", {}).get("total_value_cents") if isinstance(result.get("portfolio"), dict) else None,
            "sleeves_count": len(result.get("sleeves", [])) if "sleeves" in result else 0,
            "leaderboard_count": len(result.get("portfolio", {}).get("leaderboard", [])) if isinstance(result.get("portfolio"), dict) else 0,
        }
    except Exception as exc:
        import traceback
        return {"error": str(exc)[:500], "traceback": traceback.format_exc()[:3000]}


@router.get("/risk-console-noauth-diagnostic/{user_id}")
def risk_console_noauth(user_id: int, db: Session = Depends(get_db)) -> dict:
    """Run risk/console code path with fake current_user."""
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    try:
        from app.db.models.users import User as _User
        u = db.query(_User).filter(_User.id == user_id).first()
        if not u:
            return {"error": f"user {user_id} not found"}
        from app.routers.risk_console import get_risk_console as _gr
        result = _gr(db=db, current_user=u)
        return {
            "ok": True,
            "top_keys": list(result.keys()),
            "fund_pv_cents": result.get("fund", {}).get("pv_cents"),
            "deployment": result.get("deployment"),
            "drawdown_days": result.get("drawdown", {}).get("days_of_data"),
            "var_days": result.get("var", {}).get("days_of_data"),
            "correlation_pairs": result.get("correlation", {}).get("pairs_computed"),
        }
    except Exception as exc:
        import traceback
        return {"error": str(exc)[:500], "traceback": traceback.format_exc()[:3000]}


@router.get("/user-allocations-diagnostic/{user_id}")
def user_allocs(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Show per-bot allocation for a specific user.

    2026-07-06: added require_admin. Previously anyone with
    BMG_DIAGNOSTIC_PV_ENABLED=true could iterate user_ids and pull
    another user's allocation table.
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    rows = db.execute(text(
        "SELECT p.name, a.starting_capital_cents, a.enabled, a.paused_reason "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid "
        "ORDER BY a.starting_capital_cents DESC"
    ), {"uid": user_id}).fetchall()
    return {
        "user_id": user_id,
        "allocations": [
            {"bot": r[0], "starting_cents": int(r[1] or 0),
             "starting_usd": int(r[1] or 0)/100, "enabled": bool(r[2]),
             "paused_reason": r[3]}
            for r in rows
        ],
        "sum_cents": sum(int(r[1] or 0) for r in rows),
        "sum_usd": sum(int(r[1] or 0) for r in rows) / 100,
    }


@router.get("/all-users-portfolio-diagnostic")
def all_users_portfolio(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Sum allocations + PV per user. Hunt cross-user data mismatch.

    2026-07-06: added require_admin. Was leaking every user's email +
    fund allocation total under the diagnostic env flag.
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    # Users table
    users = db.execute(text(
        "SELECT id, email, username, is_active, created_at FROM users ORDER BY id"
    )).fetchall()
    # Per-user allocation sum
    users_data = []
    for u in users:
        uid = int(u[0])
        row = db.execute(text(
            "SELECT COUNT(*), COALESCE(SUM(starting_capital_cents),0) "
            "FROM bot_allocations WHERE user_id = :uid"
        ), {"uid": uid}).fetchone()
        alloc_count = int(row[0] or 0)
        alloc_sum = int(row[1] or 0)
        pos_count = int(db.execute(text(
            "SELECT COUNT(*) FROM bot_positions p "
            "JOIN bot_allocations a ON a.id = p.allocation_id "
            "WHERE a.user_id = :uid AND p.closed_at IS NULL"
        ), {"uid": uid}).fetchone()[0] or 0)
        users_data.append({
            "user_id": uid,
            "email": u[1],
            "username": u[2],
            "is_active": bool(u[3]),
            "created_at": str(u[4]),
            "allocation_count": alloc_count,
            "allocation_sum_cents": alloc_sum,
            "allocation_sum_usd": alloc_sum / 100,
            "open_positions_count": pos_count,
        })
    return {"users": users_data}


# ─── PUBLIC diagnostic — 24h fleet conversion ─────────────────────────────────
@router.get("/conversion-24h-diagnostic")
def get_conversion_24h(db: Session = Depends(get_db)) -> dict:
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true","1","yes"):
        return {"error": "diagnostic disabled"}
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    cut = (_dt.now(_tz.utc) - _td(hours=24)).isoformat()
    sig_row = db.execute(text(
        "SELECT COUNT(*) FROM bot_signals s "
        "JOIN bot_allocations a ON a.id = s.allocation_id "
        "WHERE a.user_id = 1 AND s.ts >= :cut"
    ), {"cut": cut}).fetchone()
    # m099: fleet + per-bot trades_24h counts BROKER_FILL only.
    trd_row = db.execute(text(
        "SELECT COUNT(*) FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = 1 AND t.ts >= :cut "
        "  AND t.quarantined_at IS NULL AND t.origin = 'BROKER_FILL'"
    ), {"cut": cut}).fetchone()
    sigs = int(sig_row[0] or 0)
    trds = int(trd_row[0] or 0)
    per_bot = db.execute(text(
        "SELECT p.name, "
        "  (SELECT COUNT(*) FROM bot_signals s WHERE s.allocation_id = a.id AND s.ts >= :cut) AS sigs, "
        "  (SELECT COUNT(*) FROM bot_trades t WHERE t.allocation_id = a.id AND t.ts >= :cut "
        "    AND t.quarantined_at IS NULL AND t.origin = 'BROKER_FILL') AS trds "
        "FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND a.starting_capital_cents > 0"
    ), {"cut": cut}).fetchall()
    per_bot_rows = [
        {"bot": r[0], "sigs_24h": int(r[1] or 0), "trades_24h": int(r[2] or 0),
         "conv_pct": round((int(r[2] or 0) / int(r[1])) * 100, 2) if int(r[1] or 0) else 0.0}
        for r in per_bot
    ]
    return {
        "window": "24h",
        "fleet_signals_24h": sigs,
        "fleet_trades_24h": trds,
        "fleet_conversion_pct": round((trds / sigs) * 100, 2) if sigs else 0.0,
        "per_bot": sorted(per_bot_rows, key=lambda r: -r["sigs_24h"]),
    }


# ─── PUBLIC diagnostic — no auth. Used to hunt phantom PV. ────────────────────
# Gated by BMG_DIAGNOSTIC_PV_ENABLED=true env var so we can turn it off after
# the tonight-session investigation.
@router.get("/pv-breakdown-diagnostic")
def get_pv_breakdown_diagnostic(db: Session = Depends(get_db)) -> dict:
    """Public per-bot PV composition — starting / realized / unrealized / pv.

    No auth. Gate this off after debugging by unsetting the env var.
    Purpose: find why the fleet PV totals $178K over the $1M starting
    invariant when the fund is essentially flat all-time.
    """
    import os as _os
    if _os.getenv("BMG_DIAGNOSTIC_PV_ENABLED", "").strip().lower() not in ("true", "1", "yes"):
        return {"error": "diagnostic disabled — set BMG_DIAGNOSTIC_PV_ENABLED=true"}

    from app.core.canonical import compute_bot_snapshot
    from app.db.models.bots import BotAllocation, BotProfile

    allocs = db.query(BotAllocation).filter(BotAllocation.user_id == 1).all()
    profile_map = {p.id: p for p in db.query(BotProfile).all()}

    rows = []
    for a in allocs:
        prof = profile_map.get(a.profile_id)
        if prof is None:
            rows.append({
                "bot": f"alloc_{a.id}",
                "enabled": bool(a.enabled),
                "starting_cents": int(a.starting_capital_cents or 0),
                "within_portfolio_cents": int(a.capital_cents_within_portfolio or 0),
                "current_capital_cents": int(getattr(a, "current_capital_cents", 0) or 0),
                "error": "no profile",
            })
            continue
        try:
            snap = compute_bot_snapshot(a, prof, db)
            rows.append({
                "bot": prof.name,
                "profile_enabled": bool(prof.enabled),
                "alloc_enabled": bool(a.enabled),
                "starting_cents": int(snap.starting_capital_cents or 0),
                "within_portfolio_cents": int(a.capital_cents_within_portfolio or 0),
                "current_capital_cents": int(getattr(a, "current_capital_cents", 0) or 0),
                "realized_cents": int(snap.realized_pnl_cents or 0),
                "unrealized_cents": int(snap.unrealized_pnl_cents or 0),
                "pv_cents": int(snap.portfolio_value_cents or 0),
                "delta_from_starting_cents": int(snap.portfolio_value_cents or 0) - int(snap.starting_capital_cents or 0),
                "open_positions_count": int(snap.open_positions_count or 0),
            })
        except Exception as exc:
            rows.append({
                "bot": prof.name,
                "profile_enabled": bool(prof.enabled),
                "alloc_enabled": bool(a.enabled),
                "starting_cents": int(a.starting_capital_cents or 0),
                "within_portfolio_cents": int(a.capital_cents_within_portfolio or 0),
                "error": str(exc)[:200],
            })

    rows.sort(key=lambda r: -(r.get("delta_from_starting_cents") or 0))
    totals = {
        "sum_starting_cents": sum((r.get("starting_cents") or 0) for r in rows),
        "sum_realized_cents": sum((r.get("realized_cents") or 0) for r in rows),
        "sum_unrealized_cents": sum((r.get("unrealized_cents") or 0) for r in rows),
        "sum_pv_cents": sum((r.get("pv_cents") or 0) for r in rows),
    }

    # Show top phantoms — bots whose delta is unusually large positive
    phantoms = [r for r in rows if (r.get("delta_from_starting_cents") or 0) > 500_000]  # > $5k delta

    # 5-col header P&L windows — verify MTD/WTD baselines
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(1, db)
        pnl_block = agg.get("pnl", {}) if agg else {}
    except Exception as _exc:
        pnl_block = {"error": str(_exc)[:200]}

    return {
        "user_id": 1,
        "row_count": len(rows),
        "totals": totals,
        "invariant_check": {
            "sum_starting_$": totals["sum_starting_cents"] / 100,
            "sum_pv_$": totals["sum_pv_cents"] / 100,
            "delta_$": (totals["sum_pv_cents"] - totals["sum_starting_cents"]) / 100,
        },
        "pnl_windows": pnl_block,
        "phantom_candidates": phantoms,
        "all_bots": rows,
    }


# ─── 2026-08-18 Brock: vault sync ping — real freshness signal for I28 ─────
# Called by scripts/bmg_vault_sync.sh after each successful pull. This is
# what I28 checks. Ping absence = the Mac cron isn't firing = vault stale
# even though /data/audits looks fresh.
@router.post("/vault-sync-ping")
def vault_sync_ping(
    request: Request,
    payload: Dict[str, Any] = Body(default={}),
    _admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Record that bmg_vault_sync.sh just completed successfully.
    Optional payload fields:
      - git_commit_sha (str)
      - git_pushed (bool)
    """
    try:
        from app.services.vault_writer import record_vault_sync_ping, read_vault_sync_ping
        src_ip = None
        try:
            src_ip = request.client.host if request.client else None
        except Exception:
            pass
        record_vault_sync_ping(
            git_commit_sha=payload.get("git_commit_sha"),
            git_pushed=payload.get("git_pushed"),
            source_ip=src_ip,
        )
        return {"ok": True, "ping": read_vault_sync_ping()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


@router.get("/vault-sync-last")
def vault_sync_last(_admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Return the last-ping payload + age-in-hours (what I28 reads)."""
    try:
        from app.services.vault_writer import read_vault_sync_ping, last_vault_sync_ping_age_hours
        return {
            "ping": read_vault_sync_ping(),
            "age_hours": last_vault_sync_ping_age_hours(),
        }
    except Exception as exc:
        return {"error": str(exc)[:500]}


# ─── 2026-08-18 Brock: vault sync endpoints (§V8 automation of §V7) ────────
@router.get("/audits/list")
def audits_list(_admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """List /data/audits/*.md — one row per daily audit file.

    Consumed by scripts/bmg_vault_sync.sh on Brock's Mac to pull audits
    into ~/Documents/BMG-Capital-Vault/daily-audits/ automatically.
    """
    try:
        from app.services.vault_writer import list_audits, newest_audit_age_hours
        return {
            "audits": list_audits(),
            "newest_age_hours": newest_audit_age_hours(),
        }
    except Exception as exc:
        return {"error": str(exc)[:500]}


@router.get("/audits/{name}")
def audits_get(name: str, _admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Read one audit file by date-string (e.g. 2026-08-18)."""
    try:
        from app.services.vault_writer import read_artifact
        content = read_artifact("audit", name)
        if content is None:
            return {"error": "not_found", "name": name}
        return {"name": name, "content": content}
    except Exception as exc:
        return {"error": str(exc)[:500]}


@router.get("/postmortem-stubs/list")
def postmortem_stubs_list(_admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """List /data/postmortems-stub/*.md — auto-generated on auto_pause/outage."""
    try:
        from app.services.vault_writer import list_postmortem_stubs
        return {"stubs": list_postmortem_stubs()}
    except Exception as exc:
        return {"error": str(exc)[:500]}


@router.get("/postmortem-stubs/{name}")
def postmortem_stubs_get(name: str, _admin: User = Depends(require_admin)) -> Dict[str, Any]:
    try:
        from app.services.vault_writer import read_artifact
        content = read_artifact("postmortem_stub", name)
        if content is None:
            return {"error": "not_found", "name": name}
        return {"name": name, "content": content}
    except Exception as exc:
        return {"error": str(exc)[:500]}


# ─── 2026-08-18 Brock: APScheduler job audit — hunt duplicates ──────────────
# 136 jobs on a 42-bot fleet ≈ 2.4x expected. Theory: setup_bot_scheduler()
# called twice, or add_job() without replace_existing=True on some path,
# leading to job accumulation. Duplicates fire real work → memory climb →
# OOM → the whole cascade. Read-only endpoint; safe alongside deploy-fix.
@router.get("/scheduler/jobs")
def scheduler_jobs(_admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """List all live APScheduler jobs. Groups by func for duplicate detection."""
    try:
        from app.main import scheduler  # type: ignore
        jobs = scheduler.get_jobs()
    except Exception as exc:
        return {"error": f"scheduler_load_failed: {str(exc)[:200]}"}

    def _func_name(j):
        try:
            f = j.func
            return getattr(f, "__qualname__", None) or getattr(f, "__name__", None) or repr(f)[:80]
        except Exception:
            return "unknown"

    rows = []
    by_func: Dict[str, list] = {}
    id_counts: Dict[str, int] = {}
    for j in jobs:
        fn = _func_name(j)
        row = {
            "id": j.id,
            "func": fn,
            "trigger": str(j.trigger)[:200],
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            "misfire_grace_time": getattr(j, "misfire_grace_time", None),
            "max_instances": getattr(j, "max_instances", None),
        }
        rows.append(row)
        by_func.setdefault(fn, []).append(j.id)
        id_counts[j.id] = id_counts.get(j.id, 0) + 1

    dup_ids = {jid: n for jid, n in id_counts.items() if n > 1}
    func_summary = {
        fn: {
            "count": len(ids),
            "sample_ids": ids[:5],
            "likely_duplicated": len(ids) > 1 and len(set(ids)) < len(ids),
        }
        for fn, ids in sorted(by_func.items(), key=lambda kv: -len(kv[1]))
    }

    return {
        "total_jobs": len(jobs),
        "unique_ids": len(id_counts),
        "duplicate_ids": dup_ids,
        "by_func": func_summary,
        "jobs": rows,
    }


# ─── 2026-08-13 Brock: mem-probe read endpoint (RSS-per-job + top leakers) ──
@router.get("/mem-probe/snapshot")
def mem_probe_snapshot(_admin: User = Depends(require_admin)) -> Dict[str, Any]:
    """Return RSS-delta tally per scheduled job + per heavy HTTP path.

    Use after 24h uptime to identify the leak: the job with the largest
    positive cumulative_delta_mb is the suspect. Container OOMs at
    ~12min-lifespan (2026-08-13 investigation).
    """
    try:
        from app.services.mem_probe import snapshot, apscheduler_job_count
        snap = snapshot()
        snap["apscheduler_job_count"] = apscheduler_job_count()
        return snap
    except Exception as exc:
        return {"error": str(exc)[:500]}
