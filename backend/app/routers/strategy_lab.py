"""
Strategy Lab — portfolio overview endpoint.

GET /api/strategy-lab/portfolio  — aggregated portfolio metrics across all enabled
                                    bot allocations for the current user.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user

from app.db.models.bots import (
    BotAllocation,
    BotProfile,
    BotWatchlist,
)
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategy-lab", tags=["strategy-lab"])

PROFILE_NAMES: Dict[str, str] = {
    "stock_swing": "Stock Swing",
    "stock_day": "Stock Day",
    "stock_lt": "Stock Long-Term",
    "crypto_swing": "Crypto Swing",
    "crypto_day": "Crypto Day",
    "crypto_lt": "Crypto Long-Term",
}


# ── Demo seed config ──────────────────────────────────────────────────────────

_DEMO_BOTS = [
    {"name": "stock_swing",            "starting_cents": 2500000,  "daily_drift": 0.0024, "daily_vol": 0.008},
    {"name": "stock_day",              "starting_cents": 1500000,  "daily_drift": 0.0041, "daily_vol": 0.012},
    {"name": "stock_lt",               "starting_cents": 5000000,  "daily_drift": 0.0010, "daily_vol": 0.004},
    {"name": "crypto_swing",           "starting_cents": 1000000,  "daily_drift": 0.0062, "daily_vol": 0.022},
    {"name": "crypto_day",             "starting_cents": 1000000,  "daily_drift": 0.0031, "daily_vol": 0.016},
    {"name": "crypto_lt",              "starting_cents": 2000000,  "daily_drift": 0.0019, "daily_vol": 0.010},
    {"name": "crypto_onchain",         "starting_cents": 1000000,  "daily_drift": 0.0028, "daily_vol": 0.018},
    {"name": "crypto_quant_aggressive","starting_cents": 1000000,  "daily_drift": 0.0051, "daily_vol": 0.025},
]

_DEMO_WATCHLISTS = {
    "stock_swing":  [("NVDA",88),("META",82),("MSFT",79),("AAPL",76),("AMZN",73),("GOOGL",69),("TSM",65),("AMD",61)],
    "stock_day":    [("SPY",91),("QQQ",87),("TSLA",83),("GME",76),("AMC",71),("PLTR",68),("RIVN",63)],
    "stock_lt":     [("VTI",94),("VOO",92),("QQQ",88),("VEA",81),("BND",77),("VNQ",72),("GLD",68),("IWM",64)],
    "crypto_swing": [("BTC/USD",89),("ETH/USD",85),("SOL/USD",78),("AVAX/USD",72),("LINK/USD",65)],
    "crypto_day":   [("BTC/USD",92),("ETH/USD",88),("SOL/USD",81),("BNB/USD",74),("MATIC/USD",67)],
    "crypto_lt":    [("BTC/USD",95),("ETH/USD",91),("SOL/USD",84),("AVAX/USD",77),("LINK/USD",70),("DOT/USD",63)],
    "crypto_onchain": [("BTC/USD",88),("ETH/USD",84),("SOL/USD",76),("MATIC/USD",69),("LINK/USD",62)],
    "crypto_quant_aggressive": [
        ("BTC/USD",95),("ETH/USD",91),("SOL/USD",85),("BNB/USD",80),("XRP/USD",75),
        ("ADA/USD",70),("AVAX/USD",66),("DOGE/USD",61),("LINK/USD",57),("ARB/USD",52),
    ],
}

def _seed_demo_allocations(db: Session, user_id: int) -> None:
    """Create default allocations and seed watchlist entries for a new user. Idempotent."""

    for cfg in _DEMO_BOTS:
        profile = db.execute(
            select(BotProfile).where(BotProfile.name == cfg["name"])
        ).scalar()
        if not profile:
            continue

        alloc = db.execute(
            select(BotAllocation).where(
                BotAllocation.user_id == user_id,
                BotAllocation.profile_id == profile.id,
            )
        ).scalar()

        if not alloc:
            alloc = BotAllocation(
                user_id=user_id,
                profile_id=profile.id,
                capital_pct=10.0,
                risk_profile="standard",
                paper_mode=True,
                enabled=True,
                starting_capital_cents=cfg["starting_cents"],
                tier="T2",
            )
            db.add(alloc)
            db.flush()

        # Seed watchlist (skip if already has rows)
        wl_count = db.execute(
            select(func.count(BotWatchlist.id)).where(BotWatchlist.profile_id == profile.id)
        ).scalar() or 0
        if wl_count == 0:
            for rank, (sym, score) in enumerate(_DEMO_WATCHLISTS.get(cfg["name"], []), 1):
                db.add(BotWatchlist(
                    profile_id=profile.id,
                    symbol=sym,
                    score=float(score),
                    rank=rank,
                    reasons={"momentum": score * 0.4, "volume": score * 0.35, "rsi": score * 0.25},
                    status="active",
                    last_evaluated_at=datetime.now(timezone.utc),
                ))

    try:
        db.commit()
        logger.info("Demo allocations seeded for user %d", user_id)
    except Exception as exc:
        db.rollback()
        logger.error("Demo seed failed for user %d: %s", user_id, exc)


_CANDIDATE_CATALOG = [
    {
        "file": "cross_sectional_momentum",
        "name": "Cross-Sectional Momentum",
        "asset_class": "equity",
        "style": "momentum",
        "reference": "Jegadeesh & Titman (1993)",
        "expected_sharpe": "0.4–0.8",
        "description": "Ranks universe by 12-1M return (skip-month), buys top quintile, sells bottom quintile.",
        "promotion_criteria": "30 days live + 20 trades + Sharpe > 0.3",
    },
    {
        "file": "time_series_momentum",
        "name": "Time-Series Momentum",
        "asset_class": "multi",
        "style": "momentum",
        "reference": "Moskowitz, Ooi & Pedersen (2012)",
        "expected_sharpe": "0.5–1.0",
        "description": "Each asset evaluated independently — go long if 12M trailing return is positive, short if negative. Sized by inverse realised volatility.",
        "promotion_criteria": "30 days live + 20 trades + Sharpe > 0.3",
    },
    {
        "file": "crypto_dual_momentum",
        "name": "Crypto Dual Momentum",
        "asset_class": "crypto",
        "style": "momentum",
        "reference": "Liu & Tsyvinski (2021) + Antonacci (2014)",
        "expected_sharpe": "0.6–1.2",
        "description": "Combines absolute momentum (vs. cash) with relative momentum (top-N crypto by 3M return). Long-only.",
        "promotion_criteria": "30 days live + 20 trades + Sharpe > 0.3",
    },
    {
        "file": "overnight_gap_fade",
        "name": "Overnight Gap Fade",
        "asset_class": "equity",
        "style": "mean_reversion",
        "reference": "Branch & Ma (2008) + Berkman et al. (2012)",
        "expected_sharpe": "0.3–0.7",
        "description": "Fades overnight gaps > 1.5%. Stocks gapping up tend to pull back intraday; stocks gapping down tend to recover.",
        "promotion_criteria": "30 days live + 20 trades + Sharpe > 0.3",
    },
    {
        "file": "rsi2_mean_reversion",
        "name": "RSI-2 Mean Reversion",
        "asset_class": "equity",
        "style": "mean_reversion",
        "reference": "Connors & Alvarez (2009)",
        "expected_sharpe": "0.4–0.9",
        "description": "Buys stocks where RSI(2) drops below 10 while price is above the 200-day MA. Exits when RSI(2) closes above 70.",
        "promotion_criteria": "30 days live + 20 trades + Sharpe > 0.3",
    },
    {
        "file": "cash_and_carry",
        "name": "Cash-and-Carry Basis",
        "asset_class": "crypto",
        "style": "arbitrage",
        "reference": "Classic futures basis trade",
        "expected_sharpe": "1.0–2.5",
        "description": "Delta-neutral: long spot + short perp. Collects positive funding rate as carry. Exits when funding collapses.",
        "promotion_criteria": "30 days live + 10 trades + Sharpe > 0.5",
    },
    {
        "file": "liquidation_cascade",
        "name": "Liquidation Cascade",
        "asset_class": "crypto",
        "style": "event_driven",
        "reference": "Coinglass heatmap + Binance forceOrders",
        "expected_sharpe": "0.6–1.4",
        "description": "Ride mode follows cascading liquidations at heatmap clusters; fade mode fades exhausted cascades with decelerating volume.",
        "promotion_criteria": "30 days live + 15 trades + Sharpe > 0.4",
    },
    {
        "file": "insider_cluster_buying",
        "name": "Insider Cluster Buying",
        "asset_class": "equity",
        "style": "event_driven",
        "reference": "Lakonishok & Lee (2001) — SEC EDGAR Form 4",
        "expected_sharpe": "0.5–1.1",
        "description": "Detects clusters of 3+ insiders buying on the open market (≥$500k combined) within a 30-day window.",
        "promotion_criteria": "30 days live + 10 trades + Sharpe > 0.4",
    },
    {
        "file": "cross_asset_momentum",
        "name": "Cross-Asset Momentum",
        "asset_class": "multi",
        "style": "cross_asset_momentum",
        "reference": "Antonacci (2014) Global Equities Momentum",
        "expected_sharpe": "0.7–1.0",
        "description": "10-ETF monthly rotation: buys top-3 by blended 1/3/12M momentum only when each passes an absolute return filter. Credit spread gate cuts sizing in stress.",
        "promotion_criteria": "60 days live + 30 trades + Sharpe > 0.5",
    },
    {
        "file": "earnings_vol_premium",
        "name": "Earnings Vol Premium",
        "asset_class": "equity",
        "style": "short_volatility",
        "reference": "Augustin, Brenner & Subrahmanyam (2014)",
        "expected_sharpe": "1.0–1.6",
        "description": "Sells iron condors 7 days before earnings on stocks where IV rank ≥ 70% and implied move ≥ 5%. Harvests post-earnings IV crush.",
        "promotion_criteria": "60 days live + 30 trades + Sharpe > 0.7",
    },
    {
        "file": "quality_momentum_screen",
        "name": "Quality Momentum Screen",
        "asset_class": "equity",
        "style": "quality_momentum",
        "reference": "Asness, Frazzini & Pedersen (2019) QMJ",
        "expected_sharpe": "0.7–1.5",
        "description": "Monthly rebalance into top-25 stocks ranked by composite quality (SimFin fundamentals) + 12-1M momentum + low beta. Flattens to cash when credit spreads are red.",
        "promotion_criteria": "60 days live + 30 trades + Sharpe > 0.5",
    },
    {
        "file": "options_iv_premium_filter",
        "name": "Options IV Premium Filter",
        "asset_class": "options",
        "style": "short_volatility",
        "reference": "Israelov & Nielsen (2014)",
        "expected_sharpe": "0.7–1.1 (with IVR filter; 0.2 blind)",
        "description": "Sells cash-secured puts or covered calls only when IV Rank ≥ 50. Half-size at IVR 30–49; skips entirely below 30. Harvests premium when implied vol is rich.",
        "promotion_criteria": "60 days live + 30 trades + annualised premium yield ≥ 12%",
    },
    # ── Wave 1 Options Candidates (Phase 3) ───────────────────────────────────
    {
        "file": "options_short_strangle_45d",
        "name": "Short Strangle 45 DTE",
        "asset_class": "options",
        "style": "short_volatility",
        "reference": "Tastytrade Research — IVR-filtered premium selling",
        "expected_sharpe": "1.1–1.5",
        "description": "Sell 16-delta call + put on SPY/QQQ/IWM/EEM/GLD/TLT when IVR proxy > 50 and 20-day price range < 10% (range-bound). 45 DTE. Exit: 50% credit | 21 DTE | strike breach. 3% buying power per position.",
        "promotion_criteria": "63 days shadow + 15 trades + Sharpe > 1.0 + max drawdown < 20%",
        "candidate_stage": "enabled_false",
        "paper_only": True,
    },
    {
        "file": "options_iron_condor_spy",
        "name": "Iron Condor SPY",
        "asset_class": "options",
        "style": "short_volatility",
        "reference": "Sosnoff (2014) — Tastytrade mechanical IC",
        "expected_sharpe": "1.0–1.4",
        "description": "SPY-only iron condor: sell 16-delta strangle, buy 10-wide wings, 45 DTE. Entry: IVR proxy > 30 AND 5-day ATR contracting below 20-day ATR. Exit: 50% credit | 21 DTE | strike breach. 2% account risk per condor.",
        "promotion_criteria": "63 days shadow + 15 trades + Sharpe > 0.9 + max drawdown < 15%",
        "candidate_stage": "enabled_false",
        "paper_only": True,
    },
    {
        "file": "options_wheel_mechanical",
        "name": "Wheel Strategy (Mechanical)",
        "asset_class": "options",
        "style": "income",
        "reference": "Mechanical wheel — CSP → assignment → covered call",
        "expected_sharpe": "0.9–1.3",
        "description": "State machine: sell 30-delta CSP → on 50% credit close+repeat → on assignment sell 30-delta CC → repeat. Universe: dividend payers + large-cap ETFs, beta < 1.5, IVR > 30. Hard stop: -20% on assigned stock.",
        "promotion_criteria": "63 days shadow + 10 full wheel cycles + Sharpe > 0.8",
        "candidate_stage": "enabled_false",
        "paper_only": True,
    },
    {
        "file": "options_0dte_spx_condor",
        "name": "0DTE SPX Iron Condor",
        "asset_class": "options",
        "style": "short_volatility",
        "reference": "0DTE SPX condor — gamma scalping at 9:35 ET",
        "expected_sharpe": "0.7–1.2",
        "description": "Entry at 9:35 ET, sell 10-delta SPX condor with 25-point wings. Exit: 50% credit | 3 PM ET time stop | strike breach. Size: 0.75% per trade (strict cap). Skip FOMC/CPI weeks and VIX > 30.",
        "promotion_criteria": "63 days shadow + 30 trades + Sharpe > 0.7 + win rate > 65%",
        "candidate_stage": "enabled_false",
        "paper_only": True,
    },
    {
        "file": "options_post_earnings_ic",
        "name": "Post-Earnings IV Crush IC",
        "asset_class": "options",
        "style": "short_volatility",
        "reference": "IV crush arbitrage post-earnings announcement",
        "expected_sharpe": "1.2–1.6",
        "description": "Sell 16-delta IC with 10-wide wings, 30 DTE, within 24h of earnings report when IVR was > 50 pre-event. Universe: NVDA, TSLA, META, NFLX, COIN, AMD, MU. Exit: 25% credit | 21 DTE. Captures residual premium after IV crush.",
        "promotion_criteria": "63 days shadow + 10 earnings cycles + Sharpe > 1.1",
        "candidate_stage": "enabled_false",
        "paper_only": True,
    },
]


@router.get("/candidates")
def get_candidates() -> dict:
    """Return the list of strategy candidates currently in incubation."""
    return {"candidates": _CANDIDATE_CATALOG}


@router.get("/description/{name}")
def get_strategy_description(name: str) -> dict:
    """Return full description for a deployed bot or incubation candidate by name."""
    from strategy_lab.strategy_descriptions import DESCRIPTIONS
    desc = DESCRIPTIONS.get(name)
    if not desc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No description found for '{name}'")
    return desc


@router.get("/indicators/{strategy_id}")
def get_strategy_indicators(strategy_id: str) -> dict:
    """Return the chart indicator spec list for a given strategy id.

    Used by the Scout chart (`/strategy/scout/chart/:ticker/:strategy_id`) to
    render the *correct* overlays/subpanels for the strategy in question, instead
    of the legacy hardcoded 50d/200d MA pair. Falls back to a sensible default
    (SMA 20 + SMA 50) for unknown strategies — never 404s so the chart always
    renders.
    """
    from app.services.strategy_indicators import (
        indicators_as_dicts,
        engine_keys_for_strategy,
        get_timeframes_for_strategy,
    )

    specs = indicators_as_dicts(strategy_id)
    engine_keys = engine_keys_for_strategy(strategy_id)
    timeframes = get_timeframes_for_strategy(strategy_id)
    return {
        "strategy_id": strategy_id,
        "indicators": specs,
        # Comma-separated keys the frontend can pass straight to GET /api/bars/{symbol}?indicators=…
        "engine_keys": ",".join(engine_keys),
        # {"default": "1D", "allowed": ["1D", "4H", ...]} — chart timeframe chip rail.
        "timeframes": timeframes,
    }


@router.get("/portfolio")
def get_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return aggregated portfolio metrics for the current user's Strategy Lab bots.

    Delegates entirely to compute_strategy_lab_aggregate() — the single canonical
    source of truth — so that the headline numbers and the leaderboard always derive
    from the same computation as every other surface that shows bot performance.

    If no StrategyPortfolio rows exist yet for this user (first visit before
    /bots/portfolios/setup has run), we fall back to seeding demo allocations via
    the legacy path so the page always shows something useful.
    """
    from app.core.canonical import compute_strategy_lab_aggregate
    from app.db.models.bots import StrategyPortfolio
    from app.routers.bots import _ensure_portfolios_for_user

    # Always ensure portfolios exist and capitals are synced (idempotent).
    # This propagates any capital updates (e.g. $100k per bot) to existing rows
    # so the headline numbers stay correct without needing a manual migration.
    try:
        port_count = db.execute(
            select(func.count()).select_from(StrategyPortfolio).where(
                StrategyPortfolio.user_id == current_user.id
            )
        ).scalar() or 0
        _ensure_portfolios_for_user(db, current_user.id)
        if port_count == 0:
            # First visit — seed 35 days of demo history so the page isn't empty.
            _seed_demo_allocations(db, current_user.id)
    except Exception:
        logger.exception("Failed to auto-setup portfolios for user %d", current_user.id)

    result = compute_strategy_lab_aggregate(current_user.id, db)

    # If aggregate returns empty (no portfolios seeded), return safe zeros.
    if not result:
        return {
            "total_value_cents": 0,
            "yesterday_value_cents": 0,
            "today_pnl_cents": 0,
            "today_pnl_pct": 0.0,
            "return_30d_pct": 0.0,
            "return_30d_value_cents": 0,
            "return_all_time_pct": 0.0,
            "sharpe_30d": 0.0,
            "total_open_positions": 0,
            "total_watchlist_count": 0,
            "equity_curve": [],
            "leaderboard": [],
            "best_performer": None,
            "worst_performer": None,
        }

    return result
