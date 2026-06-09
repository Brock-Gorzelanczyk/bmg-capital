"""
Crypto Quant Scalper — S5: Volume Spike Continuation (1m)

A sudden 3x+ volume bar in a trending environment signals institutional
participation. Fade attempts fail when the big money is still pushing.
Scalp in the direction of the volume spike, targeting 1% continuation.

Entry:
  1. Last bar volume > 3× 20-bar avg
  2. Last bar is a strong directional bar: |close - open| > 50% of bar range
  3. The prior 5 bars trend in the same direction (EMA slope)

Tight stop at 50bps, target 100bps (2:1 R/R, aligned with scalper profile).
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_scalper_volume_spike_continuation"

VOL_AVG_PERIOD = 20
VOL_SPIKE_MULT = 3.0
BAR_BODY_MIN_PCT = 0.50    # body must be >= 50% of high-low range
TREND_BARS = 5
MIN_BARS = VOL_AVG_PERIOD + TREND_BARS + 2

UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "AVAX/USD"]


def _trend_direction(bars: list[dict], n: int) -> int:
    """Return +1 if last n bars trend up, -1 if down, 0 if neutral."""
    closes = [b["c"] for b in bars[-n:]]
    if len(closes) < n:
        return 0
    ups = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    downs = (n - 1) - ups
    if ups >= round(n * 0.7):
        return 1
    if downs >= round(n * 0.7):
        return -1
    return 0


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
        last = sb[-1]
        cur = last["c"]
        if cur <= 0:
            continue

        avg_vol = sum(b["v"] for b in sb[-(VOL_AVG_PERIOD + 1):-1]) / VOL_AVG_PERIOD
        if avg_vol <= 0:
            continue
        vol_ratio = last["v"] / avg_vol
        if vol_ratio < VOL_SPIKE_MULT:
            continue

        bar_range = last["h"] - last["l"]
        if bar_range <= 0:
            continue
        body = abs(last["c"] - last["o"])
        body_pct = body / bar_range
        if body_pct < BAR_BODY_MIN_PCT:
            continue

        bar_bull = last["c"] >= last["o"]
        trend = _trend_direction(sb[:-1], TREND_BARS)
        if trend == 0 or (bar_bull and trend < 0) or (not bar_bull and trend > 0):
            continue

        side = "buy" if bar_bull else "sell"
        conf = round(min(0.85, 0.52 + (vol_ratio - VOL_SPIKE_MULT) * 0.02 + body_pct * 0.15), 3)
        signals.append(Signal(
            symbol=symbol, side=side, confidence=conf, size_hint=min(1.0, conf),
            reason=f"VOL_SPIKE_CONT {side.upper()}: {vol_ratio:.1f}x avg vol, "
                   f"{body_pct:.0%} body, trend aligned",
            strategy=STRATEGY_NAME,
        ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Volume Spike Continuation"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    last = symbol_bars[-1]
    avg_vol = sum(b["v"] for b in symbol_bars[-(VOL_AVG_PERIOD + 1):-1]) / VOL_AVG_PERIOD
    vol_ratio = last["v"] / avg_vol if avg_vol > 0 else 0
    bar_range = last["h"] - last["l"]
    body_pct = abs(last["c"] - last["o"]) / bar_range if bar_range > 0 else 0
    bar_bull = last["c"] >= last["o"]
    trend = _trend_direction(symbol_bars[:-1], TREND_BARS)
    vol_ok = vol_ratio >= VOL_SPIKE_MULT
    body_ok = body_pct >= BAR_BODY_MIN_PCT
    trend_ok = trend != 0 and ((bar_bull and trend > 0) or (not bar_bull and trend < 0))
    fired = vol_ok and body_ok and trend_ok
    conf = round(min(0.85, 0.52 + (vol_ratio - VOL_SPIKE_MULT) * 0.02 + body_pct * 0.15), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if (fired and bar_bull) else ("sell" if fired else None),
        "score": conf,
        "summary": (
            f"Vol spike {'continuation' if fired else 'not confirmed'}: "
            f"{vol_ratio:.1f}x vol, {body_pct:.0%} body, trend {'aligned' if trend_ok else 'misaligned'}"
        ),
        "conditions": [
            {"name": "Volume spike", "current_value": round(vol_ratio, 2), "operator": ">=",
             "required_value": VOL_SPIKE_MULT, "unit": "x", "passed": vol_ok, "to_pass": ""},
            {"name": "Body strength", "current_value": round(body_pct, 3), "operator": ">=",
             "required_value": BAR_BODY_MIN_PCT, "unit": "%", "passed": body_ok, "to_pass": ""},
            {"name": "Trend aligned", "current_value": trend, "operator": "aligned",
             "required_value": 1, "unit": "", "passed": trend_ok, "to_pass": ""},
        ],
    }
