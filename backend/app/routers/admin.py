"""Admin endpoints — internal ops, not exposed in public docs."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Query
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

    return result
