"""
Crypto Mean Reversion — S1: Bollinger Extreme (5m)

Price closes outside Bollinger(20, 2.5σ) — an extreme deviation.
Unlike the quant_bb_breakout (which trades WITH the breakout), this strategy
FADES the move: enters against the direction of the close expecting a snap-back.

Entry:
  close > upper(2.5σ) → short (overbought extreme, mean revert down)
  close < lower(2.5σ) → long  (oversold extreme, mean revert up)

Target: return to middle band (SMA-20). Stop: 2% (wider than scalper).
Volume: NOT required — mean reversion works even on thin volume
(we want to catch exhaustion, not momentum).
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_bollinger_extreme"

BB_PERIOD = 20
BB_STDEV = 2.5     # extreme threshold — wider than standard 2σ
MIN_BARS = BB_PERIOD + 2

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD",
    "LINK/USD", "DOT/USD", "ADA/USD", "NEAR/USD", "ATOM/USD",
]


def _bb(closes: list[float], period: int, stdev: float) -> tuple[float, float, float]:
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    window = closes[-period:]
    sma = sum(window) / period
    std = math.sqrt(sum((c - sma) ** 2 for c in window) / period)
    return sma + stdev * std, sma, sma - stdev * std


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
        upper, middle, lower = _bb(closes, BB_PERIOD, BB_STDEV)
        if upper <= 0:
            continue
        band_width = upper - lower
        if band_width <= 0:
            continue

        if cur > upper:
            excess = (cur - upper) / band_width
            conf = round(min(0.85, 0.52 + excess * 1.8), 3)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MR_BB_EXTREME short: close {cur:.4f} > upper {upper:.4f} "
                       f"(+{excess * 100:.1f}% of band), target mid {middle:.4f}",
                strategy=STRATEGY_NAME,
            ))
        elif cur < lower:
            excess = (lower - cur) / band_width
            conf = round(min(0.85, 0.52 + excess * 1.8), 3)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MR_BB_EXTREME long: close {cur:.4f} < lower {lower:.4f} "
                       f"(-{excess * 100:.1f}% of band), target mid {middle:.4f}",
                strategy=STRATEGY_NAME,
            ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Bollinger Extreme Fade"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes = [b["c"] for b in symbol_bars]
    cur = closes[-1]
    upper, middle, lower = _bb(closes, BB_PERIOD, BB_STDEV)
    band_width = upper - lower
    fired_short = cur > upper
    fired_long  = cur < lower
    fired = fired_short or fired_long
    excess = (cur - upper) / band_width if fired_short else ((lower - cur) / band_width if fired_long else 0)
    score = round(min(0.85, 0.52 + excess * 1.8), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "sell" if fired_short else ("buy" if fired_long else None),
        "score": score,
        "summary": (
            f"BB extreme {'short' if fired_short else 'long'} — "
            f"close {'above' if fired_short else 'below'} {BB_STDEV}σ band by {excess * 100:.1f}% of width"
            if fired else
            f"Inside {BB_STDEV}σ band [{lower:.4f}–{upper:.4f}]"
        ),
        "conditions": [
            {"name": f"Price outside Bollinger(20, {BB_STDEV}σ)", "current_value": round(cur, 4),
             "operator": "outside_band", "required_value": [round(lower, 4), round(upper, 4)],
             "unit": "", "passed": fired, "to_pass": ""},
        ],
    }
