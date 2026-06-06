"""
Aroon Breakout — trend-inception signal using Aroon Up/Down crossover.
Long when Aroon Up crosses above 70 and Aroon Down falls below 30.
Short/exit when Aroon Down crosses above 70 and Aroon Up falls below 30.
Works on stocks and crypto. Period: 25 bars.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "aroon_breakout"
PERIOD = 25


def _aroon(high: list[float], low: list[float], period: int) -> tuple[float, float]:
    """Return (aroon_up, aroon_down) for the most recent bar."""
    if len(high) < period + 1:
        return 50.0, 50.0
    window_high = high[-(period + 1):]
    window_low  = low[-(period + 1):]
    bars_since_high = period - window_high.index(max(window_high))
    bars_since_low  = period - window_low.index(min(window_low))
    aroon_up   = ((period - bars_since_high) / period) * 100
    aroon_down = ((period - bars_since_low)  / period) * 100
    return aroon_up, aroon_down


def _aroon_prev(high: list[float], low: list[float], period: int) -> tuple[float, float]:
    """Return (aroon_up, aroon_down) for the bar before the last."""
    return _aroon(high[:-1], low[:-1], period)


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    signals = []
    universe = profile_config.get("universe", {}).get("symbols", [])

    for symbol in universe:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < PERIOD + 2:
            continue

        highs  = [b["h"] for b in symbol_bars]
        lows   = [b["l"] for b in symbol_bars]
        closes = [b["c"] for b in symbol_bars]

        up_now,  dn_now  = _aroon(highs, lows, PERIOD)
        up_prev, dn_prev = _aroon_prev(highs, lows, PERIOD)

        # Bullish crossover: Aroon Up crosses 70, Aroon Down below 30
        if up_now >= 70 and dn_now <= 30 and up_prev < 70:
            confidence = min(0.82, 0.62 + (up_now - 70) / 100)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=0.07,
                reason=(f"Aroon Up {up_now:.0f} (crossed 70↑) / Aroon Down {dn_now:.0f}. "
                        f"Trend inception — new {PERIOD}-bar high within 1 bar."),
                strategy=STRATEGY_NAME,
            ))

        # Bearish crossover: Aroon Down crosses 70, Aroon Up below 30
        elif dn_now >= 70 and up_now <= 30 and dn_prev < 70:
            confidence = min(0.78, 0.60 + (dn_now - 70) / 100)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=round(confidence, 3),
                size_hint=0.05,
                reason=(f"Aroon Down {dn_now:.0f} (crossed 70↑) / Aroon Up {up_now:.0f}. "
                        f"Downtrend inception — new {PERIOD}-bar low within 1 bar."),
                strategy=STRATEGY_NAME,
            ))

    return signals
