"""
Backfill 30 days of realistic paper-trade history for all active bot allocations.

Run via:  railway run python backend/scripts/backfill_bot_data.py

What it does:
  1. Sets starting_capital_cents on every allocation that's missing it
  2. Inserts 30 days of BotDailyPnL rows with portfolio_value_eod_cents
  3. Inserts a few current open BotPositions per bot
  4. Inserts BotSignal rows for each day
  Skips any allocation that already has >= 25 daily PnL rows.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

# Make sure backend/ is on the path when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DATABASE_URL", "sqlite:////data/bmg_capital.db")

# ── Production guard ──────────────────────────────────────────────────────────
# Railway sets RAILWAY_ENVIRONMENT=production automatically.
# To run this script in production deliberately, set FORCE_SEED=1.
_env = os.environ.get("RAILWAY_ENVIRONMENT", "").lower()
_force = os.environ.get("FORCE_SEED", "").lower() in ("1", "true", "yes")
if _env == "production" and not _force:
    raise SystemExit(
        "ERROR: backfill_bot_data.py refused to run in production.\n"
        "This script inserts FAKE seed data and must never run against real user data.\n"
        "If you truly need to re-seed in production, set FORCE_SEED=1 explicitly.\n"
        "Example: FORCE_SEED=1 railway run python backend/scripts/backfill_bot_data.py"
    )

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Seeded RNG ────────────────────────────────────────────────────────────────

def _rng(seed_str: str) -> random.Random:
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed)


# ── Per-bot config ────────────────────────────────────────────────────────────

_UNIVERSES: dict[str, list[str]] = {
    "stock_swing":         ["NVDA", "META", "MSFT", "AAPL", "AMZN", "GOOGL", "TSM", "AMD"],
    "stock_day":           ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "MSFT"],
    "stock_lt":            ["SPY", "QQQ", "VTI", "MSFT", "AAPL", "V", "JPM", "BRK.B"],
    "crypto_swing":        ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD"],
    "crypto_day":          ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"],
    "crypto_lt":           ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "AVAX/USD"],
    "options_income":      ["AAPL", "MSFT", "SPY", "NVDA", "QQQ", "META"],
    "options_directional": ["SPY", "QQQ", "NVDA", "TSLA", "META", "AAPL"],
}

_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "NVDA": (800, 1200), "META": (450, 650), "MSFT": (380, 480),
    "AAPL": (170, 220),  "AMZN": (170, 220), "GOOGL": (150, 200),
    "TSM":  (120, 180),  "AMD":  (140, 200),  "SPY":  (520, 580),
    "QQQ":  (440, 500),  "TSLA": (200, 350),  "VTI":  (245, 275),
    "V":    (270, 310),  "JPM": (195, 240),   "BRK.B": (390, 430),
    "BTC/USD": (60000, 100000), "ETH/USD": (3000, 5000),
    "SOL/USD": (150, 250), "AVAX/USD": (30, 60), "LINK/USD": (12, 20),
    "BNB/USD": (550, 750), "DOT/USD": (6, 12),
}

# daily_pnl_range: (mean_pct, std_pct) — slight positive bias
_PNL_PARAMS: dict[str, tuple[float, float]] = {
    "stock_swing":         (0.22, 0.90),
    "stock_day":           (0.12, 0.60),
    "stock_lt":            (0.18, 0.45),
    "crypto_swing":        (0.30, 1.50),
    "crypto_day":          (0.18, 1.20),
    "crypto_lt":           (0.25, 0.80),
    "options_income":      (0.15, 0.55),
    "options_directional": (0.28, 1.80),
}

_STRATEGIES: dict[str, list[str]] = {
    "stock_swing":         ["momentum_breakout", "stage_2_breakout", "rsi_reversion"],
    "stock_day":           ["vwap_reversion", "gap_fill", "opening_range_breakout"],
    "stock_lt":            ["dca_weekly", "moving_avg_crossover", "factor_blend"],
    "crypto_swing":        ["crypto_momentum", "exchange_flow", "on_chain_signal"],
    "crypto_day":          ["funding_rate_arb", "order_book_imbalance", "vol_breakout"],
    "crypto_lt":           ["dca_weekly", "btc_dominance_shift", "factor_blend"],
    "options_income":      ["covered_call", "cash_secured_put", "iron_condor"],
    "options_directional": ["debit_spread", "long_call_momentum", "vol_event_play"],
}

_REASONS: dict[str, list[str]] = {
    "stock_swing": [
        "Stage 2 breakout on daily chart; volume +40% above 20d avg",
        "RSI(14) crossed 30 → 50 with positive MACD divergence",
        "Earnings beat + guidance raise; gap up through resistance",
        "Sector rotation signal; relative strength rank #1 in group",
    ],
    "stock_day": [
        "VWAP reclaim with high relative volume; first 30-min candle break",
        "Gap-fill setup; pre-market news catalyst, clean level to trade",
        "Opening range breakout at $192.40; clean continuation pattern",
        "High short interest + catalyst; squeeze potential identified",
    ],
    "stock_lt": [
        "Weekly DCA trigger; price < 50-week SMA by 8%",
        "Factor blend score 91/100: value + momentum + quality",
        "Moving average crossover (50d > 200d); trend confirmation",
        "Dividend reinvestment trigger on ex-dividend date",
    ],
    "crypto_swing": [
        "BTC dominance declining; alt season signal on-chain",
        "Exchange inflows surging; potential sell-off hedge",
        "Funding rate negative → positive flip; long bias confirmed",
        "Whale accumulation detected; large wallet addresses adding",
    ],
    "crypto_day": [
        "Order book imbalance 3:1 bid-to-ask at key level $68,200",
        "Funding rate spike; short squeeze catalyst building",
        "Volatility breakout from 4h Bollinger Band squeeze",
        "ETF flow data showing institutional accumulation",
    ],
    "crypto_lt": [
        "Weekly DCA trigger; BTC/USD below 200-week SMA",
        "NVT ratio below historical mean; undervalued signal",
        "Staking yield + price appreciation thesis intact",
        "Cycle analysis: mid-cycle accumulation zone",
    ],
    "options_income": [
        "IV rank 75th percentile; selling premium in high-vol environment",
        "Covered call with 0.30 delta; 45-day expiry, 2.1% monthly yield",
        "Iron condor on SPY; earnings-free window, collect theta",
        "Cash-secured put below key support; defined risk entry",
    ],
    "options_directional": [
        "Debit spread ahead of earnings; 4:1 risk-reward on breakout target",
        "Long calls with rising IV before FOMC; catalyst play",
        "Vertical spread on trend continuation; tight stop defined",
        "Vol event play on CPI print; straddle with skew adjustment",
    ],
}


def _entry_price(symbol: str, rng: random.Random) -> float:
    lo, hi = _PRICE_RANGES.get(symbol, (50.0, 300.0))
    return round(rng.uniform(lo, hi), 2)


def main() -> None:
    from app.db.session import SessionLocal
    from app.db.models.bots import (
        BotProfile, BotAllocation, BotPosition, BotTrade,
        BotDailyPnL, BotSignal,
    )
    from app.db.models.users import User

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        if not users:
            log.warning("No active users found — nothing to backfill")
            return

        today = date.today()
        now = datetime.now(timezone.utc)

        for user in users:
            log.info(f"Backfilling for user {user.id} ({user.email})")

            allocations = (
                db.query(BotAllocation)
                .filter(BotAllocation.user_id == user.id)
                .all()
            )
            if not allocations:
                log.info(f"  No allocations — skipping user {user.id}")
                continue

            for alloc in allocations:
                profile = db.get(BotProfile, alloc.profile_id)
                if not profile:
                    continue

                bot_name = profile.name

                # ── Check if already seeded ───────────────────────────────────
                existing_count = (
                    db.query(BotDailyPnL)
                    .filter(BotDailyPnL.allocation_id == alloc.id)
                    .count()
                )
                if existing_count >= 25:
                    log.info(f"  {bot_name}: already has {existing_count} PnL rows — skipping")
                    continue

                # ── Set starting capital if missing ───────────────────────────
                capital_cents = int(alloc.capital_cents_within_portfolio or 0)
                if capital_cents == 0:
                    capital_cents = {
                        "stock_swing": 1_666_700, "stock_day": 1_666_700,
                        "stock_lt": 1_666_600, "crypto_swing": 1_666_700,
                        "crypto_day": 1_666_700, "crypto_lt": 1_666_600,
                        "options_income": 2_500_000, "options_directional": 2_500_000,
                    }.get(bot_name, 1_500_000)

                if not alloc.starting_capital_cents:
                    alloc.starting_capital_cents = capital_cents

                mean_pct, std_pct = _PNL_PARAMS.get(bot_name, (0.15, 0.80))
                universe = _UNIVERSES.get(bot_name, ["AAPL", "MSFT", "NVDA"])
                strategies = _STRATEGIES.get(bot_name, ["momentum"])
                reasons = _REASONS.get(bot_name, ["Signal triggered"])

                # ── Backfill 30 days of PnL rows ──────────────────────────────
                portfolio_value = capital_cents
                log.info(f"  Backfilling {bot_name} from ${capital_cents/100:,.0f} starting capital")

                for days_back in range(30, 0, -1):
                    d = today - timedelta(days=days_back)
                    # Skip weekends for stock/options
                    if bot_name not in ("crypto_swing", "crypto_day", "crypto_lt"):
                        if d.weekday() >= 5:
                            continue

                    # Skip if row already exists
                    if (
                        db.query(BotDailyPnL)
                        .filter(BotDailyPnL.allocation_id == alloc.id, BotDailyPnL.date == d)
                        .first()
                    ):
                        continue

                    day_rng = _rng(f"{bot_name}-{user.id}-{d}")
                    daily_pct = day_rng.gauss(mean_pct, std_pct)

                    realized_cents = int(portfolio_value * daily_pct / 100)
                    unrealized_cents = int(portfolio_value * day_rng.gauss(0.05, 0.40) / 100)
                    fees_cents = abs(int(realized_cents * 0.001))

                    portfolio_value = portfolio_value + realized_cents - fees_cents
                    portfolio_value = max(portfolio_value, int(capital_cents * 0.75))

                    db.add(BotDailyPnL(
                        allocation_id=alloc.id,
                        date=d,
                        realized_cents=realized_cents,
                        unrealized_cents=unrealized_cents,
                        fees_cents=fees_cents,
                        portfolio_value_eod_cents=portfolio_value,
                    ))

                # ── Today's PnL row ───────────────────────────────────────────
                today_rng = _rng(f"{bot_name}-{user.id}-{today}")
                today_realized = int(portfolio_value * today_rng.gauss(mean_pct, std_pct) / 100)
                today_unrealized = int(portfolio_value * today_rng.gauss(0.05, 0.40) / 100)
                portfolio_value += today_realized
                portfolio_value = max(portfolio_value, int(capital_cents * 0.75))

                if not (
                    db.query(BotDailyPnL)
                    .filter(BotDailyPnL.allocation_id == alloc.id, BotDailyPnL.date == today)
                    .first()
                ):
                    db.add(BotDailyPnL(
                        allocation_id=alloc.id,
                        date=today,
                        realized_cents=today_realized,
                        unrealized_cents=today_unrealized,
                        fees_cents=abs(int(today_realized * 0.001)),
                        portfolio_value_eod_cents=portfolio_value,
                    ))

                # ── Open positions (2-3 current) ──────────────────────────────
                open_count = (
                    db.query(BotPosition)
                    .filter(BotPosition.allocation_id == alloc.id, BotPosition.closed_at.is_(None))
                    .count()
                )
                if open_count == 0:
                    pos_rng = _rng(f"{bot_name}-{user.id}-positions")
                    n_pos = pos_rng.randint(2, 3)
                    sym_pool = list(universe)
                    pos_rng.shuffle(sym_pool)

                    for sym in sym_pool[:n_pos]:
                        entry = _entry_price(sym, pos_rng)
                        notional = capital_cents / 100 * pos_rng.uniform(0.05, 0.12)
                        qty = round(notional / entry, 4)
                        if qty <= 0:
                            continue
                        opened_at = now - timedelta(days=pos_rng.randint(1, 8))
                        pos = BotPosition(
                            allocation_id=alloc.id,
                            symbol=sym,
                            qty=qty,
                            avg_cost_cents=int(entry * 100),
                            opened_at=opened_at,
                            closed_at=None,
                            is_paper=True,
                        )
                        db.add(pos)
                        db.flush()
                        db.add(BotTrade(
                            allocation_id=alloc.id,
                            symbol=sym,
                            side="buy",
                            qty=qty,
                            fill_price_cents=int(entry * 100),
                            fees_cents=0,
                            ts=opened_at,
                            position_id=pos.id,
                            is_paper=True,
                            expected_fill_cents=int(entry * 100),
                            slippage_bps=pos_rng.uniform(0, 2),
                        ))

                # ── Signals (2-3 per week for 30 days) ───────────────────────
                sig_count = (
                    db.query(BotSignal)
                    .filter(BotSignal.allocation_id == alloc.id)
                    .count()
                )
                if sig_count < 10:
                    sig_rng = _rng(f"{bot_name}-{user.id}-signals")
                    for days_back in range(30, 0, -2):
                        if sig_rng.random() < 0.55:
                            continue
                        sig_ts = now - timedelta(days=days_back, hours=sig_rng.randint(9, 15))
                        sym = sig_rng.choice(universe)
                        side = "buy" if sig_rng.random() < 0.65 else "sell"
                        db.add(BotSignal(
                            allocation_id=alloc.id,
                            ts=sig_ts,
                            symbol=sym,
                            side=side,
                            confidence=round(sig_rng.uniform(0.55, 0.92), 2),
                            size_hint=round(sig_rng.uniform(0.05, 0.15), 3),
                            reason=sig_rng.choice(reasons),
                            strategy=sig_rng.choice(strategies),
                        ))

                # ── Ensure allocation is enabled ──────────────────────────────
                if not alloc.enabled:
                    alloc.enabled = True
                    alloc.paused_reason = None
                    alloc.updated_at = now

                log.info(
                    f"  {bot_name}: seeded 30d history, "
                    f"final value ${portfolio_value/100:,.0f} "
                    f"({(portfolio_value - capital_cents)/capital_cents*100:+.1f}%)"
                )

            db.commit()
            log.info(f"User {user.id} done")

        log.info("Backfill complete.")
    except Exception:
        log.exception("Backfill failed")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
