"""
Crypto Mean Reversion — S6: Pin Bar Rejection (5m)

A pin bar (hammer / shooting star) at an extreme signals price rejection.

Hammer (long): small body near the TOP of a long lower wick.
  - Lower wick > 2× body height
  - Close in upper 30% of bar range
  - Occurs when price is below its 24-bar EMA (extreme low)

Shooting star (short): small body near the BOTTOM of a long upper wick.
  - Upper wick > 2× body height
  - Close in lower 30% of bar range
  - Occurs when price is above its 24-bar EMA (extreme high)

Confirmation: price must be at least 1.5% below/above the 24-bar EMA
to ensure we're catching an actual extreme, not mid-range noise.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_pin_bar_rejection"

EMA_PERIOD = 24
WICK_BODY_RATIO = 2.0     # wick must be >= 2x body
CLOSE_ZONE = 0.30          # close in top/bottom 30% of bar range
MIN_EXTREME_PCT = 0.015    # price must be ≥ 1.5% from EMA
MIN_BARS = EMA_PERIOD + 2

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD",
    "LINK/USD", "DOT/USD", "ADA/USD", "NEAR/USD", "ATOM/USD",
]


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _is_hammer(bar: dict) -> tuple[bool, float]:
    """Returns (is_hammer, body_as_fraction_of_range)."""
    o, h, l, c = bar["o"], bar["h"], bar["l"], bar["c"]
    bar_range = h - l
    if bar_range <= 0:
        return False, 0.0
    body = abs(c - o)
    lower_wick = min(o, c) - l
    # hammer: lower wick long, body small, close near top
    close_pct = (c - l) / bar_range
    if lower_wick > WICK_BODY_RATIO * max(body, bar_range * 0.01) and close_pct >= (1 - CLOSE_ZONE):
        return True, body / bar_range
    return False, 0.0


def _is_shooting_star(bar: dict) -> tuple[bool, float]:
    o, h, l, c = bar["o"], bar["h"], bar["l"], bar["c"]
    bar_range = h - l
    if bar_range <= 0:
        return False, 0.0
    body = abs(c - o)
    upper_wick = h - max(o, c)
    close_pct = (c - l) / bar_range
    if upper_wick > WICK_BODY_RATIO * max(body, bar_range * 0.01) and close_pct <= CLOSE_ZONE:
        return True, body / bar_range
    return False, 0.0


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
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
        ema = _ema(closes[:-1], EMA_PERIOD)
        if ema <= 0:
            continue
        pct_from_ema = (cur - ema) / ema

        bar = sb[-1]
        is_h, body_frac = _is_hammer(bar)
        is_s, body_frac_s = _is_shooting_star(bar)

        if is_h and pct_from_ema < -MIN_EXTREME_PCT:
            depth = abs(pct_from_ema) - MIN_EXTREME_PCT
            conf = round(min(0.82, 0.53 + depth * 3.0 + (1.0 - body_frac) * 0.05), 3)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MR_PIN_BAR hammer long: {pct_from_ema * 100:.1f}% below EMA-{EMA_PERIOD}, "
                       f"pin bar rejection at ${cur:.4f}",
                strategy=STRATEGY_NAME,
            ))
        elif is_s and pct_from_ema > MIN_EXTREME_PCT:
            depth = pct_from_ema - MIN_EXTREME_PCT
            conf = round(min(0.82, 0.53 + depth * 3.0 + (1.0 - body_frac_s) * 0.05), 3)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MR_PIN_BAR shooting star short: +{pct_from_ema * 100:.1f}% above EMA-{EMA_PERIOD}, "
                       f"pin bar rejection at ${cur:.4f}",
                strategy=STRATEGY_NAME,
            ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Pin Bar Rejection"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes = [b["c"] for b in symbol_bars]
    cur = closes[-1]
    ema = _ema(closes[:-1], EMA_PERIOD)
    pct_from_ema = (cur - ema) / ema if ema > 0 else 0
    bar = symbol_bars[-1]
    is_h, _ = _is_hammer(bar)
    is_s, _ = _is_shooting_star(bar)
    fired_long  = is_h and pct_from_ema < -MIN_EXTREME_PCT
    fired_short = is_s and pct_from_ema > MIN_EXTREME_PCT
    fired = fired_long or fired_short
    depth = max(0, abs(pct_from_ema) - MIN_EXTREME_PCT)
    score = round(min(0.82, 0.53 + depth * 3.0), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if fired_long else ("sell" if fired_short else None),
        "score": score,
        "summary": (
            f"Pin bar {'hammer' if fired_long else 'shooting star'} at {pct_from_ema * 100:.1f}% from EMA-{EMA_PERIOD}"
            if fired else
            f"No pin bar: hammer={is_h}, star={is_s}, pct_from_ema={pct_from_ema * 100:.2f}%"
        ),
        "conditions": [
            {"name": "Pin bar pattern", "current_value": int(is_h or is_s), "operator": "==",
             "required_value": 1, "unit": "", "passed": is_h or is_s, "to_pass": ""},
            {"name": f"Distance from EMA-{EMA_PERIOD}", "current_value": round(abs(pct_from_ema) * 100, 3),
             "operator": ">=", "required_value": round(MIN_EXTREME_PCT * 100, 1),
             "unit": "%", "passed": abs(pct_from_ema) >= MIN_EXTREME_PCT, "to_pass": ""},
        ],
    }
