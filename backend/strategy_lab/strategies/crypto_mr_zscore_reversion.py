"""
Crypto Mean Reversion — S4: Z-Score Reversion (5m)

Price z-score against its rolling mean: when |z| > 2 (2 std deviations from
the 48-bar rolling mean), the move is statistically extreme and likely to
revert within the hold period.

Entry:
  z < -2 → long  (2 std below rolling mean)
  z >  2 → short (2 std above rolling mean)

The 48-bar lookback on 5m bars = 4 hours of context. Classic mean reversion.
Target: z = 0 (return to mean). Stop: 2%.
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_zscore_reversion"

ZSCORE_PERIOD = 48    # 48 × 5m = 4 hours
ZSCORE_ENTRY = 2.0    # enter when |z| > 2
MIN_BARS = ZSCORE_PERIOD + 2

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD",
    "LINK/USD", "DOT/USD", "ADA/USD", "NEAR/USD", "ATOM/USD",
]


def _zscore(closes: list[float], period: int) -> float:
    if len(closes) < period + 1:
        return 0.0
    window = closes[-(period + 1):-1]
    mean = sum(window) / period
    std = math.sqrt(sum((c - mean) ** 2 for c in window) / period)
    if std <= 0:
        return 0.0
    return (closes[-1] - mean) / std


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    # 2026-06-30 regime gate: mean reversion is structurally weak in trending
    # regimes (bull/bear). Trade only in chop or when regime data is unavailable.
    trend = (regime or {}).get("trend_regime", "").lower()
    if trend in ("bull", "bear"):
        return []
    signals: list[Signal] = []
    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", UNIVERSE) if isinstance(universe, dict) else UNIVERSE

    for symbol in symbols:
        sb = bars.get(symbol, [])
        if len(sb) < MIN_BARS:
            continue
        closes = [b["c"] for b in sb]
        cur = closes[-1]
        if cur <= 0:
            continue
        z = _zscore(closes, ZSCORE_PERIOD)
        if abs(z) < ZSCORE_ENTRY:
            continue

        depth = abs(z) - ZSCORE_ENTRY
        conf = round(min(0.87, 0.55 + depth * 0.08), 3)
        side = "buy" if z < 0 else "sell"
        signals.append(Signal(
            symbol=symbol, side=side, confidence=conf, size_hint=min(1.0, conf),
            reason=f"MR_ZSCORE {side.upper()}: z={z:.2f} (|z|>{ZSCORE_ENTRY}), "
                   f"{ZSCORE_PERIOD}-bar mean reversion at ${cur:.4f}",
            strategy=STRATEGY_NAME,
        ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Z-Score Reversion"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes = [b["c"] for b in symbol_bars]
    z = _zscore(closes, ZSCORE_PERIOD)
    fired = abs(z) >= ZSCORE_ENTRY
    depth = abs(z) - ZSCORE_ENTRY
    score = round(min(0.87, 0.55 + depth * 0.08), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if (fired and z < 0) else ("sell" if fired else None),
        "score": score,
        "summary": f"Z-score {z:.2f} vs threshold ±{ZSCORE_ENTRY} — {'FIRED' if fired else 'within range'}",
        "conditions": [
            {"name": f"Z-score (vs {ZSCORE_PERIOD}-bar mean)", "current_value": round(z, 4),
             "operator": f"|z| >= {ZSCORE_ENTRY}", "required_value": ZSCORE_ENTRY,
             "unit": "σ", "passed": fired, "to_pass": f"Currently {z:.2f}σ"},
        ],
    }
