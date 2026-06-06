"""
Ultimate Oscillator — Larry Williams' multi-period momentum oscillator.
Combines 7, 14, and 28 period buying pressure / true range ratios.
Long when UO crosses above 30 from oversold; exit when UO > 70 (overbought).
Short/reduce when UO crosses below 70 from overbought.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "ultimate_oscillator"
PERIOD1 = 7
PERIOD2 = 14
PERIOD3 = 28
OVERSOLD   = 30
OVERBOUGHT = 70


def _true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _buying_pressure(close: float, low: float, prev_close: float) -> float:
    return close - min(low, prev_close)


def _uo_period_avg(
    highs: list[float], lows: list[float], closes: list[float],
    period: int,
) -> float:
    bp_sum = 0.0
    tr_sum = 0.0
    for i in range(-period, 0):
        pc = closes[i - 1]
        bp_sum += _buying_pressure(closes[i], lows[i], pc)
        tr_sum += _true_range(highs[i], lows[i], pc)
    return bp_sum / tr_sum if tr_sum else 0.5


def _uo(highs: list[float], lows: list[float], closes: list[float]) -> float:
    needed = PERIOD3 + 1
    if len(closes) < needed:
        return 50.0
    avg7  = _uo_period_avg(highs, lows, closes, PERIOD1)
    avg14 = _uo_period_avg(highs, lows, closes, PERIOD2)
    avg28 = _uo_period_avg(highs, lows, closes, PERIOD3)
    raw = (4 * avg7 + 2 * avg14 + avg28) / 7
    return raw * 100


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    signals = []
    universe = profile_config.get("universe", {}).get("symbols", [])

    for symbol in universe:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < PERIOD3 + 2:
            continue

        highs  = [b["h"] for b in symbol_bars]
        lows   = [b["l"] for b in symbol_bars]
        closes = [b["c"] for b in symbol_bars]

        uo_now  = _uo(highs, lows, closes)
        uo_prev = _uo(highs[:-1], lows[:-1], closes[:-1])

        if uo_now > OVERSOLD and uo_prev <= OVERSOLD:
            confidence = min(0.79, 0.58 + (uo_now - OVERSOLD) / 100)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=0.07,
                reason=(f"Ultimate Oscillator crossed above {OVERSOLD} (now {uo_now:.1f}). "
                        f"Multi-timeframe momentum turn confirmed by 7/14/28-period BPs."),
                strategy=STRATEGY_NAME,
            ))

        elif uo_now < OVERBOUGHT and uo_prev >= OVERBOUGHT:
            confidence = min(0.75, 0.55 + (OVERBOUGHT - uo_now) / 100)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=round(confidence, 3),
                size_hint=0.05,
                reason=(f"Ultimate Oscillator crossed below {OVERBOUGHT} (now {uo_now:.1f}). "
                        f"Overbought exhaustion across all three timeframes."),
                strategy=STRATEGY_NAME,
            ))

    return signals
