"""
Strategy Scout scanner — runs every 5 minutes, evaluates all active user
setups, and fires Discord alerts to #my-signals when confidence crosses
the strategy threshold.

Hooked into APScheduler by setup_bot_scheduler() in bot_scheduler.py.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def run_scout_scan() -> None:
    """Main entry point — called by cron every 5 min."""
    import os
    if not os.getenv("ENABLE_STRATEGY_SCOUT", "false").strip().lower() == "true":
        return

    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        _run_scan(db)
    except Exception as exc:
        logger.error("[scout-scanner] unhandled error: %s", exc, exc_info=True)
    finally:
        db.close()


def _run_scan(db) -> None:
    from sqlalchemy import text as _text
    from app.db.models.scout import UserScoutSetup, UserScoutSignal
    from strategy_lab.scout_catalog import SCOUT_CATALOG
    from app.routers.scout import _fetch_bars_for_ticker, _run_strategy

    rows = (
        db.query(UserScoutSetup)
        .filter(UserScoutSetup.status == "active")
        .all()
    )
    if not rows:
        return

    logger.info("[scout-scanner] scanning %d active setups", len(rows))

    # Group setups by ticker so we only fetch bars once per ticker.
    by_ticker: dict[str, list[UserScoutSetup]] = defaultdict(list)
    for setup in rows:
        by_ticker[setup.ticker].append(setup)

    now = datetime.now(timezone.utc)
    fired = 0

    for ticker, setups in by_ticker.items():
        bars = _fetch_bars_for_ticker(ticker)
        if not bars:
            logger.debug("[scout-scanner] no bars for %s — skipping", ticker)
            continue

        for setup in setups:
            result = _run_strategy(setup.strategy_id, ticker, bars)

            # Always update last_scanned_at and last_confidence.
            setup.last_scanned_at = now
            if result:
                setup.last_confidence = result["confidence"]

            if not result or not result.get("armed"):
                continue

            meta = SCOUT_CATALOG.get(setup.strategy_id, {})
            threshold = meta.get("confidence_threshold", 0.45)
            confidence = result["confidence"]

            if confidence < threshold or result["side"] == "hold":
                continue

            # Fire signal.
            sig_row = UserScoutSignal(
                setup_id=setup.id,
                user_id=setup.user_id,
                ticker=ticker,
                strategy_id=setup.strategy_id,
                side=result["side"],
                confidence=confidence,
                entry_price=result.get("entry"),
                stop_price=result.get("stop"),
                target_price=result.get("target"),
                reason=result.get("reason") or "",
            )
            db.add(sig_row)
            setup.status = "fired"
            setup.fired_at = now

            try:
                db.flush()
                _post_scout_signal(setup, result, sig_row.id)
            except Exception as exc:
                logger.warning("[scout-scanner] Discord post failed for %s/%s: %s",
                               ticker, setup.strategy_id, exc)

            fired += 1

    db.commit()
    logger.info("[scout-scanner] done — %d setups scanned, %d signals fired", len(rows), fired)


def _post_scout_signal(setup: object, result: dict, signal_id: int) -> None:
    from app.services.discord_public import post_signal

    display_name = result.get("display_name") or setup.strategy_id  # type: ignore[attr-defined]
    signal_dict = {
        "bot":        "scout",
        "symbol":     setup.ticker,                                   # type: ignore[attr-defined]
        "side":       result["side"],
        "strategy":   display_name,
        "confidence": result["confidence"],
        "price":      result.get("entry"),
        "stop":       result.get("stop"),
        "target":     result.get("target"),
        "reason":     result.get("reason") or "",
        "notional_usd": None,
    }
    post_signal(signal_dict, source="scout")
    logger.warning("[scout] fired %s %s → %s conf=%.2f",
                   result["side"], setup.ticker, display_name, result["confidence"])  # type: ignore[attr-defined]
