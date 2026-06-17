"""Admin endpoints — internal ops, not exposed in public docs."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User

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
                prof_map.get(r.profile_id, str(r.profile_id)): r.last_ts.isoformat() if r.last_ts else None
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
        alloc.capital_cents_within_portfolio or alloc.starting_capital_cents or 5_000_000
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
                "ts":               s.ts.isoformat() if s.ts else None,
                "symbol":           s.symbol,
                "side":             s.side,
                "confidence":       s.confidence,
                "price":            s.price,
                "discord_posted_at": s.discord_posted_at.isoformat() if s.discord_posted_at else None,
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
                "ts":            t.ts.isoformat() if t.ts else None,
                "symbol":        t.symbol,
                "side":          t.side,
                "qty":           t.qty,
                "price":         t.price,
                "pnl_cents":     t.pnl_cents,
                "quarantined_at": t.quarantined_at.isoformat() if t.quarantined_at else None,
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
                "ts":        s.discord_posted_at.isoformat() if s.discord_posted_at else None,
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
