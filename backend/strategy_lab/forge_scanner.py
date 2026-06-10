"""
The Forge scanner — runs every 5 minutes, evaluates all active forge bots
(user-built custom bots) against their watchlists × strategy stacks.
Fires to #my-signals Discord when a combo crosses its confidence threshold.

Hooked into APScheduler by setup_bot_scheduler() in bot_scheduler.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def run_forge_scan() -> None:
    """Main entry point — called by cron every 5 min."""
    import os
    if not os.getenv("ENABLE_STRATEGY_FORGE", "false").strip().lower() == "true":
        return

    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        _run_scan(db)
    except Exception as exc:
        logger.error("[forge-scanner] unhandled error: %s", exc, exc_info=True)
    finally:
        db.close()


def _run_scan(db) -> None:
    from app.db.models.forge import UserForgeBot, UserForgeSignal
    from strategy_lab.scout_catalog import SCOUT_CATALOG
    from app.routers.scout import _fetch_bars_for_ticker, _run_strategy

    bots = (
        db.query(UserForgeBot)
        .filter(UserForgeBot.status == "active")
        .all()
    )
    if not bots:
        return

    logger.info("[forge-scanner] scanning %d active forge bots", len(bots))

    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(hours=24)
    fired = 0

    # Fetch each unique ticker once across all bots.
    ticker_set: set[str] = set()
    for bot in bots:
        for ticker in json.loads(bot.watchlist or "[]"):
            ticker_set.add(ticker)

    bars_cache: dict[str, list[dict]] = {}
    for ticker in ticker_set:
        bars = _fetch_bars_for_ticker(ticker)
        if bars:
            bars_cache[ticker] = bars
        else:
            logger.debug("[forge-scanner] no bars for %s — skipping", ticker)

    for bot in bots:
        strategies = json.loads(bot.strategies or "[]")
        watchlist = json.loads(bot.watchlist or "[]")

        bot.last_scanned_at = now

        for ticker in watchlist:
            bars = bars_cache.get(ticker)
            if not bars:
                continue

            for strategy_id in strategies:
                # 24h dedup per (bot, ticker, strategy)
                recent = (
                    db.query(UserForgeSignal)
                    .filter(
                        UserForgeSignal.forge_bot_id == bot.id,
                        UserForgeSignal.ticker == ticker,
                        UserForgeSignal.strategy_id == strategy_id,
                        UserForgeSignal.created_at >= cooldown_cutoff,
                    )
                    .first()
                )
                if recent:
                    continue

                result = _run_strategy(strategy_id, ticker, bars)
                if not result or not result.get("armed"):
                    continue

                meta = SCOUT_CATALOG.get(strategy_id, {})
                threshold = meta.get("confidence_threshold", 0.45)
                confidence = result["confidence"]

                if confidence < threshold or result["side"] == "hold":
                    continue

                sig_row = UserForgeSignal(
                    forge_bot_id=bot.id,
                    user_id=bot.user_id,
                    ticker=ticker,
                    strategy_id=strategy_id,
                    side=result["side"],
                    confidence=confidence,
                    entry_price=result.get("entry"),
                    stop_price=result.get("stop"),
                    target_price=result.get("target"),
                    reason=result.get("reason") or "",
                )
                db.add(sig_row)
                bot.last_fired_at = now

                try:
                    db.flush()
                    _post_forge_signal(bot, result, strategy_id, ticker)
                except Exception as exc:
                    logger.warning(
                        "[forge-scanner] Discord post failed bot=%s %s/%s: %s",
                        bot.name, ticker, strategy_id, exc,
                    )

                fired += 1

    db.commit()
    logger.info("[forge-scanner] done — %d bots scanned, %d signals fired", len(bots), fired)


def _post_forge_signal(bot, result: dict, strategy_id: str, ticker: str) -> None:
    from app.services.discord_public import post_signal
    from strategy_lab.scout_catalog import SCOUT_CATALOG

    meta = SCOUT_CATALOG.get(strategy_id, {})
    display_name = meta.get("display_name", strategy_id)

    signal_dict = {
        "bot":          bot.name,
        "bot_name":     bot.name,
        "symbol":       ticker,
        "side":         result["side"],
        "strategy":     display_name,
        "confidence":   result["confidence"],
        "price":        result.get("entry"),
        "stop":         result.get("stop"),
        "target":       result.get("target"),
        "reason":       result.get("reason") or "",
        "notional_usd": None,
    }
    post_signal(signal_dict, source="custom_bot")
    logger.warning(
        "[forge] fired %s %s → %s / %s conf=%.2f",
        result["side"], ticker, bot.name, display_name, result["confidence"],
    )
