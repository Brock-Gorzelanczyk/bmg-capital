from __future__ import annotations

"""
Crypto strategy preset definitions.

Same pattern as filters.py / PRESET_SCREENS but for crypto assets.
Each preset is a list of filter-spec dicts; crypto_runner.py evaluates them
against CCXT/Binance OHLCV bars.
"""

from typing import Any

# Filter spec dict keys:
#   type:     filter class name (RSI, MACross, PriceVsMA, VolumeSurge, Breakout)
#   field:    sub-field within the type (e.g. "window" for RSI)
#   operator: gt / lt / gte / lte / eq
#   value:    comparison threshold (numeric or string)

CRYPTO_PRESET_SCREENS: dict[str, list[dict[str, Any]]] = {
    "btc_ma_crossover": [
        {"type": "MACross",      "field": "cross",   "operator": "eq",  "value": "golden"},
        {"type": "PriceVsMA",    "field": "ma_200",  "operator": "gt",  "value": 0},
    ],
    "rsi_oversold_crypto": [
        {"type": "RSI",          "field": "window",  "operator": "lt",  "value": 35},
        {"type": "PriceVsMA",    "field": "ma_50",   "operator": "gt",  "value": 0},
    ],
    "breakout_30d_high": [
        {"type": "Breakout",     "field": "period",  "operator": "gte", "value": 30},
        {"type": "VolumeSurge",  "field": "mult",    "operator": "gte", "value": 1.5},
    ],
    "volume_surge_crypto": [
        {"type": "VolumeSurge",  "field": "mult",    "operator": "gte", "value": 2.0},
        {"type": "RSI",          "field": "window",  "operator": "gt",  "value": 45},
    ],
    "dca_accumulation": [
        {"type": "RSI",          "field": "window",  "operator": "lt",  "value": 40},
        {"type": "PriceVsMA",    "field": "ma_200",  "operator": "lt",  "value": 0},
    ],
    "momentum_continuation": [
        {"type": "RSI",          "field": "window",  "operator": "gt",  "value": 55},
        {"type": "RSI",          "field": "window",  "operator": "lt",  "value": 75},
        {"type": "PriceVsMA",    "field": "ma_50",   "operator": "gt",  "value": 0},
        {"type": "PriceVsMA",    "field": "ma_200",  "operator": "gt",  "value": 0},
    ],
    "oversold_bounce": [
        {"type": "RSI",          "field": "window",  "operator": "lt",  "value": 30},
        {"type": "VolumeSurge",  "field": "mult",    "operator": "gte", "value": 1.2},
    ],
    "golden_zone_retrace": [
        {"type": "PriceVsMA",    "field": "ma_50",   "operator": "gt",  "value": 0},
        {"type": "PriceVsMA",    "field": "ma_200",  "operator": "gt",  "value": 0},
        {"type": "RSI",          "field": "window",  "operator": "gt",  "value": 40},
        {"type": "RSI",          "field": "window",  "operator": "lt",  "value": 60},
    ],
}

CRYPTO_PRESET_LABELS: dict[str, str] = {
    "btc_ma_crossover":      "BTC Golden Cross",
    "rsi_oversold_crypto":   "Crypto RSI Oversold",
    "breakout_30d_high":     "30-Day Breakout",
    "volume_surge_crypto":   "Volume Surge",
    "dca_accumulation":      "DCA Accumulation Zone",
    "momentum_continuation": "Momentum Continuation",
    "oversold_bounce":       "Oversold Bounce",
    "golden_zone_retrace":   "Golden Zone Retrace",
}

# Symbols universe — top coins tracked by the strategy engine
CRYPTO_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "LINK/USDT", "DOT/USDT",
    "MATIC/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "NEAR/USDT",
    "APT/USDT", "ARB/USDT", "OP/USDT", "INJ/USDT", "SUI/USDT",
]
