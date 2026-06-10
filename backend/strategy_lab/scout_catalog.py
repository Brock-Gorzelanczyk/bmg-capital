"""
Strategy Scout catalog — strategies available for per-ticker evaluation.

Excludes strategies that require non-OHLCV inputs (on-chain metrics,
order-book imbalance, funding rates) or sub-daily minute-bar quant feeds.
Every entry here must have a generate_signals(bars, profile_config, regime)
function in its module.
"""
from __future__ import annotations

SCOUT_CATALOG: dict[str, dict] = {
    # ── Trend Following ───────────────────────────────────────────────────────
    "golden_cross": {
        "display_name": "Golden Cross",
        "category": "Trend",
        "module": "strategy_lab.strategies.golden_cross",
        "confidence_threshold": 0.45,
        "description": "SMA50 > SMA200 golden / death cross",
        "min_bars": 201,
    },
    "seykota_weekly_breakout": {
        "display_name": "Seykota Weekly Breakout",
        "category": "Trend",
        "module": "strategy_lab.strategies.seykota_weekly_breakout",
        "confidence_threshold": 0.50,
        "description": "Weekly trend-following breakout system",
        "min_bars": 52,
    },
    "turtle_donchian_s1": {
        "display_name": "Turtle Donchian S1",
        "category": "Trend",
        "module": "strategy_lab.strategies.turtle_donchian_s1",
        "confidence_threshold": 0.50,
        "description": "Classic Turtle System 1 — 20-day channel breakout",
        "min_bars": 55,
    },
    "turtle_donchian_s2": {
        "display_name": "Turtle Donchian S2",
        "category": "Trend",
        "module": "strategy_lab.strategies.turtle_donchian_s2",
        "confidence_threshold": 0.50,
        "description": "Turtle System 2 — 55-day channel breakout",
        "min_bars": 80,
    },
    "weinstein_stage2_breakout": {
        "display_name": "Weinstein Stage 2",
        "category": "Trend",
        "module": "strategy_lab.strategies.weinstein_stage2_breakout",
        "confidence_threshold": 0.50,
        "description": "Price breaks above 30-week MA with volume expansion",
        "min_bars": 150,
    },
    # ── Mean Reversion ────────────────────────────────────────────────────────
    "bollinger_squeeze": {
        "display_name": "Bollinger Squeeze",
        "category": "Mean Reversion",
        "module": "strategy_lab.strategies.bollinger_squeeze",
        "confidence_threshold": 0.45,
        "description": "Price at Bollinger band extreme with bandwidth squeeze",
        "min_bars": 25,
    },
    "rsi_bands": {
        "display_name": "RSI Bands",
        "category": "Mean Reversion",
        "module": "strategy_lab.strategies.rsi_bands",
        "confidence_threshold": 0.45,
        "description": "RSI extreme readings — oversold / overbought reversion",
        "min_bars": 30,
    },
    "rsi2_mean_reversion": {
        "display_name": "RSI-2 Mean Reversion",
        "category": "Mean Reversion",
        "module": "strategy_lab.strategies.rsi2_mean_reversion",
        "confidence_threshold": 0.45,
        "description": "Short-term RSI-2 extreme overshoot reversion",
        "min_bars": 10,
    },
    "vwap_reversion": {
        "display_name": "VWAP Reversion",
        "category": "Mean Reversion",
        "module": "strategy_lab.strategies.vwap_reversion",
        "confidence_threshold": 0.45,
        "description": "Price extended from VWAP — mean-reversion entry",
        "min_bars": 20,
    },
    "camarilla_pivot_reversion": {
        "display_name": "Camarilla Pivot Reversion",
        "category": "Mean Reversion",
        "module": "strategy_lab.strategies.camarilla_pivot_reversion",
        "confidence_threshold": 0.45,
        "description": "Camarilla H3/L3 pivot-level reversion signal",
        "min_bars": 5,
    },
    # ── Momentum ──────────────────────────────────────────────────────────────
    "fifty_two_week_high_momentum": {
        "display_name": "52-Week High Momentum",
        "category": "Momentum",
        "module": "strategy_lab.strategies.fifty_two_week_high_momentum",
        "confidence_threshold": 0.45,
        "description": "Near 52-week high with momentum continuation",
        "min_bars": 252,
    },
    "relative_strength_leaders": {
        "display_name": "Relative Strength Leaders",
        "category": "Momentum",
        "module": "strategy_lab.strategies.relative_strength_leaders",
        "confidence_threshold": 0.45,
        "description": "Leading relative strength versus benchmark",
        "min_bars": 60,
    },
    "factor_momentum_value": {
        "display_name": "Factor Momentum + Value",
        "category": "Momentum",
        "module": "strategy_lab.strategies.factor_momentum_value",
        "confidence_threshold": 0.45,
        "description": "Combined momentum and value factor signal",
        "min_bars": 100,
    },
    "frog_in_the_pan_momentum": {
        "display_name": "Frog In The Pan",
        "category": "Momentum",
        "module": "strategy_lab.strategies.frog_in_the_pan_momentum",
        "confidence_threshold": 0.45,
        "description": "Consistent vs. jumpy price acceleration signal",
        "min_bars": 21,
    },
    "dual_momentum_gem": {
        "display_name": "Dual Momentum (GEM)",
        "category": "Momentum",
        "module": "strategy_lab.strategies.dual_momentum_gem",
        "confidence_threshold": 0.50,
        "description": "Gary Antonacci's Global Equity Momentum model",
        "min_bars": 252,
    },
    # ── Breakout ──────────────────────────────────────────────────────────────
    "cup_and_handle": {
        "display_name": "Cup and Handle",
        "category": "Breakout",
        "module": "strategy_lab.strategies.cup_and_handle",
        "confidence_threshold": 0.50,
        "description": "Classic cup-and-handle pattern breakout",
        "min_bars": 40,
    },
    "darvas_box_breakout": {
        "display_name": "Darvas Box Breakout",
        "category": "Breakout",
        "module": "strategy_lab.strategies.darvas_box_breakout",
        "confidence_threshold": 0.50,
        "description": "Price breaks out of Darvas box formation",
        "min_bars": 20,
    },
    "bull_flag_continuation": {
        "display_name": "Bull Flag Continuation",
        "category": "Breakout",
        "module": "strategy_lab.strategies.bull_flag_continuation",
        "confidence_threshold": 0.50,
        "description": "Bull flag consolidation + momentum continuation",
        "min_bars": 20,
    },
    "canslim_pivot_breakout": {
        "display_name": "CANSLIM Pivot Breakout",
        "category": "Breakout",
        "module": "strategy_lab.strategies.canslim_pivot_breakout",
        "confidence_threshold": 0.50,
        "description": "CANSLIM method pivot-point breakout entry",
        "min_bars": 50,
    },
    "donchian_breakout": {
        "display_name": "Donchian Channel Breakout",
        "category": "Breakout",
        "module": "strategy_lab.strategies.crypto_quant_donchian_breakout_5m",
        "confidence_threshold": 0.45,
        "description": "Donchian channel breakout with volume confirmation",
        "min_bars": 20,
    },
    # ── Technical ─────────────────────────────────────────────────────────────
    "aroon_breakout": {
        "display_name": "Aroon Breakout",
        "category": "Technical",
        "module": "strategy_lab.strategies.aroon_breakout",
        "confidence_threshold": 0.45,
        "description": "Aroon indicator directional breakout signal",
        "min_bars": 30,
    },
    "hammer_at_support": {
        "display_name": "Hammer at Support",
        "category": "Technical",
        "module": "strategy_lab.strategies.hammer_at_support",
        "confidence_threshold": 0.45,
        "description": "Hammer candlestick at key support level",
        "min_bars": 30,
    },
    "three_white_soldiers": {
        "display_name": "Three White Soldiers",
        "category": "Technical",
        "module": "strategy_lab.strategies.three_white_soldiers",
        "confidence_threshold": 0.50,
        "description": "Three consecutive strong bullish candles",
        "min_bars": 5,
    },
    "ultimate_oscillator": {
        "display_name": "Ultimate Oscillator",
        "category": "Technical",
        "module": "strategy_lab.strategies.ultimate_oscillator",
        "confidence_threshold": 0.45,
        "description": "Multi-timeframe oscillator divergence signal",
        "min_bars": 40,
    },
    "chaikin_money_flow": {
        "display_name": "Chaikin Money Flow",
        "category": "Technical",
        "module": "strategy_lab.strategies.chaikin_money_flow",
        "confidence_threshold": 0.45,
        "description": "Accumulation / distribution money-flow signal",
        "min_bars": 21,
    },
    "macd_crossover": {
        "display_name": "MACD Crossover",
        "category": "Technical",
        "module": "strategy_lab.strategies.macd_crossover",
        "confidence_threshold": 0.45,
        "description": "MACD signal-line crossover entry",
        "min_bars": 35,
    },
    "earnings_drift_post": {
        "display_name": "Post-Earnings Drift (PEAD)",
        "category": "Event",
        "module": "strategy_lab.strategies.earnings_drift_post",
        "confidence_threshold": 0.45,
        "description": "Price drift following an earnings surprise",
        "min_bars": 60,
    },
    # ── Crypto ────────────────────────────────────────────────────────────────
    "crypto_ema_cross": {
        "display_name": "Crypto EMA Cross",
        "category": "Crypto Trend",
        "module": "strategy_lab.strategies.crypto_ema_cross",
        "confidence_threshold": 0.45,
        "description": "EMA crossover trend signal for crypto pairs",
        "min_bars": 50,
    },
    "crypto_momentum_breakout": {
        "display_name": "Crypto Momentum Breakout",
        "category": "Crypto Trend",
        "module": "strategy_lab.strategies.crypto_momentum_breakout",
        "confidence_threshold": 0.45,
        "description": "Price-momentum breakout for crypto assets",
        "min_bars": 30,
    },
    "crypto_rsi_mean_reversion": {
        "display_name": "Crypto RSI Reversion",
        "category": "Crypto Mean Reversion",
        "module": "strategy_lab.strategies.crypto_rsi_mean_reversion",
        "confidence_threshold": 0.45,
        "description": "RSI extreme reversion for crypto markets",
        "min_bars": 20,
    },
    "crypto_macd_swing": {
        "display_name": "Crypto MACD Swing",
        "category": "Crypto Trend",
        "module": "strategy_lab.strategies.crypto_macd_swing",
        "confidence_threshold": 0.45,
        "description": "MACD crossover swing signal for crypto",
        "min_bars": 35,
    },
    "crypto_volatility_breakout": {
        "display_name": "Crypto Volatility Breakout",
        "category": "Crypto Trend",
        "module": "strategy_lab.strategies.crypto_volatility_breakout",
        "confidence_threshold": 0.45,
        "description": "ATR-based volatility expansion breakout",
        "min_bars": 20,
    },
}


def get_catalog_entry(strategy_id: str) -> dict | None:
    return SCOUT_CATALOG.get(strategy_id)


def list_catalog() -> list[dict]:
    return [
        {
            "strategy_id": sid,
            "display_name": meta["display_name"],
            "category": meta["category"],
            "description": meta["description"],
            "confidence_threshold": meta["confidence_threshold"],
        }
        for sid, meta in SCOUT_CATALOG.items()
    ]
