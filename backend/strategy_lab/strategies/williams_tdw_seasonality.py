"""Williams day-of-week seasonality: buy Mon/Tue, sell Thu/Fri."""
from __future__ import annotations
import datetime
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "williams_tdw_seasonality"


def _v1_signals(
    symbol: str, closes: list[float], timestamps: list
) -> List[Signal]:
    """Core logic: day-of-week seasonality."""
    if not closes or not timestamps:
        return []
    ts = timestamps[-1]
    if isinstance(ts, (int, float)):
        dt = datetime.datetime.utcfromtimestamp(ts)
    elif isinstance(ts, str):
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except Exception:
            return []
    elif isinstance(ts, datetime.datetime):
        dt = ts
    else:
        return []
    weekday = dt.weekday()  # 0=Mon, 4=Fri
    if weekday <= 1:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.55,
            size_hint=0.55,
            reason=f"Williams TDW: Mon/Tue seasonality buy (weekday={weekday})",
            strategy=STRATEGY_NAME,
        )]
    if weekday >= 3:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.52,
            size_hint=0.52,
            reason=f"Williams TDW: Thu/Fri seasonality sell (weekday={weekday})",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        timestamps = [b.get("t") for b in bar_list]
        out.extend(_v1_signals(symbol, closes, timestamps))
    return out


def generate_signal(
    symbol: str, closes: list[float], timestamps: list = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not timestamps:
        return None
    sigs = _v1_signals(symbol, closes, timestamps)
    return sigs[0] if sigs else None
