"""
Three White Soldiers — classic 3-candle bullish continuation/reversal pattern.
Requires: 3 consecutive bullish candles, each closing near the high,
each opening within the prior candle's body (progressive gapping up).
Fires a buy when preceded by at least 5 bars of prior downtrend.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "three_white_soldiers"
DOWNTREND_BARS = 5
MAX_UPPER_SHADOW_PCT = 0.25   # upper shadow <= 25% of candle range (closes near high)


def _is_bullish_soldier(o: float, h: float, l: float, c: float) -> bool:
    if c <= o:
        return False
    candle_range = h - l
    upper_shadow = h - c
    return candle_range > 0 and upper_shadow / candle_range <= MAX_UPPER_SHADOW_PCT


def _prior_downtrend(bars: list[dict], lookback: int) -> bool:
    if len(bars) < lookback:
        return False
    closes = [b["c"] for b in bars[-lookback:]]
    return closes[-1] < closes[0]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    signals = []
    universe = profile_config.get("universe", {}).get("symbols", [])

    for symbol in universe:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < DOWNTREND_BARS + 3:
            continue

        b1, b2, b3 = symbol_bars[-3], symbol_bars[-2], symbol_bars[-1]

        if not (_is_bullish_soldier(b1["o"], b1["h"], b1["l"], b1["c"]) and
                _is_bullish_soldier(b2["o"], b2["h"], b2["l"], b2["c"]) and
                _is_bullish_soldier(b3["o"], b3["h"], b3["l"], b3["c"])):
            continue

        # Each candle opens within the prior candle's body
        b2_opens_in_b1 = b1["o"] <= b2["o"] <= b1["c"]
        b3_opens_in_b2 = b2["o"] <= b3["o"] <= b2["c"]
        if not (b2_opens_in_b1 and b3_opens_in_b2):
            continue

        # Each candle closes higher than the previous
        if not (b1["c"] < b2["c"] < b3["c"]):
            continue

        if not _prior_downtrend(symbol_bars[:-3], DOWNTREND_BARS):
            continue

        total_gain = (b3["c"] - b1["o"]) / b1["o"] if b1["o"] else 0
        confidence = min(0.84, 0.68 + total_gain * 2)
        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=round(confidence, 3),
            size_hint=0.09,
            reason=(f"Three White Soldiers: 3 consecutive bullish closes "
                    f"(+{total_gain*100:.1f}% total). Each opens in prior body, "
                    f"closes near high. Preceded by {DOWNTREND_BARS}-bar downtrend."),
            strategy=STRATEGY_NAME,
        ))

    return signals
