from __future__ import annotations

"""
Crypto strategy preset definitions — 18 active strategies across 8 categories.

Per-coin strategies use _apply_crypto_filters in crypto_runner.py.
Cross-sectional strategies (requiring comparison across all coins) are listed
in CRYPTO_CROSS_SECTIONAL_KEYS and handled by _collect_cross_sectional_results.
"""

from typing import Any

CRYPTO_PRESET_SCREENS: dict[str, list[dict[str, Any]]] = {
    # ── Existing 8 (Phase 0) ──────────────────────────────────────────────────
    "btc_ma_crossover": [
        {"type": "MACross",      "value": "golden"},
        {"type": "PriceVsMA",    "field": "ma_200", "operator": "gt", "value": 0},
    ],
    "rsi_oversold_crypto": [
        {"type": "RSI",          "operator": "lt", "value": 35},
        {"type": "PriceVsMA",    "field": "ma_50",  "operator": "gt", "value": 0},
    ],
    "breakout_30d_high": [
        {"type": "Breakout",     "value": 30},
        {"type": "VolumeSurge",  "value": 1.5},
    ],
    "volume_surge_crypto": [
        {"type": "VolumeSurge",  "value": 2.0},
        {"type": "RSI",          "operator": "gt", "value": 45},
    ],
    "dca_accumulation": [
        {"type": "RSI",          "operator": "lt", "value": 40},
        {"type": "PriceVsMA",    "field": "ma_200", "operator": "lt", "value": 0},
    ],
    "momentum_continuation": [
        {"type": "RSI",          "operator": "gt", "value": 55},
        {"type": "RSI",          "operator": "lt", "value": 75},
        {"type": "PriceVsMA",    "field": "ma_50",  "operator": "gt", "value": 0},
        {"type": "PriceVsMA",    "field": "ma_200", "operator": "gt", "value": 0},
    ],
    "oversold_bounce": [
        {"type": "RSI",          "operator": "lt", "value": 30},
        {"type": "VolumeSurge",  "value": 1.2},
    ],
    "golden_zone_retrace": [
        {"type": "PriceVsMA",    "field": "ma_50",  "operator": "gt", "value": 0},
        {"type": "PriceVsMA",    "field": "ma_200", "operator": "gt", "value": 0},
        {"type": "RSI",          "operator": "gt", "value": 40},
        {"type": "RSI",          "operator": "lt", "value": 60},
    ],

    # ── Phase 1 new per-coin strategies (6) ───────────────────────────────────
    "pi_cycle_top": [
        # 111-day MA below 95% of 2×350-day MA = accumulation zone (not at cycle top)
        {"type": "PiCycle", "operator": "lt", "value": 0.95},
    ],
    "donchian_breakout": [
        {"type": "Breakout",    "value": 20},
        {"type": "VolumeSurge", "value": 1.5},
    ],
    "tsmom": [
        # 12-month return (skip 1 month) is positive
        {"type": "TSMOM", "lookback_days": 365, "skip_days": 30, "operator": "gt", "value": 0},
    ],
    "ma_200w": [
        # Price within 20% below / 10% above the 200-day MA (accumulation near long-term support)
        {"type": "PriceNearMA", "period": 200, "max_pct_above": 0.10, "max_pct_below": 0.20},
    ],
    "zscore_reversal": [
        # Price Z-score vs 20-day mean below -2 standard deviations (statistically oversold)
        {"type": "ZScore", "period": 20, "operator": "lt", "value": -2.0},
    ],
    "halving_phase": [
        # Active only during pre-halving (≤6 months out) or post-halving bull (≤18 months in)
        {"type": "HalvingPhase", "phases": ["pre_halving", "post_halving_bull"]},
    ],

    # ── Phase 2 on-chain strategies (5) ───────────────────────────────────────
    "nupl_signal": [
        # NUPL below 0.5 = fear/capitulation/early-hope zone (not euphoria)
        {"type": "OnChainNUPL", "operator": "lt", "value": 0.5},
    ],
    "mvrv_zscore": [
        # MVRV Z-score below 2.0 = not yet in bubble territory
        {"type": "OnChainMVRV", "zscore_operator": "lt", "zscore_value": 2.0},
    ],
    "sopr_reversal": [
        # SOPR proxy 0.85–1.02 = coins moving near/below cost basis (capitulation support)
        {"type": "OnChainSOPR", "min_value": 0.85, "max_value": 1.02},
    ],
    "exchange_netflow": [
        # Declining open interest = position unwinding / spot accumulation signal
        {"type": "OnChainNetflow", "signal": "outflow"},
    ],
    "stablecoin_ratio": [
        # SSR < 5 = large stablecoin dry-powder pool relative to BTC market cap
        {"type": "OnChainSSR", "signal": "low"},
    ],

    # ── Phase 3 derivatives strategies (3) ────────────────────────────────────
    "funding_rate_contrarian": [
        # Extreme negative funding (< -0.03%) = shorts paying longs = contrarian long entry
        {"type": "FundingRate", "condition": "extreme_negative", "threshold": -0.0003},
    ],
    "oi_divergence": [
        # Price falling AND open interest falling = capitulation (liquidations, not fresh shorts)
        {"type": "OIDivergence", "price_falling": True, "oi_falling": True},
    ],
    "basis_carry": [
        # Funding persistently positive for 3+ 8h bars AND annualized yield > 10%
        {"type": "FundingRate", "condition": "persistently_positive", "threshold": 0.0003, "min_bars": 3},
    ],

    # ── Phase 4 whale activity (1) ────────────────────────────────────────────
    "whale_accumulation": [
        # Large wallet count (addresses > $1M) rising 7d = accumulation signal
        {"type": "WhaleAccumulation", "signal": "accumulating"},
    ],
}

# Strategies that require comparing all coins at once (handled separately in the runner)
CRYPTO_CROSS_SECTIONAL_KEYS: list[str] = [
    "cross_sectional_momentum",
    "altseason_index",
    "eth_btc_ratio",
    "narrative_basket",
]

# Per-strategy universe override — only screen these symbols for BTC-only / restricted strategies
CRYPTO_RESTRICTED_UNIVERSES: dict[str, list[str]] = {
    "btc_ma_crossover":  ["BTC/USDT"],
    "pi_cycle_top":      ["BTC/USDT"],
    "ma_200w":           ["BTC/USDT"],
    "halving_phase":     ["BTC/USDT", "ETH/USDT"],
    # On-chain: all BTC-focused (MVRV/NUPL/SOPR are BTC metrics)
    "nupl_signal":              ["BTC/USDT"],
    "mvrv_zscore":              ["BTC/USDT"],
    "sopr_reversal":            ["BTC/USDT"],
    "exchange_netflow":         ["BTC/USDT", "ETH/USDT"],
    "stablecoin_ratio":         ["BTC/USDT"],
    # Derivatives: major perp markets
    "funding_rate_contrarian":  ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "oi_divergence":            ["BTC/USDT", "ETH/USDT"],
    "basis_carry":              ["BTC/USDT", "ETH/USDT"],
    "whale_accumulation":           ["BTC/USDT", "ETH/USDT"],
}

CRYPTO_PRESET_LABELS: dict[str, str] = {
    # Phase 0 (original 8)
    "btc_ma_crossover":          "BTC Golden Cross",
    "rsi_oversold_crypto":       "RSI Bounce",
    "breakout_30d_high":         "30-Day Breakout",
    "volume_surge_crypto":       "Volume Surge",
    "dca_accumulation":          "DCA Accumulation Zone",
    "momentum_continuation":     "Momentum Continuation",
    "oversold_bounce":           "Oversold Bounce",
    "golden_zone_retrace":       "Golden Zone Retrace",
    # Phase 1 per-coin (6)
    "pi_cycle_top":              "Pi Cycle Top",
    "donchian_breakout":         "Donchian Breakout",
    "tsmom":                     "Time-Series Momentum",
    "ma_200w":                   "200-Day MA Support",
    "zscore_reversal":           "Z-Score Reversion",
    "halving_phase":             "Halving Phase",
    # Phase 1 cross-sectional (4)
    "cross_sectional_momentum":  "Cross-Sectional Momentum",
    "altseason_index":           "Altseason Index",
    "eth_btc_ratio":             "ETH/BTC Rotation",
    "narrative_basket":          "Narrative Basket",
    # Phase 2 on-chain (5)
    "nupl_signal":               "NUPL Accumulation",
    "mvrv_zscore":               "MVRV Z-Score",
    "sopr_reversal":             "SOPR Reversal",
    "exchange_netflow":          "Exchange Net Flow",
    "stablecoin_ratio":          "Stablecoin Supply Ratio",
    # Phase 3 derivatives (3)
    "funding_rate_contrarian":   "Funding Rate Contrarian",
    "oi_divergence":             "Open Interest Divergence",
    "basis_carry":               "Cash & Carry Basis",
    # Phase 4 whale activity (1)
    "whale_accumulation":            "Whale Accumulation",
}

# Full universe — top coins + narrative/DeFi/AI tokens for basket strategies
CRYPTO_UNIVERSE = [
    # Top caps
    "BTC/USDT",  "ETH/USDT",  "SOL/USDT",  "BNB/USDT",  "XRP/USDT",
    "ADA/USDT",  "AVAX/USDT", "DOGE/USDT", "LINK/USDT", "DOT/USDT",
    # Mid caps / Layer-2
    "MATIC/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT",  "NEAR/USDT",
    "APT/USDT",   "ARB/USDT", "OP/USDT",   "INJ/USDT",  "SUI/USDT",
    # DeFi (narrative basket)
    "AAVE/USDT", "CRV/USDT", "LDO/USDT", "MKR/USDT",
    # AI tokens (narrative basket)
    "FET/USDT", "RENDER/USDT", "WLD/USDT", "OCEAN/USDT",
]

# Narrative sub-universe used by narrative_basket cross-sectional strategy
NARRATIVE_UNIVERSE: list[str] = [
    "ARB/USDT",    "OP/USDT",     "MATIC/USDT",  "UNI/USDT",
    "AAVE/USDT",   "CRV/USDT",    "LDO/USDT",    "MKR/USDT",
    "FET/USDT",    "RENDER/USDT", "WLD/USDT",    "OCEAN/USDT",
]
