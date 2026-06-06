"""
Chaikin Money Flow (CMF) — volume-weighted accumulation/distribution.
Long when CMF crosses above +0.15 (institutional buying).
Exit/short when CMF crosses below -0.15 (distribution).
Period: 20 bars.
"""
from __future__ import annotations
from strategy_lab.core.signals import Signal

STRATEGY_NAME = "chaikin_money_flow"
PERIOD = 20
BUY_THRESHOLD  =  0.15
SELL_THRESHOLD = -0.15


def _cmf(high: list[float], low: list[float], close: list[float],
         volume: list[float], period: int) -> float:
    if len(close) < period:
        return 0.0
    mfv_sum = 0.0
    vol_sum = 0.0
    for i in range(-period, 0):
        hl = high[i] - low[i]
        mfm = 0.0 if hl == 0 else ((close[i] - low[i]) - (high[i] - close[i])) / hl
        mfv_sum += mfm * volume[i]
        vol_sum += volume[i]
    return mfv_sum / vol_sum if vol_sum else 0.0


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> list[Signal]:
    signals = []
    universe = profile_config.get("universe", {}).get("symbols", [])

    for symbol in universe:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < PERIOD + 2:
            continue

        highs   = [b["h"] for b in symbol_bars]
        lows    = [b["l"] for b in symbol_bars]
        closes  = [b["c"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]

        cmf_now  = _cmf(highs, lows, closes, volumes, PERIOD)
        cmf_prev = _cmf(highs[:-1], lows[:-1], closes[:-1], volumes[:-1], PERIOD)

        if cmf_now >= BUY_THRESHOLD and cmf_prev < BUY_THRESHOLD:
            confidence = min(0.80, 0.60 + cmf_now * 0.5)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=0.08,
                reason=(f"CMF crossed above {BUY_THRESHOLD} (now {cmf_now:.3f}). "
                        f"Institutional accumulation detected over {PERIOD} bars."),
                strategy=STRATEGY_NAME,
            ))

        elif cmf_now <= SELL_THRESHOLD and cmf_prev > SELL_THRESHOLD:
            confidence = min(0.76, 0.58 + abs(cmf_now) * 0.5)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=round(confidence, 3),
                size_hint=0.05,
                reason=(f"CMF crossed below {SELL_THRESHOLD} (now {cmf_now:.3f}). "
                        f"Distribution phase — reduce exposure."),
                strategy=STRATEGY_NAME,
            ))

    return signals
