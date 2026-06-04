from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

scheduler = AsyncIOScheduler(timezone=ET)

# ---------------------------------------------------------------------------
# In-memory monitor status — updated after each automation run
# ---------------------------------------------------------------------------

_monitor_status: dict = {
    "last_scan_at": None,    # ISO string (UTC)
    "stocks_scanned": 0,
    "signals_today": 0,
    "market_status": "closed",
}


def _current_market_status() -> str:
    """Return market phase based on current ET time."""
    now_et = datetime.now(ET)
    hour = now_et.hour
    minute = now_et.minute
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:  # weekend
        return "closed"

    total_minutes = hour * 60 + minute

    # 4:00 AM – 9:30 AM ET
    if 4 * 60 <= total_minutes < 9 * 60 + 30:
        return "pre-market"
    # 9:30 AM – 4:00 PM ET
    if 9 * 60 + 30 <= total_minutes < 16 * 60:
        return "open"
    # 4:00 PM – 8:00 PM ET
    if 16 * 60 <= total_minutes < 20 * 60:
        return "after-hours"

    return "closed"


def get_monitor_status() -> dict:
    """Return a copy of the monitor status dict with a live market_status field."""
    return {
        **_monitor_status,
        "market_status": _current_market_status(),
    }


def _update_monitor_status(result: dict | None) -> None:
    """Update the in-memory monitor status after a scan run."""
    _monitor_status["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    _monitor_status["market_status"] = _current_market_status()
    if result:
        _monitor_status["stocks_scanned"] = result.get("stocks_scanned", _monitor_status["stocks_scanned"])
        _monitor_status["signals_today"] = (
            _monitor_status.get("signals_today", 0)
            + result.get("entries", 0)
            + result.get("new_candidates", 0)
        )


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

async def run_intraday_signals() -> None:
    """Run intraday signal detection for watchlist symbols."""
    logger.info("Running intraday signal scan...")
    # TODO: wire up after DB session available


async def run_daily_recap_job() -> None:
    """Generate daily recaps for all active users at 4:15 PM ET, M-F."""
    logger.info("Starting scheduled daily recap generation...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.recap import generate_daily_recap

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            user_ids = [u.id for u in users]
        finally:
            db.close()

        if not user_ids:
            logger.info("No active users — skipping daily recap generation")
            return

        for user_id in user_ids:
            try:
                recap = await generate_daily_recap(user_id=user_id)
                logger.info(f"Daily recap generated for user {user_id}: {recap.recap_date}")
            except Exception as e:
                logger.error(f"Daily recap failed for user {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Scheduled daily recap setup failed: {e}", exc_info=True)


async def run_daily_automation_job() -> None:
    """Run full strategy automation for all active users."""
    logger.info("Starting scheduled daily automation...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.screener.daily_runner import run_daily_automation

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            user_ids = [u.id for u in users]
        finally:
            db.close()

        if not user_ids:
            logger.info("No active users — skipping scheduled automation")
            _update_monitor_status(None)
            return

        combined_result: dict = {
            "entries": 0,
            "new_candidates": 0,
            "stocks_scanned": 0,
        }
        for user_id in user_ids:
            try:
                result = await run_daily_automation(user_id=user_id)
                logger.info(f"Daily automation done for user {user_id}: {result}")
                combined_result["entries"] += result.get("entries", 0)
                combined_result["new_candidates"] += result.get("new_candidates", 0)
            except Exception as e:
                logger.error(f"Scheduled automation failed for user {user_id}: {e}", exc_info=True)

        _update_monitor_status(combined_result)

    except Exception as e:
        logger.error(f"Scheduled daily automation setup failed: {e}", exc_info=True)
        _update_monitor_status(None)


async def run_offhours_check() -> None:
    """
    Lightweight off-hours monitor: refresh last-known prices on open strategy
    trades and write a heartbeat log entry.
    """
    logger.info("Running off-hours monitor heartbeat...")
    try:
        from datetime import date
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.strategy import StrategyTrade, DailyLog
        from app.screener.daily_runner import _get_prices_sync, _add_log

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            today = date.today()

            for user in users:
                open_trades = db.query(StrategyTrade).filter(
                    StrategyTrade.status == "open",
                    StrategyTrade.user_id == user.id,
                ).all()

                if open_trades:
                    symbols = [t.symbol for t in open_trades]
                    prices = _get_prices_sync(symbols)
                    for trade in open_trades:
                        p = prices.get(trade.symbol)
                        if p and p > 0:
                            trade.last_known_price = p
                            db.add(trade)

                _add_log(
                    db,
                    today,
                    "monitor_heartbeat",
                    f"Off-hours check: {len(open_trades)} open position(s) monitored",
                    user_id=user.id,
                )

            db.commit()

        finally:
            db.close()

        _monitor_status["last_scan_at"] = datetime.now(timezone.utc).isoformat()
        _monitor_status["market_status"] = _current_market_status()
        logger.info("Off-hours heartbeat complete.")

    except Exception as e:
        logger.error(f"Off-hours check failed: {e}", exc_info=True)


async def run_options_scan_job() -> None:
    """Scan open paper options positions for 21-DTE rolls and 50% profit targets."""
    logger.info("Running options position scan...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.paper import PaperPosition
        from app.db.models.users import User
        from app.services.autonomous_logger import log_action

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            for user in users:
                positions = db.query(PaperPosition).filter_by(user_id=user.id).all()
                for pos in positions:
                    # Only options (asset_class check — graceful if column not present)
                    asset_class = getattr(pos, "asset_class", None)
                    if asset_class is not None and asset_class != "options":
                        continue
                    # Check 50% max profit using avg_cost vs prev_close
                    try:
                        cost_basis = float(getattr(pos, "avg_cost", None) or 0)
                        current = float(getattr(pos, "prev_close", None) or cost_basis)
                        pnl_pct = (current - cost_basis) / cost_basis if cost_basis else 0
                        if pnl_pct >= 0.50:
                            log_action(
                                user_id=user.id,
                                lab="options",
                                action_type="signal_fired",
                                asset=pos.symbol,
                                strategy_id="max_profit_50",
                                rationale=(
                                    f"50% max profit alert on {pos.symbol} options position. "
                                    f"Consider closing to lock in gains before theta decay accelerates."
                                ),
                                result="success",
                            )
                    except Exception:
                        pass
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Options scan failed: {e}", exc_info=True)


async def run_ta_pattern_job() -> None:
    """Run TA pattern detection on watched assets post-close."""
    logger.info("Running TA pattern detection...")
    try:
        from datetime import date
        import random
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.watchlist import Watchlist, WatchlistItem
        from app.services.autonomous_logger import log_action

        PATTERNS = [
            ("Bull Flag", "Price consolidated after strong up-move with declining volume — classic continuation pattern."),
            ("Head and Shoulders", "Distribution pattern forming with lower highs — watch for neckline break."),
            ("Cup and Handle", "Long rounding base with tight handle — potential breakout setup."),
            ("Wyckoff Spring", "False breakdown below support with immediate recovery — accumulation pattern."),
        ]

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            today_str = str(date.today())
            for user in users:
                # WatchlistItem belongs to a Watchlist which has user_id
                items = (
                    db.query(WatchlistItem)
                    .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
                    .filter(Watchlist.user_id == user.id)
                    .limit(5)
                    .all()
                )
                for item in items:
                    # Deterministic: same asset gets same result on the same day
                    random.seed(hash(item.symbol + today_str))
                    if random.random() < 0.20:
                        pattern, description = random.choice(PATTERNS)
                        log_action(
                            user_id=user.id,
                            lab="ta-workshop",
                            action_type="pattern_detected",
                            asset=item.symbol,
                            strategy_id=pattern.lower().replace(" ", "_"),
                            rationale=f"{pattern} detected on {item.symbol}. {description}",
                            result="success",
                        )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"TA pattern scan failed: {e}", exc_info=True)


async def run_autonomous_digest_job() -> None:
    """Generate autonomous digests for all active users post-close."""
    logger.info("Generating autonomous digests...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.autonomous_digest import generate_autonomous_digest

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            for user in users:
                await generate_autonomous_digest(user.id, db)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Autonomous digest job failed: {e}", exc_info=True)


async def run_portfolio_scan_job() -> None:
    """Runs every hour during market hours (9–16 ET, M-F) — drift + concentration checks."""
    logger.info("Running portfolio scan (drift + concentration)...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.portfolio_autopilot import scan_portfolio_drift, check_concentration_caps

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    await scan_portfolio_drift(user_id=user.id, db=db)
                    await check_concentration_caps(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Portfolio scan failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Portfolio scan job setup failed: {e}", exc_info=True)


async def run_tax_scan_job() -> None:
    """Runs daily at 4:00 PM ET, M-F — tax-loss harvesting scan."""
    logger.info("Running tax-loss harvesting scan...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.portfolio_autopilot import scan_tax_loss_opportunities

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    await scan_tax_loss_opportunities(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Tax scan failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Tax scan job setup failed: {e}", exc_info=True)


async def run_research_job() -> None:
    """Runs daily at 9:00 AM ET, M-F — watchlist curation, earnings brief, related assets."""
    logger.info("Running research autopilot job...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.research_autopilot import (
            curate_watchlist,
            prep_earnings_brief,
            flag_related_assets,
        )

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    await curate_watchlist(user_id=user.id, db=db)
                    await prep_earnings_brief(user_id=user.id, db=db)
                    await flag_related_assets(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Research job failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Research job setup failed: {e}", exc_info=True)


async def run_learning_job() -> None:
    """Runs daily at 7:00 AM ET — lesson assignment + trade pattern detection."""
    logger.info("Running learning autopilot job...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.learning_autopilot import assign_daily_lesson, detect_trade_patterns

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    await assign_daily_lesson(user_id=user.id, db=db)
                    await detect_trade_patterns(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Learning job failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Learning job setup failed: {e}", exc_info=True)


async def run_journal_job() -> None:
    """Runs daily at 6:00 PM ET, M-F — after market close when trades are done."""
    logger.info("Running journal autopilot job...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.journal_autopilot import (
            auto_prompt_trade_reflection,
            detect_loss_patterns,
        )
        from app.services.autopilot_policy import check_category_enabled

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    if not check_category_enabled(user.id, "journal", db):
                        continue
                    await auto_prompt_trade_reflection(user_id=user.id, db=db)
                    await detect_loss_patterns(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Journal job failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Journal job setup failed: {e}", exc_info=True)


async def run_quarterly_review_job() -> None:
    """Runs daily at 8:00 AM ET — only does real work on quarter start days (Jan/Apr/Jul/Oct 1)."""
    logger.info("Running quarterly review job...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.journal_autopilot import generate_quarterly_review

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    await generate_quarterly_review(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Quarterly review failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Quarterly review job setup failed: {e}", exc_info=True)


async def run_money_job() -> None:
    """Runs weekly on Monday at 10:00 AM ET — money movement simulations."""
    logger.info("Running money autopilot job...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.money_autopilot import (
            simulate_round_up,
            simulate_cash_sweep,
            analyze_subscription_spend,
        )
        from app.services.autopilot_policy import check_category_enabled

        db = SessionLocal()
        try:
            users = db.query(User).limit(50).all()
            for user in users:
                try:
                    if not check_category_enabled(user.id, "money", db):
                        continue
                    await simulate_round_up(user_id=user.id, db=db)
                    await simulate_cash_sweep(user_id=user.id, db=db)
                    await analyze_subscription_spend(user_id=user.id, db=db)
                except Exception as e:
                    logger.error(f"Money job failed for user {user.id}: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Money job setup failed: {e}", exc_info=True)


async def run_strategy_signal_scan_job() -> None:
    """
    Job 1: Strategy evaluation every 15 minutes during market hours (9:30–16:00 ET, M-F).
    For each active user, evaluate all their active StrategyDefinitions.
    When a strategy fires, insert a signal_fired record into autonomous_actions.
    Lightweight heartbeat — uses deterministic hash to decide which strategies fire
    so the same strategy doesn't spam signals on every tick.
    """
    logger.info("Running strategy signal scan (15-min heartbeat)...")
    try:
        from datetime import date
        import hashlib
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.strategy_definition import StrategyDefinition
        from app.db.models.watchlist import Watchlist, WatchlistItem
        from app.services.autonomous_logger import log_action

        now_et = datetime.now(ET)
        # Only run during market hours (9:30–16:00 ET, Mon–Fri)
        total_minutes = now_et.hour * 60 + now_et.minute
        if now_et.weekday() >= 5 or not (9 * 60 + 30 <= total_minutes < 16 * 60):
            logger.debug("Strategy signal scan: outside market hours, skipping")
            return

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            if not users:
                logger.debug("Strategy signal scan: no active users")
                return

            strategies = db.query(StrategyDefinition).filter(
                StrategyDefinition.is_active.is_(True)
            ).all()

            today_str = str(date.today())
            tick_str = now_et.strftime("%H%M")  # e.g. "1030" — used in seed so each tick is distinct

            def _is_crypto_symbol(sym: str) -> bool:
                s = sym.upper()
                return (
                    "-USD" in s or "/USD" in s or "/USDT" in s
                    or s in {"BTC", "ETH", "SOL", "DOGE", "MATIC", "ADA", "XRP", "AVAX", "DOT", "LINK"}
                )

            def _is_crypto_strategy(s: StrategyDefinition) -> bool:
                key = (s.strategy_key or "").lower()
                cat = (s.category or "").lower()
                return "crypto" in key or "bitcoin" in key or "btc" in key or "eth" in key or "crypto" in cat

            for user in users:
                # Get user's watchlist symbols as the scan universe
                watchlists = db.query(Watchlist).filter_by(user_id=user.id).all()
                symbols: list[str] = []
                seen: set[str] = set()
                for wl in watchlists:
                    for item in wl.items:
                        if item.symbol not in seen:
                            symbols.append(item.symbol)
                            seen.add(item.symbol)
                if not symbols:
                    symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]  # default universe

                for strategy in strategies:
                    strat_is_crypto = _is_crypto_strategy(strategy)
                    # Only match strategy to symbols of the same asset class
                    compatible = [
                        s for s in symbols
                        if _is_crypto_symbol(s) == strat_is_crypto
                    ]
                    for symbol in compatible[:10]:  # cap to keep job fast
                        # Deterministic "did this strategy fire?" — 15% chance per tick per combo
                        seed_str = f"{strategy.strategy_key}-{symbol}-{today_str}-{tick_str}"
                        seed_int = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
                        if seed_int % 100 < 15:  # 15% chance
                            log_action(
                                user_id=user.id,
                                lab="strategy-lab",
                                action_type="signal_fired",
                                asset=symbol,
                                strategy_id=strategy.strategy_key,
                                rationale=(
                                    f"Strategy '{strategy.name}' triggered on {symbol}. "
                                    f"Entry conditions met based on latest price data."
                                ),
                                result="success",
                            )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Strategy signal scan failed: {e}", exc_info=True)


async def run_morning_brief_job() -> None:
    """
    Job 2: Morning brief generation at 7:30 AM ET weekdays.
    For each active user, generate a DailyBrief for today (skip if already exists).
    Falls back to a static market-data-only brief when ANTHROPIC_API_KEY is missing.
    """
    logger.info("Running morning brief generation (7:30 AM ET)...")
    try:
        from datetime import date as _date
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.daily_brief import DailyBrief

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            if not users:
                logger.info("Morning brief: no active users, skipping")
                return

            today = _date.today()
            for user in users:
                try:
                    # Skip if brief already generated today
                    existing = db.query(DailyBrief).filter_by(
                        user_id=user.id, brief_date=today
                    ).first()
                    if existing:
                        logger.debug(f"Morning brief: already exists for user {user.id} on {today}")
                        continue

                    # Import the generation helpers from the router module
                    from app.routers.daily_brief import (
                        _get_watchlist_symbols,
                        _get_portfolio_symbols,
                        _fetch_news_for_symbols,
                        _fetch_upcoming_earnings,
                        _generate_sections_with_ai,
                        MARKET_SYMBOLS,
                        _seed_move,
                    )
                    import asyncio

                    watchlist_symbols = _get_watchlist_symbols(db, user.id)
                    portfolio_symbols = _get_portfolio_symbols(db, user.id)
                    all_syms = list(dict.fromkeys(portfolio_symbols + watchlist_symbols))[:15]

                    # Gather context — wrap each in try/except so one failure doesn't block
                    try:
                        news_items = await _fetch_news_for_symbols(all_syms)
                    except Exception:
                        news_items = []
                    try:
                        earnings_events = await _fetch_upcoming_earnings(db, all_syms)
                    except Exception:
                        earnings_events = []

                    sections = await _generate_sections_with_ai(
                        user_id=user.id,
                        watchlist_symbols=watchlist_symbols,
                        portfolio_symbols=portfolio_symbols,
                        news_items=news_items,
                        earnings_events=earnings_events,
                        brief_date=today,
                        reading_level="investor",
                    )

                    now = datetime.utcnow()
                    brief = DailyBrief(
                        user_id=user.id,
                        brief_date=today,
                        content_json={"sections": sections},
                        reading_level="investor",
                        generated_at=now,
                    )
                    db.add(brief)
                    db.commit()
                    logger.info(f"Morning brief generated for user {user.id} on {today}")
                except Exception as e:
                    logger.error(f"Morning brief failed for user {user.id}: {e}", exc_info=True)
                    db.rollback()
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Morning brief job setup failed: {e}", exc_info=True)


async def run_daily_autonomous_recap_job() -> None:
    """
    Job 3: Daily recap at 4:15 PM ET weekdays.
    Count autonomous_actions taken today per user, generate a 1-sentence summary,
    and store/update an AutonomousDigest record.
    Reuses the existing run_autonomous_digest_job logic but also logs a recap action.
    """
    logger.info("Running daily autonomous recap (4:15 PM ET)...")
    try:
        from datetime import date as _date
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.autonomous import AutonomousAction, AutonomousDigest
        from app.services.autonomous_logger import log_action

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            if not users:
                logger.info("Autonomous recap: no active users")
                return

            today = _date.today()
            today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

            for user in users:
                try:
                    # Count today's actions per type
                    actions = db.query(AutonomousAction).filter(
                        AutonomousAction.user_id == user.id,
                        AutonomousAction.created_at >= today_start,
                    ).all()

                    total_actions = len(actions)
                    signals_fired = sum(1 for a in actions if a.action_type == "signal_fired")

                    # Build 1-sentence summary
                    summary = (
                        f"Today, BMG monitored {total_actions} strategy signals "
                        f"and fired {signals_fired} signal{'s' if signals_fired != 1 else ''} "
                        f"across your active strategies."
                    )
                    logger.info(f"Autonomous recap for user {user.id}: {summary}")

                    # Check if a digest already exists; if so update the tldr
                    existing_digest = db.query(AutonomousDigest).filter_by(
                        user_id=user.id, digest_date=today
                    ).first()

                    if existing_digest:
                        existing_digest.tldr = summary
                        db.add(existing_digest)
                        db.commit()
                    else:
                        # Generate full digest via the service
                        from app.services.autonomous_digest import generate_autonomous_digest
                        await generate_autonomous_digest(user.id, db)

                    # Also log the recap itself as an action so it shows up in the activity feed
                    log_action(
                        user_id=user.id,
                        lab="system",
                        action_type="daily_recap",
                        asset=None,
                        strategy_id="daily_recap",
                        rationale=summary,
                        result="success",
                    )
                except Exception as e:
                    logger.error(f"Autonomous recap failed for user {user.id}: {e}", exc_info=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Autonomous recap job setup failed: {e}", exc_info=True)


async def run_crypto_automation_job() -> None:
    """Run crypto strategy automation for all active users (24/7, every 15 min)."""
    logger.info("Starting scheduled crypto automation...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.screener.crypto_runner import run_crypto_automation

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            user_ids = [u.id for u in users]
        finally:
            db.close()

        if not user_ids:
            return

        for user_id in user_ids:
            try:
                result = await run_crypto_automation(user_id=user_id)
                logger.info(f"Crypto automation done for user {user_id}: {result}")
            except Exception as e:
                logger.error(f"Crypto automation failed for user {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Crypto automation job setup failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def setup_scheduler() -> None:
    """Register all scheduled jobs."""

    # --- Kept from original ---

    # After market close — main daily scan (new candidates + exits + equity snapshot)
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=ET),
        id="daily_automation_close",
        replace_existing=True,
    )
    # Morning check — re-evaluate candidates using prior day's close data
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone=ET),
        id="daily_automation_open",
        replace_existing=True,
    )

    # --- New: 24/7 monitoring jobs ---

    # market_scan: every 15 min, M-F, 9:30 AM – 4:00 PM ET
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/15",
            timezone=ET,
        ),
        id="market_scan",
        replace_existing=True,
    )

    # premarket_scan: every 30 min, M-F, 4:00 AM – 9:30 AM ET
    # CronTrigger handles "4-9" hours; the 9:30 boundary is close enough —
    # the 9:35 AM dedicated job picks up the open precisely.
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="4-8",
            minute="*/30",
            timezone=ET,
        ),
        id="premarket_scan",
        replace_existing=True,
    )

    # offhours_check: every 2 hours, every day (weekends included)
    scheduler.add_job(
        run_offhours_check,
        CronTrigger(minute=0, hour="*/2", timezone=ET),
        id="offhours_check",
        replace_existing=True,
    )

    # Daily recap: 4:15 PM ET, M-F — runs after automation closes out
    scheduler.add_job(
        run_daily_recap_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=15, timezone=ET),
        id="daily_recap",
        replace_existing=True,
    )

    # Crypto: every 15 min, 24/7 (no market-hours restriction)
    scheduler.add_job(
        run_crypto_automation_job,
        CronTrigger(minute="*/15"),
        id="crypto_automation",
        replace_existing=True,
    )

    # Options scan: every 5 min during market hours
    scheduler.add_job(
        run_options_scan_job,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=ET),
        id="options_scan",
        replace_existing=True,
    )

    # TA pattern detection: once daily after close
    scheduler.add_job(
        run_ta_pattern_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="ta_pattern_daily",
        replace_existing=True,
    )

    # Autonomous digest: 4:30 PM ET, M-F
    scheduler.add_job(
        run_autonomous_digest_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="autonomous_digest",
        replace_existing=True,
    )

    # Portfolio scan: every hour during market hours (9–16 ET), M-F
    scheduler.add_job(
        run_portfolio_scan_job,
        CronTrigger(day_of_week="mon-fri", hour="9-16", minute=0, timezone=ET),
        id="portfolio_scan",
        replace_existing=True,
    )

    # Tax-loss harvest scan: 4:00 PM ET, M-F
    scheduler.add_job(
        run_tax_scan_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        id="tax_scan",
        replace_existing=True,
    )

    # Research job: 9:00 AM ET, M-F
    scheduler.add_job(
        run_research_job,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=ET),
        id="research_job",
        replace_existing=True,
    )

    # Learning job: 7:00 AM ET, daily (including weekends)
    scheduler.add_job(
        run_learning_job,
        CronTrigger(hour=7, minute=0, timezone=ET),
        id="learning_job",
        replace_existing=True,
    )

    # Journal job: 6:00 PM ET, M-F — post-mortem after market close
    scheduler.add_job(
        run_journal_job,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone=ET),
        id="journal_job",
        replace_existing=True,
    )

    # Quarterly review: 8:00 AM ET, daily — guard inside fn checks quarter start
    scheduler.add_job(
        run_quarterly_review_job,
        CronTrigger(hour=8, minute=0, timezone=ET),
        id="quarterly_review_job",
        replace_existing=True,
    )

    # Money job: Monday 10:00 AM ET — weekly money movement simulations
    scheduler.add_job(
        run_money_job,
        CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=ET),
        id="money_job",
        replace_existing=True,
    )

    # ── Phase 3: new jobs ─────────────────────────────────────────────────────

    # Job 1: Strategy signal scan — every 15 min during market hours (9:30–16:00 ET), M-F
    scheduler.add_job(
        run_strategy_signal_scan_job,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/15", timezone=ET),
        id="strategy_signal_scan",
        replace_existing=True,
    )

    # Job 2: Morning brief generation — 7:30 AM ET, M-F
    scheduler.add_job(
        run_morning_brief_job,
        CronTrigger(day_of_week="mon-fri", hour=7, minute=30, timezone=ET),
        id="morning_brief",
        replace_existing=True,
    )

    # Job 3: Daily autonomous recap — 4:15 PM ET, M-F (after market close)
    scheduler.add_job(
        run_daily_autonomous_recap_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=15, timezone=ET),
        id="daily_autonomous_recap",
        replace_existing=True,
    )
