"""
Crypto Mean Reversion — S5: Keltner Channel Extreme (5m)

Keltner Channel uses ATR-based bands (less sensitive to spikes than Bollinger).
When price closes outside the Keltner(20, 2.5 ATR) channel, it indicates
sustained volatility expansion — which in ranging markets typically reverts.

Entry: close outside Keltner(20, 2.5) → fade the direction
Target: return to midline (EMA-20). Stop: 2%.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_keltner_outside_band"

EMA_PERIOD = 20
ATR_PERIOD = 14
ATR_MULT = 2.5
MIN_BARS = max(EMA_PERIOD, ATR_PERIOD) + 3

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


def _atr(bars: list[dict], period: int) -> float:
    trs = []
    for i in range(1, len(bars)):
        high = bars[i]["h"]
        low  = bars[i]["l"]
        prev_close = bars[i - 1]["c"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if not trs:
        return 0.0
    window = trs[-period:]
    return sum(window) / len(window)


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
        mid = _ema(closes, EMA_PERIOD)
        atr = _atr(sb, ATR_PERIOD)
        if mid <= 0 or atr <= 0:
            continue
        upper = mid + ATR_MULT * atr
        lower = mid - ATR_MULT * atr

        if cur > upper:
            excess = (cur - upper) / atr
            conf = round(min(0.83, 0.52 + excess * 0.06), 3)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MR_KELTNER short: close {cur:.4f} > upper Keltner {upper:.4f} "
                       f"({excess:.2f}x ATR excess), fade to EMA {mid:.4f}",
                strategy=STRATEGY_NAME,
            ))
        elif cur < lower:
            excess = (lower - cur) / atr
            conf = round(min(0.83, 0.52 + excess * 0.06), 3)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MR_KELTNER long: close {cur:.4f} < lower Keltner {lower:.4f} "
                       f"({excess:.2f}x ATR excess), fade to EMA {mid:.4f}",
                strategy=STRATEGY_NAME,
            ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Keltner Outside Band"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes = [b["c"] for b in symbol_bars]
    cur = closes[-1]
    mid = _ema(closes, EMA_PERIOD)
    atr = _atr(symbol_bars, ATR_PERIOD)
    upper = mid + ATR_MULT * atr
    lower = mid - ATR_MULT * atr
    fired_short = cur > upper
    fired_long  = cur < lower
    fired = fired_short or fired_long
    excess = (cur - upper) / atr if fired_short else ((lower - cur) / atr if fired_long else 0)
    score = round(min(0.83, 0.52 + excess * 0.06), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "sell" if fired_short else ("buy" if fired_long else None),
        "score": score,
        "summary": (
            f"Keltner extreme {'short' if fired_short else 'long'} — {excess:.2f}x ATR outside band"
            if fired else
            f"Inside Keltner [{lower:.4f}–{upper:.4f}] (ATR={atr:.4f})"
        ),
        "conditions": [
            {"name": f"Keltner(EMA-{EMA_PERIOD}, {ATR_MULT}×ATR) band",
             "current_value": round(cur, 4), "operator": "outside_band",
             "required_value": [round(lower, 4), round(upper, 4)],
             "unit": "", "passed": fired, "to_pass": ""},
        ],
    }
