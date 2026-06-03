"""Post-Earnings Announcement Drift (PEAD) proxy strategy."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "earnings_drift_post"

GAP_THRESHOLD = 0.03   # 3% overnight gap
VOL_SURGE_MIN = 2.0    # 2x average volume


def _v1_signals(
    symbol: str,
    closes: list[float],
    volumes: list[float],
    opens: list[float],
) -> List[Signal]:
    """Return buy on earnings gap + volume surge proxy for PEAD.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 5.
        volumes: Volume values, most-recent last.
        opens: Open prices, most-recent last.
    """
    if len(closes) < 5 or len(volumes) < 6 or len(opens) < 1:
        return []

    overnight_gap = (opens[-1] - closes[-2]) / closes[-2] if closes[-2] != 0 else 0.0
    avg_vol_5d = sum(volumes[-6:-1]) / 5 if sum(volumes[-6:-1]) > 0 else 0.0
    vol_surge = volumes[-1] / avg_vol_5d if avg_vol_5d > 0 else 0.0

    if overnight_gap > GAP_THRESHOLD and vol_surge > VOL_SURGE_MIN:
        confidence = max(0.4, min(0.85, overnight_gap * 10 + (vol_surge - 2.0) * 0.1))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"PEAD proxy: gap +{overnight_gap*100:.1f}%, "
                f"vol surge {vol_surge:.1f}x (time-based exit 5-15d)"
            ),
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        volumes = [float(b.get("v", 0)) for b in bar_list]
        opens = [float(b.get("o", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, volumes, opens))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    volumes: list[float],
    opens: list[float],
) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, volumes, opens)
    return signals[0] if signals else None
