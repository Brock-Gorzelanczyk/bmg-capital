from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Seed definitions ──────────────────────────────────────────────────────────

STRATEGY_SEEDS: List[Dict[str, Any]] = [
    # ── Phase 1: Price-Only (12) ──────────────────────────────────────────────
    {
        "strategy_key": "btc_ma_crossover",
        "name": "BTC Golden Cross",
        "category": "Trend Following",
        "description": (
            "Long Bitcoin when the 50-day moving average crosses above the 200-day MA (Golden Cross). "
            "Exit on Death Cross (50d crosses below 200d) or hard stop. One of the most historically "
            "reliable trend-following signals in crypto — captures the bulk of multi-month bull runs."
        ),
        "source_originator": "Technical Analysis",
        "version": 1,
        "tier_required": "free",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"fast_period": 50, "slow_period": 200, "symbol": "BTC/USDT"},
        "entry_conditions": [
            {"type": "ma_cross", "fast_period": 50, "slow_period": 200, "direction": "cross_above"}
        ],
        "exit_conditions": [
            {"type": "ma_cross", "fast_period": 50, "slow_period": 200, "direction": "cross_below"},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "*/15 * * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#f59e0b",
        "category_accent_to": "#f97316",
        "is_active": True,
        "sort_order": 1,
    },
    {
        "strategy_key": "pi_cycle_top",
        "name": "Pi Cycle Top",
        "category": "Cycle",
        "description": (
            "Uses the 111-day MA and 2× the 350-day MA. When the 111DMA crosses above 2×350DMA, "
            "BTC has historically been at or very near a cycle top within days. Inverse signal "
            "(111DMA recovering from below) is the accumulation entry. Developed by Philip Swift."
        ),
        "source_originator": "Philip Swift / LookIntoBitcoin",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"ma1_period": 111, "ma2_period": 350, "ma2_multiplier": 2, "symbol": "BTC/USDT"},
        "entry_conditions": [
            {"type": "ma_spread", "fast_ma": 111, "slow_ma": 350, "slow_multiplier": 2, "condition": "fast_below_slow", "threshold_pct": -5}
        ],
        "exit_conditions": [
            {"type": "ma_spread", "fast_ma": 111, "slow_ma": 350, "slow_multiplier": 2, "condition": "fast_crosses_above_slow"},
            {"type": "stop_loss", "atr_multiplier": 3.0},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 0 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#f97316",
        "category_accent_to": "#eab308",
        "is_active": True,
        "sort_order": 2,
    },
    {
        "strategy_key": "donchian_breakout",
        "name": "Donchian Channel Breakout",
        "category": "Trend Following",
        "description": (
            "Price breaks above the 20-day high channel on above-average volume. "
            "Trend-following entry that captures momentum breakouts before they extend. "
            "Exit on 10-day low channel break or trailing stop. Works well across mid/large-cap alts."
        ),
        "source_originator": "Richard Donchian",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT"],
        "parameters": {
            "entry_channel": 20,
            "exit_channel": 10,
            "volume_multiplier": 1.5,
        },
        "entry_conditions": [
            {"type": "price_vs_channel", "period": 20, "direction": "breakout_above"},
            {"type": "volume_vs_avg", "period": 20, "multiplier": 1.5},
        ],
        "exit_conditions": [
            {"type": "price_vs_channel", "period": 10, "direction": "breakdown_below"},
            {"type": "stop_loss", "atr_multiplier": 2.0},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "*/15 * * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#f59e0b",
        "category_accent_to": "#f97316",
        "is_active": True,
        "sort_order": 3,
    },
    {
        "strategy_key": "tsmom",
        "name": "Time-Series Momentum",
        "category": "Momentum",
        "description": (
            "12-minus-1 month return signal. If the cumulative return over the past 11 months "
            "(skipping last month) is positive, go long; negative means flat or short. "
            "Academic momentum signal adapted for crypto's extreme volatility. Rebalances monthly."
        ),
        "source_originator": "Moskowitz, Ooi, Pedersen (2012)",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT",
                              "LINK/USDT", "DOT/USDT", "MATIC/USDT", "ADA/USDT", "ATOM/USDT"],
        "parameters": {"lookback_months": 12, "skip_months": 1, "rebalance": "monthly"},
        "entry_conditions": [
            {"type": "return_sign", "lookback_days": 330, "skip_days": 30, "direction": "positive"}
        ],
        "exit_conditions": [
            {"type": "return_sign", "lookback_days": 330, "skip_days": 30, "direction": "negative"},
            {"type": "monthly_rebalance"},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 0 1 * *"},
        "signal_duration_required": None,
        "category_accent_from": "#8b5cf6",
        "category_accent_to": "#ec4899",
        "is_active": True,
        "sort_order": 4,
    },
    {
        "strategy_key": "cross_sectional_momentum",
        "name": "Cross-Sectional Momentum",
        "category": "Momentum",
        "description": (
            "Rank assets in the universe by 3-month return. Go long the top quartile, avoid "
            "the bottom quartile. Rebalances every 4 weeks. Captures relative strength — "
            "leaders continue to lead in trending markets."
        ),
        "source_originator": "Jegadeesh & Titman (1993)",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT",
            "LINK/USDT", "DOT/USDT", "MATIC/USDT", "ADA/USDT", "ATOM/USDT",
            "UNI/USDT", "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT",
        ],
        "parameters": {"lookback_days": 90, "top_pct": 25, "rebalance_days": 28},
        "entry_conditions": [
            {"type": "relative_rank", "lookback_days": 90, "rank_pct_threshold": 75}
        ],
        "exit_conditions": [
            {"type": "relative_rank", "lookback_days": 90, "rank_pct_threshold": 50, "condition": "falls_below"},
            {"type": "periodic_rebalance", "days": 28},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 0 * * 1"},
        "signal_duration_required": None,
        "category_accent_from": "#8b5cf6",
        "category_accent_to": "#ec4899",
        "is_active": True,
        "sort_order": 5,
    },
    {
        "strategy_key": "ma_200w",
        "name": "200-Week MA Retest",
        "category": "Trend Following",
        "description": (
            "Bitcoin's 200-week moving average has acted as the macro bear market floor in every cycle. "
            "Buy when BTC touches or dips below the 200WMA and begins recovering. "
            "Long-term hold exit when price is 3× the 200WMA (historically cycle top territory)."
        ),
        "source_originator": "PlanB / Bitcoin Fundamentals",
        "version": 1,
        "tier_required": "free",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"ma_period_weeks": 200, "exit_multiplier": 3.0},
        "entry_conditions": [
            {"type": "price_vs_ma", "period_weeks": 200, "condition": "within_pct", "pct": 5}
        ],
        "exit_conditions": [
            {"type": "price_vs_ma", "period_weeks": 200, "condition": "above_multiplier", "multiplier": 3.0},
            {"type": "stop_loss", "pct_below_ma": 20},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 0 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#f59e0b",
        "category_accent_to": "#f97316",
        "is_active": True,
        "sort_order": 6,
    },
    {
        "strategy_key": "altseason_index",
        "name": "Altseason Index",
        "category": "Market Structure",
        "description": (
            "When 75% of the top 50 altcoins have outperformed Bitcoin over the past 90 days, "
            "it's altseason. Rotate from BTC into a basket of top-performing alts. "
            "Exit when fewer than 50% outperform BTC. Based on the CoinMarketCap Altcoin Season Index."
        ),
        "source_originator": "CoinMarketCap",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": [
            "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT", "LINK/USDT",
            "DOT/USDT", "MATIC/USDT", "ADA/USDT", "ATOM/USDT", "UNI/USDT",
        ],
        "parameters": {"altseason_threshold": 75, "exit_threshold": 50, "lookback_days": 90},
        "entry_conditions": [
            {"type": "altseason_score", "threshold": 75, "lookback_days": 90}
        ],
        "exit_conditions": [
            {"type": "altseason_score", "threshold": 50, "condition": "falls_below"},
        ],
        "context_conditions": {"regime": "altseason"},
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */4 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#10b981",
        "category_accent_to": "#06b6d4",
        "is_active": True,
        "sort_order": 7,
    },
    {
        "strategy_key": "eth_btc_ratio",
        "name": "ETH/BTC Rotation",
        "category": "Market Structure",
        "description": (
            "Monitor the ETH/BTC ratio trend. Rising ratio = ETH outperforming = risk-on altseason. "
            "Falling ratio = BTC dominance rising = rotate into BTC. Uses 50-day MA of the ratio "
            "to filter noise. Captures major rotation cycles between the top two assets."
        ),
        "source_originator": "Ratio Analysis",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["ETH/USDT", "BTC/USDT"],
        "parameters": {"ratio_ma_period": 50},
        "entry_conditions": [
            {"type": "ratio_trend", "numerator": "ETH/USDT", "denominator": "BTC/USDT", "ma_period": 50, "direction": "rising"}
        ],
        "exit_conditions": [
            {"type": "ratio_trend", "numerator": "ETH/USDT", "denominator": "BTC/USDT", "ma_period": 50, "direction": "falling"},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "*/15 * * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#10b981",
        "category_accent_to": "#06b6d4",
        "is_active": True,
        "sort_order": 8,
    },
    {
        "strategy_key": "narrative_basket",
        "name": "Narrative Basket",
        "category": "Momentum",
        "description": (
            "Equal-weight basket of the top 3 momentum leaders within a selected crypto narrative "
            "(L2s, DeFi, AI tokens, RWA, etc.). Rotates every 4 weeks based on 30-day relative strength. "
            "Captures sector rotation — narratives move in waves."
        ),
        "source_originator": "Thematic Momentum",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": [
            "ARB/USDT", "OP/USDT", "MATIC/USDT", "STRK/USDT", "MANTA/USDT",
            "UNI/USDT", "AAVE/USDT", "CRV/USDT", "MKR/USDT", "LDO/USDT",
            "FET/USDT", "RENDER/USDT", "WLD/USDT", "AGIX/USDT", "OCEAN/USDT",
        ],
        "parameters": {"basket_size": 3, "lookback_days": 30, "rebalance_days": 28},
        "entry_conditions": [
            {"type": "narrative_momentum_rank", "top_n": 3, "lookback_days": 30}
        ],
        "exit_conditions": [
            {"type": "periodic_rebalance", "days": 28},
            {"type": "stop_loss", "atr_multiplier": 2.0},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 0 * * 1"},
        "signal_duration_required": None,
        "category_accent_from": "#8b5cf6",
        "category_accent_to": "#ec4899",
        "is_active": True,
        "sort_order": 9,
    },
    {
        "strategy_key": "zscore_reversal",
        "name": "Z-Score Mean Reversion",
        "category": "Mean Reversion",
        "description": (
            "Buy when price Z-score vs 20-day rolling mean drops below -2 standard deviations "
            "(statistically oversold). Exit when Z-score returns to 0 (mean). "
            "Crypto reverts hard after panic selloffs — this systematically captures those bounces."
        ),
        "source_originator": "Statistical Mean Reversion",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT",
            "LINK/USDT", "DOT/USDT", "MATIC/USDT",
        ],
        "parameters": {"lookback_days": 20, "entry_zscore": -2.0, "exit_zscore": 0.0},
        "entry_conditions": [
            {"type": "zscore", "period": 20, "threshold": -2.0, "condition": "below"}
        ],
        "exit_conditions": [
            {"type": "zscore", "period": 20, "threshold": 0.0, "condition": "above"},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "*/15 * * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#3b82f6",
        "category_accent_to": "#06b6d4",
        "is_active": True,
        "sort_order": 10,
    },
    {
        "strategy_key": "rsi_oversold_crypto",
        "name": "RSI Bounce",
        "category": "Mean Reversion",
        "description": (
            "Daily RSI(14) drops below 30 (oversold) on a confirmed uptrend asset. Wait for RSI "
            "to begin recovering (uptick from below 30). Enter long. Exit when RSI > 55 or stop hit. "
            "Simple, battle-tested signal — consistently effective on high-quality crypto assets."
        ),
        "source_originator": "J. Welles Wilder",
        "version": 1,
        "tier_required": "free",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT",
            "LINK/USDT", "DOT/USDT", "MATIC/USDT", "ADA/USDT",
        ],
        "parameters": {"rsi_period": 14, "oversold": 30, "exit_rsi": 55},
        "entry_conditions": [
            {"type": "rsi", "period": 14, "condition": "below", "threshold": 30},
            {"type": "rsi", "period": 14, "condition": "recovering"},
        ],
        "exit_conditions": [
            {"type": "rsi", "period": 14, "condition": "above", "threshold": 55},
            {"type": "stop_loss", "atr_multiplier": 2.0},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "*/15 * * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#3b82f6",
        "category_accent_to": "#06b6d4",
        "is_active": True,
        "sort_order": 11,
    },
    {
        "strategy_key": "halving_phase",
        "name": "Bitcoin Halving Phase",
        "category": "Cycle",
        "description": (
            "Position size based on where we are in the 4-year halving cycle. "
            "Months -6 to +6 around halving: accumulate BTC/ETH. +6 to +18: full risk-on (alts). "
            "+18 to +36: reduce and protect. +36 to next halving: bear market, minimal exposure. "
            "Historically the most reliable macro timing framework in crypto."
        ),
        "source_originator": "Bitcoin Halving Cycles",
        "version": 1,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT", "ETH/USDT"],
        "parameters": {
            "last_halving_date": "2024-04-20",
            "next_halving_estimate": "2028-04-01",
            "accumulation_window_months": 6,
            "bull_phase_months": 18,
        },
        "entry_conditions": [
            {"type": "halving_phase", "phase": "pre_halving", "months_before": 6},
            {"type": "halving_phase", "phase": "post_halving_bull", "months_after_max": 18},
        ],
        "exit_conditions": [
            {"type": "halving_phase", "phase": "late_bull", "months_after_min": 18},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 0 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#f97316",
        "category_accent_to": "#eab308",
        "is_active": True,
        "sort_order": 12,
    },

    # ── Phase 2: On-Chain Strategies (5) ─────────────────────────────────────
    # Data sources: CoinMetrics Community API (free), CoinGecko stablecoins, Binance futures OI
    {
        "strategy_key": "nupl_signal",
        "name": "NUPL Accumulation",
        "category": "On-Chain",
        "description": (
            "Net Unrealized Profit/Loss proxied from CoinMetrics Community API (free). "
            "NUPL = (market cap − realized cap) / market cap. Below 0.5 (fear/hope zone) "
            "means most holders are NOT in euphoria — historically the safe accumulation window. "
            "Enter when NUPL < 0.5 and price is above the 50-day MA."
        ),
        "source_originator": "CoinMetrics Community API",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coinmetrics"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"entry_nupl": 0.5, "exit_nupl": 0.75},
        "entry_conditions": [
            {"type": "on_chain_metric", "metric": "nupl", "condition": "below", "threshold": 0.5},
            {"type": "price_vs_ma", "period": 50, "condition": "above"},
        ],
        "exit_conditions": [
            {"type": "on_chain_metric", "metric": "nupl", "condition": "above", "threshold": 0.75},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */6 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#6366f1",
        "category_accent_to": "#8b5cf6",
        "is_active": True,
        "sort_order": 13,
    },
    {
        "strategy_key": "mvrv_zscore",
        "name": "MVRV Z-Score",
        "category": "On-Chain",
        "description": (
            "Market Value to Realized Value Z-Score computed from CoinMetrics Community API (free). "
            "Z-Score below 0 marks major cycle bottoms; above 7 marks cycle tops. "
            "Enter when Z-score is below 2 (historically: 0–2 = good entry, <0 = generational bottom). "
            "One of the most reliable on-chain BTC macro signals."
        ),
        "source_originator": "CoinMetrics / Murad Mahmudov",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coinmetrics"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"entry_zscore": 2.0, "exit_zscore": 7.0},
        "entry_conditions": [
            {"type": "on_chain_metric", "metric": "mvrv_zscore", "condition": "below", "threshold": 2.0}
        ],
        "exit_conditions": [
            {"type": "on_chain_metric", "metric": "mvrv_zscore", "condition": "above", "threshold": 7.0},
            {"type": "stop_loss", "pct": 25},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */6 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#6366f1",
        "category_accent_to": "#8b5cf6",
        "is_active": True,
        "sort_order": 14,
    },
    {
        "strategy_key": "sopr_reversal",
        "name": "SOPR Reversal",
        "category": "On-Chain",
        "description": (
            "Spent Output Profit Ratio proxy = current price / realized price (from CoinMetrics free). "
            "When SOPR is near or below 1.0, on-chain coins are moving at a loss — holders refuse to "
            "sell, forming a cost-basis support floor. Enter when SOPR is in the 0.85–1.02 zone, "
            "which captures the capitulation-to-recovery window. Exit when SOPR > 1.05."
        ),
        "source_originator": "CoinMetrics / Renato Shirakashi",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coinmetrics"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"entry_min": 0.85, "entry_max": 1.02, "exit_above": 1.05},
        "entry_conditions": [
            {"type": "on_chain_metric", "metric": "sopr_proxy", "condition": "in_range", "min": 0.85, "max": 1.02}
        ],
        "exit_conditions": [
            {"type": "on_chain_metric", "metric": "sopr_proxy", "condition": "above", "threshold": 1.05},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */6 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#6366f1",
        "category_accent_to": "#8b5cf6",
        "is_active": True,
        "sort_order": 15,
    },
    {
        "strategy_key": "exchange_netflow",
        "name": "Exchange Net Flow",
        "category": "On-Chain",
        "description": (
            "Uses Binance perpetual futures open interest history as a free netflow proxy. "
            "Declining open interest (−5% over 7 days) signals longs/shorts unwinding and coins "
            "potentially moving to cold storage — a reduction in sell pressure. "
            "No CryptoQuant API key required: Binance /futures/data/openInterestHist is public."
        ),
        "source_originator": "Binance Futures OI (free)",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["binance_futures"],
        "default_universe": ["BTC/USDT", "ETH/USDT"],
        "parameters": {"oi_change_threshold_pct": -5, "lookback_days": 7},
        "entry_conditions": [
            {"type": "oi_change_7d", "condition": "below_pct", "threshold": -5}
        ],
        "exit_conditions": [
            {"type": "oi_change_7d", "condition": "above_pct", "threshold": 5},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */6 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#6366f1",
        "category_accent_to": "#8b5cf6",
        "is_active": True,
        "sort_order": 16,
    },
    {
        "strategy_key": "stablecoin_ratio",
        "name": "Stablecoin Supply Ratio",
        "category": "On-Chain",
        "description": (
            "SSR = Bitcoin market cap / total stablecoin market cap (CoinGecko free tier). "
            "SSR < 5 means a large pool of stablecoins exists relative to BTC market cap — "
            "potential buying pressure waiting to enter. Enter when SSR is in the 'low' zone "
            "and BTC is above its 20-day MA. No API key required."
        ),
        "source_originator": "CoinGecko (free)",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coingecko"],
        "default_universe": ["BTC/USDT"],
        "parameters": {"entry_ssr_max": 5.0, "exit_ssr_min": 15.0},
        "entry_conditions": [
            {"type": "ssr", "condition": "below", "threshold": 5.0},
            {"type": "price_vs_ma", "period": 20, "condition": "above"},
        ],
        "exit_conditions": [
            {"type": "ssr", "condition": "above", "threshold": 15.0},
            {"type": "stop_loss", "atr_multiplier": 2.0},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */6 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#6366f1",
        "category_accent_to": "#8b5cf6",
        "is_active": True,
        "sort_order": 17,
    },

    # ── Phase 3: Derivatives (3) ──────────────────────────────────────────────
    # Data source: Binance /fapi/v1/fundingRate + /futures/data/openInterestHist (free, no key)
    {
        "strategy_key": "funding_rate_contrarian",
        "name": "Funding Rate Contrarian",
        "category": "Derivatives",
        "description": (
            "When 8-hour perpetual funding drops below −0.03% (shorts paying longs), the market is "
            "extremely crowded short. Mean reversion favors the long side as shorts must pay to hold. "
            "Enter when funding starts recovering from extreme negative (shorts beginning to cover). "
            "Uses Binance perpetual funding API — free, no key required."
        ),
        "source_originator": "Binance Perpetuals (free)",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": True,
        "required_data_sources": ["binance_futures"],
        "default_universe": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "parameters": {
            "entry_funding_threshold": -0.0003,
            "exit_funding_threshold": 0.0001,
            "bar_size": "8h",
        },
        "entry_conditions": [
            {"type": "funding_rate", "condition": "extreme_negative", "threshold": -0.0003},
            {"type": "funding_rate", "condition": "recovering"},
        ],
        "exit_conditions": [
            {"type": "funding_rate", "condition": "normalized", "threshold": 0.0001},
            {"type": "stop_loss", "atr_multiplier": 2.0},
        ],
        "context_conditions": None,
        "structure_type": "perpetual",
        "execution_schedule": {"cron": "0 0,8,16 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#dc2626",
        "category_accent_to": "#f97316",
        "is_active": True,
        "sort_order": 18,
    },
    {
        "strategy_key": "oi_divergence",
        "name": "Open Interest Divergence",
        "category": "Derivatives",
        "description": (
            "Compares open interest direction to price direction over 14 days. "
            "Price falling AND OI falling = liquidation capitulation (forced sellers, not new shorts) — "
            "historically a strong bottom signal. Confirmed when RSI recovers from below 35. "
            "Uses Binance perpetual OI history — free, no key required."
        ),
        "source_originator": "Binance Perpetuals (free)",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["binance_futures"],
        "default_universe": ["BTC/USDT", "ETH/USDT"],
        "parameters": {"oi_lookback_days": 14, "price_lookback_days": 14, "rsi_period": 14},
        "entry_conditions": [
            {"type": "oi_price_divergence", "price_direction": "falling", "oi_direction": "falling"},
            {"type": "rsi", "period": 14, "condition": "recovering_from_below", "threshold": 35},
        ],
        "exit_conditions": [
            {"type": "oi_change", "direction": "rising", "threshold_pct": 5},
            {"type": "stop_loss", "atr_multiplier": 2.0},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */4 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#dc2626",
        "category_accent_to": "#f97316",
        "is_active": True,
        "sort_order": 19,
    },
    {
        "strategy_key": "basis_carry",
        "name": "Cash & Carry Basis",
        "category": "Derivatives",
        "description": (
            "Enter long spot BTC/ETH when perpetual funding has been persistently positive for 3+ "
            "consecutive 8h bars AND annualized yield exceeds 10%. Funding above this level means "
            "longs are paying — spot buyers collect yield vs. perp shorts. "
            "For a fully delta-neutral carry trade, manually short the same size on the perpetual. "
            "Uses Binance perpetual funding API — free, no key required."
        ),
        "source_originator": "Binance Perpetuals (free)",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": True,
        "required_data_sources": ["binance_futures"],
        "default_universe": ["BTC/USDT", "ETH/USDT"],
        "parameters": {
            "min_annual_yield_pct": 10.0,
            "funding_threshold": 0.0003,
            "min_consecutive_bars": 3,
        },
        "entry_conditions": [
            {"type": "funding_rate", "condition": "persistently_positive", "threshold": 0.0003, "min_bars": 3},
            {"type": "annualized_yield", "condition": "above_pct", "threshold": 10.0},
        ],
        "exit_conditions": [
            {"type": "funding_rate", "condition": "below", "threshold": 0.0001},
            {"type": "stop_loss", "atr_multiplier": 1.5},
        ],
        "context_conditions": None,
        "structure_type": "hedged",
        "execution_schedule": {"cron": "0 0,8,16 * * *"},
        "signal_duration_required": {"condition": "funding_positive", "min_bars": 3, "bar_size": "8h"},
        "category_accent_from": "#dc2626",
        "category_accent_to": "#f97316",
        "is_active": True,
        "sort_order": 20,
    },

    # ── Phase 4: Whale Activity (1) ───────────────────────────────────────────
    {
        "strategy_key": "whale_accumulation",
        "name": "Whale Accumulation",
        "category": "Whale Activity",
        "description": (
            "Track large wallet net accumulation via Arkham Intelligence. Wallets holding >1000 BTC "
            "or >10,000 ETH show sustained inflow patterns before major price moves. "
            "7-day net accumulation across the top 50 non-exchange wallets triggers the signal. "
            "Arkham free tier required."
        ),
        "source_originator": "Arkham Intelligence",
        "version": 2,
        "tier_required": "plus",
        "comprehension_quiz_required": False,
        "required_data_sources": ["coinmetrics"],
        "default_universe": ["BTC/USDT", "ETH/USDT"],
        "parameters": {
            "min_wallet_size_btc": 1000,
            "min_wallet_size_eth": 10000,
            "lookback_days": 7,
            "top_n_wallets": 50,
        },
        "entry_conditions": [
            {"type": "whale_netflow", "direction": "inflow", "lookback_days": 7, "top_n": 50}
        ],
        "exit_conditions": [
            {"type": "whale_netflow", "direction": "outflow", "lookback_days": 7, "top_n": 50},
            {"type": "stop_loss", "atr_multiplier": 2.5},
        ],
        "context_conditions": None,
        "structure_type": "simple",
        "execution_schedule": {"cron": "0 */6 * * *"},
        "signal_duration_required": None,
        "category_accent_from": "#1e40af",
        "category_accent_to": "#7c3aed",
        "is_active": True,
        "sort_order": 21,
    },
]

# ── Registry cache ────────────────────────────────────────────────────────────

_cache: dict[str, dict] = {}
_cache_ready = False


def _to_dict(row) -> dict:
    return {
        "id": row.id,
        "strategy_key": row.strategy_key,
        "name": row.name,
        "category": row.category,
        "description": row.description,
        "source_originator": row.source_originator,
        "version": row.version,
        "tier_required": row.tier_required,
        "comprehension_quiz_required": row.comprehension_quiz_required,
        "required_data_sources": row.required_data_sources,
        "default_universe": row.default_universe,
        "parameters": row.parameters,
        "entry_conditions": row.entry_conditions,
        "exit_conditions": row.exit_conditions,
        "context_conditions": row.context_conditions,
        "structure_type": row.structure_type,
        "execution_schedule": row.execution_schedule,
        "signal_duration_required": row.signal_duration_required,
        "category_accent_from": row.category_accent_from,
        "category_accent_to": row.category_accent_to,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def seed_strategy_definitions(db: Session) -> None:
    from app.db.models.strategy_definition import StrategyDefinition

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seeded = 0
    for seed in STRATEGY_SEEDS:
        existing = db.query(StrategyDefinition).filter_by(strategy_key=seed["strategy_key"]).first()
        if existing is None:
            row = StrategyDefinition(
                **seed,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            seeded += 1
        else:
            # Update mutable fields on version bump
            if seed.get("version", 1) > existing.version:
                for k, v in seed.items():
                    if k not in ("strategy_key", "created_at"):
                        setattr(existing, k, v)
                existing.updated_at = now

    db.commit()
    if seeded:
        logger.info(f"strategy_registry: seeded {seeded} new strategy definitions")


def _prime_cache(db: Session) -> None:
    global _cache, _cache_ready
    from app.db.models.strategy_definition import StrategyDefinition

    rows = db.query(StrategyDefinition).order_by(StrategyDefinition.sort_order).all()
    _cache = {r.strategy_key: _to_dict(r) for r in rows}
    _cache_ready = True


def get_all_definitions(db: Session) -> list[dict]:
    if not _cache_ready:
        _prime_cache(db)
    return sorted(_cache.values(), key=lambda d: d["sort_order"])


def get_definition(db: Session, strategy_key: str) -> Optional[dict]:
    if not _cache_ready:
        _prime_cache(db)
    return _cache.get(strategy_key)


def invalidate_cache() -> None:
    global _cache_ready
    _cache_ready = False
