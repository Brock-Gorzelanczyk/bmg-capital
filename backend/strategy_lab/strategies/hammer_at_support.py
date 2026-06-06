"""
Hammer at Support — candlestick pattern + S/R confluence.
Fires when a hammer or inverted hammer forms within 1% of a 20-bar support level.
Hammer defined as: lower shadow >= 2× body, body in upper third of range.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "hammer_at_support"
LOOKBACK = 20
SUPPORT_PROXIMITY_PCT = 0.01   # within 1% of support counts as "at support"
SHADOW_RATIO = 2.0             # lower shadow must be >= 2× body


def _is_hammer(o: float, h: float, l: float, c: float) -> bool:
    body   = abs(c - o)
    lo_shadow = min(o, c) - l
    hi_shadow = h - max(o, c)
    if body == 0:
        return False
    return lo_shadow >= SHADOW_RATIO * body and hi_shadow <= 0.5 * body and c > o


def _support_level(lows: list[float], lookback: int) -> float:
    return min(lows[-lookback:])


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    signals = []
    universe = profile_config.get("universe", {}).get("symbols", [])

    for symbol in universe:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < LOOKBACK + 1:
            continue

        last = symbol_bars[-1]
        o, h, l, c = last["o"], last["h"], last["l"], last["c"]

        lows    = [b["l"] for b in symbol_bars]
        support = _support_level(lows[:-1], LOOKBACK)
        near_support = abs(c - support) / support <= SUPPORT_PROXIMITY_PCT if support else False

        if _is_hammer(o, h, l, c) and near_support:
            lo_shadow = min(o, c) - l
            body      = abs(c - o)
            confidence = min(0.81, 0.60 + (lo_shadow / body - 2) * 0.05)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=0.07,
                reason=(f"Hammer candle (shadow/body {lo_shadow/body:.1f}×) within "
                        f"{abs(c - support)/support*100:.2f}% of {LOOKBACK}-bar support ${support:.2f}. "
                        f"Bullish reversal at structural low."),
                strategy=STRATEGY_NAME,
            ))

    return signals
