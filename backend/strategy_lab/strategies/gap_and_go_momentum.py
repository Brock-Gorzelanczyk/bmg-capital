"""Gap and go momentum: gap up >3% with volume surge, holding above open."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "gap_and_go_momentum"


def _v1_signals(
    symbol: str, closes: list[float], opens: list[float], volumes: list[float]
) -> List[Signal]:
    """Core logic: gap up on volume, close holding above open."""
    if len(closes) < 2 or len(opens) < 1:
        return []
    gap_pct = (opens[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
    holding_gap = closes[-1] > opens[-1] * 0.99
    if len(volumes) > 6:
        recent_vols = volumes[-6:-1]
        vol_avg = mean(recent_vols) if recent_vols else 1
        vol_conf = volumes[-1] > vol_avg * 1.5
    else:
        vol_conf = True
    if gap_pct > 0.03 and holding_gap and vol_conf:
        conf = min(0.85, 0.55 + gap_pct * 5)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Gap and go: gap={gap_pct:.2%}, holding above open",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        opens = [float(b.get("o", 0)) for b in bar_list]
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, opens, volumes))
    return out


def generate_signal(
    symbol: str, closes: list[float], opens: list[float] = None,
    volumes: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not opens:
        return None
    sigs = _v1_signals(symbol, closes, opens, volumes or [])
    return sigs[0] if sigs else None
