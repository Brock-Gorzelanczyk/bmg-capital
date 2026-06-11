"""Time-series momentum — Moskowitz, Ooi & Pedersen (2012).

Each asset is evaluated independently: if its own trailing return is
positive, go long; negative, go short.  Uses a 12-month lookback and
sizes by the inverse of realised volatility (risk parity scaling).
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "time_series_momentum"

_LOOKBACK = 252   # ~12 months of daily closes
_VOL_WIN = 60     # realised vol window for position sizing


def _realised_vol(closes: list[float], window: int) -> float:
    """Annualised daily-return std over `window` bars."""
    if len(closes) < window + 1:
        return 0.20  # fallback: 20 % annualised vol
    rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return 0.20
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _tsmom_signal(closes: list[float]) -> tuple[str | None, float, float]:
    """Return (side, confidence, size_hint) for the series."""
    if len(closes) < _LOOKBACK:
        return None, 0.0, 0.0

    ret_12m = (closes[-1] - closes[-_LOOKBACK]) / closes[-_LOOKBACK]
    vol = _realised_vol(closes, _VOL_WIN)

    # Risk-parity size: target 10 % annualised vol per position
    target_vol = 0.10
    raw_size = target_vol / vol if vol > 0 else 0.5
    size = max(0.10, min(0.90, raw_size))

    if ret_12m > 0.02:
        conf = min(0.85, 0.55 + abs(ret_12m) * 0.3)
        return "buy", conf, size
    if ret_12m < -0.02:
        conf = min(0.80, 0.55 + abs(ret_12m) * 0.3)
        return "sell", conf, size * 0.7  # size down on shorts
    return None, 0.0, 0.0


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    vix = regime.get("vix_regime", "mid")
    trend = regime.get("trend_regime", "chop")

    # TSMOM underperforms in panic / whipsaw — reduce confidence
    regime_mult = 0.70 if vix == "panic" or trend == "chop" else 1.0

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        side, conf, size = _tsmom_signal(closes)
        if side is None:
            continue
        ret_12m = (closes[-1] - closes[-_LOOKBACK]) / closes[-_LOOKBACK]
        out.append(Signal(
            symbol=symbol,
            side=side,
            confidence=round(conf * regime_mult, 4),
            size_hint=round(size, 4),
            reason=(
                f"TSMOM 12M ret={ret_12m:.3f} "
                f"vol={_realised_vol(closes, _VOL_WIN):.3f}"
            ),
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    **kwargs,
) -> Optional[Signal]:
    """Backwards-compat shim."""
    side, conf, size = _tsmom_signal(closes)
    if side is None:
        return None
    ret_12m = (closes[-1] - closes[-_LOOKBACK]) / closes[-_LOOKBACK]
    return Signal(
        symbol=symbol,
        side=side,
        confidence=conf,
        size_hint=size,
        reason=f"TSMOM 12M ret={ret_12m:.3f}",
        strategy=STRATEGY_NAME,
    )
