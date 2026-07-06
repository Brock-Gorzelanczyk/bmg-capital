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

    now = datetime.now(timezone.utc).isoformat()

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

    for pos in to_quarantine:
        pos.quarantined_at = now
        pos.quarantine_reason = "dedupe_duplicate_open_position"
    db.commit()

    return {
        "ok": True,
        "positions_quarantined": len(to_quarantine),
        "unique_positions_kept": len(seen),
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
        )
        db.add(pos)
        db.flush()

        trade = BotTrade(
            allocation_id=alloc.id,
            symbol=_SYN_SYMBOL,
            side="buy",
            qty=float(_SYN_CONTRACTS),
            fill_price_cents=_SYN_ENTRY_CENTS,
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
    portfolio_breakdown_pv = sum(
        int(p.get("portfolio_value_cents") or 0) for p in (agg.get("portfolios") or [])
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
    from app.services.capital_invariant import check_capital_invariant
    status = check_capital_invariant(db, user_id=1)
    return {
        "status":                status.status,
        "is_valid":              status.is_valid,
        "current_sum_cents":     status.current_sum_cents,
        "expected_sum_cents":    100_000_000,
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
               (SELECT COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0) FROM bot_positions bp
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
                   AND bt.quarantined_at IS NULL) AS trades_window,
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
               (SELECT COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0) FROM bot_positions bp
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
                   AND bt.quarantined_at IS NULL) AS trades_window,
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
               (SELECT COALESCE(SUM(bp.qty * bp.avg_cost_cents), 0) FROM bot_positions bp
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
                   AND bt.quarantined_at IS NULL) AS trades_window,
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
def hedge_fund_audit(db: Session = Depends(get_db)) -> dict:
    """Comprehensive audit: per-bot P&L, hit rate, hold time, exposure,
    correlation, deployment ratio, symbol concentration."""
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
def user_allocs(user_id: int, db: Session = Depends(get_db)) -> dict:
    """Show per-bot allocation for a specific user."""
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
def all_users_portfolio(db: Session = Depends(get_db)) -> dict:
    """Sum allocations + PV per user. Hunt cross-user data mismatch."""
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
    trd_row = db.execute(text(
        "SELECT COUNT(*) FROM bot_trades t "
        "JOIN bot_allocations a ON a.id = t.allocation_id "
        "WHERE a.user_id = 1 AND t.ts >= :cut AND t.quarantined_at IS NULL"
    ), {"cut": cut}).fetchone()
    sigs = int(sig_row[0] or 0)
    trds = int(trd_row[0] or 0)
    per_bot = db.execute(text(
        "SELECT p.name, "
        "  (SELECT COUNT(*) FROM bot_signals s WHERE s.allocation_id = a.id AND s.ts >= :cut) AS sigs, "
        "  (SELECT COUNT(*) FROM bot_trades t WHERE t.allocation_id = a.id AND t.ts >= :cut AND t.quarantined_at IS NULL) AS trds "
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
