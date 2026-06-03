"""VPA no-supply: narrow range + low volume in uptrend = buyers in control."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "vpa_no_supply_demand"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float],
    lows: list[float], volumes: list[float]
) -> List[Signal]:
    """Core logic: Anna Coulling no-supply bar in uptrend."""
    if len(closes) < 10 or len(highs) < 10 or len(lows) < 10 or len(volumes) < 10:
        return []
    is_uptrend = (closes[-1] > mean(closes[-20:]) if len(closes) >= 20
                  else closes[-1] > closes[-5])
    avg_range = mean([highs[i] - lows[i] for i in range(-10, -1)])
    narrow_range = (highs[-1] - lows[-1]) < avg_range * 0.7
    avg_vol = mean(volumes[-10:-1])
    low_vol = volumes[-1] < avg_vol * 0.8
    if is_uptrend and narrow_range and low_vol:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason="VPA no-supply: narrow range + low volume in uptrend",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        highs = [float(b.get("h", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs, lows, volumes))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None,
    lows: list[float] = None, volumes: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs or not lows or not volumes:
        return None
    sigs = _v1_signals(symbol, closes, highs, lows, volumes)
    return sigs[0] if sigs else None
