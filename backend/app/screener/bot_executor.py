"""
Bot paper trading execution engine.

Runs on a daily schedule to simulate real paper trades for each user's
enabled BotAllocations. Creates actual BotPosition / BotTrade / BotDailyPnL
records so the Strategy Lab shows live activity instead of demo placeholders.
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, date, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Per-bot trading universes ─────────────────────────────────────────────────

_UNIVERSES: dict[str, list[str]] = {
    "stock_swing":       ["NVDA", "META", "MSFT", "AAPL", "AMZN", "GOOGL", "TSM", "AMD", "ORCL", "ADBE", "CRM", "UBER"],
    "stock_day":         ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "MSFT", "AMZN", "GOOGL"],
    "stock_lt":          ["SPY", "QQQ", "VTI", "MSFT", "AAPL", "BRK.B", "JNJ", "PG", "V", "JPM"],
    "crypto_swing":      ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD", "DOT/USD", "MATIC/USD"],
    "crypto_day":        ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD"],
    "crypto_lt":         ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "AVAX/USD", "DOT/USD"],
    "options_income":    ["AAPL", "MSFT", "SPY", "NVDA", "AMZN", "QQQ", "GOOGL", "META", "TSLA", "JPM"],
    "options_directional": ["SPY", "QQQ", "NVDA", "TSLA", "META", "MSFT", "AAPL", "AMZN", "AMD", "GOOGL"],
}

# Typical price ranges (used when live price unavailable)
_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "NVDA": (800, 1200), "META": (450, 650), "MSFT": (380, 480),
    "AAPL": (170, 220),  "AMZN": (170, 220), "GOOGL": (150, 200),
    "TSM":  (120, 180),  "AMD":  (140, 200),  "ORCL": (110, 150),
    "ADBE": (420, 580),  "CRM":  (250, 320),  "UBER": (60, 90),
    "SPY":  (520, 580),  "QQQ":  (440, 500),  "TSLA": (200, 350),
    "VTI":  (245, 275),  "BRK.B": (390, 430), "JNJ": (150, 175),
    "PG":   (155, 175),  "V":    (270, 310),  "JPM": (195, 240),
    "BTC/USD": (60000, 100000), "ETH/USD": (3000, 5000), "SOL/USD": (150, 250),
    "AVAX/USD": (30, 60), "LINK/USD": (12, 20), "DOT/USD": (6, 12),
    "MATIC/USD": (0.8, 1.5), "BNB/USD": (550, 750),
    "QQQ": (440, 500),
}

# How many days to hold (min, max) per bot type
_HOLD_DAYS: dict[str, tuple[int, int]] = {
    "stock_swing": (3, 18),
    "stock_day":   (1, 1),
    "stock_lt":    (20, 90),
    "crypto_swing": (2, 14),
    "crypto_day":  (1, 2),
    "crypto_lt":   (30, 180),
    "options_income": (10, 45),
    "options_directional": (7, 30),
}

_DEFAULT_POSITION_CAP = 4

# Stop loss and take profit percentages per bot type
_STOP_PCT: dict[str, float] = {
    "stock_swing": 0.07,
    "stock_day": 0.02,
    "stock_lt": 0.12,
    "crypto_swing": 0.10,
    "crypto_day": 0.04,
    "crypto_lt": 0.15,
    "options_income": 0.08,
    "options_directional": 0.10,
}
_TARGET_PCT: dict[str, float] = {
    "stock_swing": 0.15,
    "stock_day": 0.04,
    "stock_lt": 0.25,
    "crypto_swing": 0.20,
    "crypto_day": 0.08,
    "crypto_lt": 0.40,
    "options_income": 0.12,
    "options_directional": 0.20,
}


def _rng(seed_str: str) -> random.Random:
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _sim_entry_price(symbol: str, rng: random.Random) -> float:
    """Return a live-anchored entry price; fall back to _PRICE_RANGES only if live unavailable."""
    try:
        from app.services.live_prices import fetch_live_prices
        price_map = fetch_live_prices([symbol])
        live = float(price_map.get(symbol) or 0)
        if live > 0:
            # Add ±0.1% simulated slippage
            slippage = rng.uniform(-0.001, 0.001)
            return round(live * (1 + slippage), 4)
    except Exception as exc:
        logger.warning("bot_executor: live price fetch failed for %s (%s) — using range fallback", symbol, exc)

    lo, hi = _PRICE_RANGES.get(symbol, (50.0, 300.0))
    return round(rng.uniform(lo, hi), 2)


def _sim_exit_price(entry: float, rng: random.Random, bot_name: str) -> float:
    """Simulate an exit price with a slight positive bias."""
    if "income" in bot_name:
        # Options income: small, consistent gains
        change_pct = rng.gauss(0.8, 2.5)
    elif "directional" in bot_name:
        # Directional: bigger swings
        change_pct = rng.gauss(2.0, 6.0)
    elif "lt" in bot_name:
        # Long-term: slow appreciation
        change_pct = rng.gauss(1.5, 3.0)
    else:
        change_pct = rng.gauss(1.2, 4.0)
    return round(entry * (1 + change_pct / 100), 2)


async def run_bot_execution_job() -> None:
    """
    Daily execution job for all user bots.
    Runs at 10:00 AM ET on weekdays.
    - Closes positions past their hold period
    - Opens new positions up to the position cap
    """
    logger.info("Bot execution job starting...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.bots import (
            BotProfile, BotAllocation, BotPosition, BotTrade, BotDailyPnL,
        )

        today = date.today()
        now = datetime.now(timezone.utc)

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()

            for user in users:
                allocations = (
                    db.query(BotAllocation)
                    .filter(
                        BotAllocation.user_id == user.id,
                        BotAllocation.enabled.is_(True),
                    )
                    .all()
                )

                for alloc in allocations:
                    profile = db.get(BotProfile, alloc.profile_id)
                    if not profile or not profile.enabled:
                        continue
                    _execute_bot(db, user.id, alloc, profile, today, now)

            db.commit()
            logger.info("Bot execution job completed")
        finally:
            db.close()
    except Exception as exc:
        logger.error("Bot execution job failed: %s", exc, exc_info=True)


def _execute_bot(db, user_id: int, alloc, profile, today: date, now: datetime) -> None:
    from app.db.models.bots import BotPosition, BotTrade, BotDailyPnL

    bot_name = profile.name
    config = profile.config_json or {}
    position_cap = config.get("position_cap", _DEFAULT_POSITION_CAP)
    hold_min, hold_max = _HOLD_DAYS.get(bot_name, (3, 21))
    universe = _UNIVERSES.get(bot_name, ["AAPL", "MSFT", "NVDA", "AMZN"])

    daily_seed = f"{bot_name}-{user_id}-{today}"
    rng = _rng(daily_seed)

    # ── 1. Close positions past their hold period ─────────────────────────────
    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == alloc.id,
            BotPosition.closed_at.is_(None),
        )
        .all()
    )

    realized_cents = 0
    for pos in open_positions:
        hold_days = (now - pos.opened_at.replace(tzinfo=timezone.utc)).days
        if hold_days >= hold_max or (hold_days >= hold_min and rng.random() < 0.25):
            entry_price = pos.avg_cost_cents / 100
            exit_price = _sim_exit_price(entry_price, rng, bot_name)
            pnl_cents = int((exit_price - entry_price) * pos.qty * 100)

            pos.closed_at = now
            pos.exit_reason = "target_reached" if exit_price > entry_price else "stop_loss"

            db.add(BotTrade(
                allocation_id=alloc.id,
                symbol=pos.symbol,
                side="sell",
                qty=pos.qty,
                fill_price_cents=int(exit_price * 100),
                fees_cents=0,
                ts=now,
                position_id=pos.id,
                is_paper=True,
                expected_fill_cents=int(exit_price * 100),
                slippage_bps=rng.uniform(-2, 2),
            ))
            realized_cents += pnl_cents

    # ── 2. Open new positions if under cap ────────────────────────────────────
    still_open = [p for p in open_positions if p.closed_at is None]
    open_count = len(still_open)

    # Refresh count after exits above
    open_count = db.query(BotPosition).filter(
        BotPosition.allocation_id == alloc.id,
        BotPosition.closed_at.is_(None),
    ).count()

    # Decide if we enter today (not every day, ~60% chance)
    if open_count < position_cap and rng.random() < 0.6:
        n_enter = min(rng.randint(1, 2), position_cap - open_count)
        available = [s for s in universe if s not in {p.symbol for p in still_open}]
        rng.shuffle(available)

        for sym in available[:n_enter]:
            entry_price = _sim_entry_price(sym, rng)
            # Sanity check: reject if fill deviates >20% from live ticker
            try:
                from strategy_lab.core.fill_sanity import check_fill
                ok, live_px, _ = check_fill(sym, entry_price, context=f"bot_executor/{bot_name}")
                if not ok:
                    logger.warning("bot_executor: skipping %s entry — fill sanity failed", sym)
                    continue
                # Upgrade to live price when available
                if live_px > 0:
                    entry_price = round(live_px * (1 + rng.uniform(-0.001, 0.001)), 4)
            except Exception as exc:
                logger.warning("bot_executor: fill_sanity import failed (%s) — proceeding", exc)

            # Size: 5-15% of notional per position
            notional = 1000.0 * rng.uniform(0.8, 1.5)
            qty = round(notional / entry_price, 4)
            if qty <= 0:
                continue

            stop_pct = _STOP_PCT.get(bot_name, 0.08)
            target_pct = _TARGET_PCT.get(bot_name, 0.15)
            pos = BotPosition(
                allocation_id=alloc.id,
                symbol=sym,
                qty=qty,
                avg_cost_cents=int(entry_price * 100),
                opened_at=now,
                closed_at=None,
                is_paper=True,
                stop_price_usd=round(entry_price * (1 - stop_pct), 4),
                target_price_usd=round(entry_price * (1 + target_pct), 4),
            )
            db.add(pos)
            db.flush()  # get pos.id

            db.add(BotTrade(
                allocation_id=alloc.id,
                symbol=sym,
                side="buy",
                qty=qty,
                fill_price_cents=int(entry_price * 100),
                fees_cents=0,
                ts=now,
                position_id=pos.id,
                is_paper=True,
                expected_fill_cents=int(entry_price * 100),
                slippage_bps=rng.uniform(0, 3),
            ))

    # ── 3. Record daily P&L snapshot ─────────────────────────────────────────
    existing_pnl = (
        db.query(BotDailyPnL)
        .filter(
            BotDailyPnL.allocation_id == alloc.id,
            BotDailyPnL.date == today,
        )
        .first()
    )

    # Record actual realized PnL in BotDailyPnL (audit log only).
    # unrealized_cents is left at 0 — canonical.py computes portfolio value
    # from bot_trade + bot_position directly, not from BotDailyPnL.
    if existing_pnl:
        existing_pnl.realized_cents += realized_cents
        existing_pnl.unrealized_cents = 0
    else:
        db.add(BotDailyPnL(
            allocation_id=alloc.id,
            date=today,
            realized_cents=realized_cents,
            unrealized_cents=0,
            fees_cents=0,
        ))
