"""0DTE Iron Condor — short-strangle with wings expiring same day.

Designed for SPY/QQQ/SPX proxies on Fridays only.
0DTE condors need tight range-bound action: skip if overnight gap > 0.5%
or if the market is trending. Best in VIX 14-25 range.

Entry conditions (all required):
  1. Friday only (0DTE expires today)
  2. Symbol is SPY or QQQ (highest 0DTE liquidity)
  3. VIX between 14 and 26 — enough premium, not crisis
  4. Overnight gap < 0.5% (market not committed to direction)
  5. 5-day range < 8% (range-bound week)
  6. Not bear trending, not panic

Risk: max loss = spread width minus credit. Size tiny — 0DTE gamma risk is extreme.
Reference: Tastytrade Friday 0DTE research (Sosnoff et al.).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import range_pct

logger = logging.getLogger(__name__)
STRATEGY_NAME = "zero_dte_iron_condor"

ELIGIBLE_SYMBOLS = {"SPY", "QQQ"}
VIX_MIN          = 14.0
VIX_MAX          = 26.0
MAX_GAP_PCT      = 0.005   # 0.5% overnight gap
MAX_RANGE_5D     = 0.08    # 8% weekly range
BASE_SIZE        = 0.03    # 3% — tiny due to gamma risk


def _is_friday() -> bool:
    try:
        import pytz
        ET = pytz.timezone("America/New_York")
        return datetime.now(ET).weekday() == 4  # 4 = Friday
    except Exception:
        return datetime.now(timezone.utc).weekday() == 4


def _entry_conditions(
    symbol: str,
    closes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    if symbol not in ELIGIBLE_SYMBOLS:
        return False, 0.0, ""
    if not _is_friday():
        return False, 0.0, ""

    vix_regime   = regime.get("vix_regime", "mid")
    trend_regime = regime.get("trend_regime", "chop")
    vix_value    = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if trend_regime == "bear":
        return False, 0.0, ""
    if vix_value is None or not (VIX_MIN <= vix_value <= VIX_MAX):
        return False, 0.0, ""

    if len(closes) < 6:
        return False, 0.0, ""

    # Overnight gap: compare today's open-like proxy (last close vs prior close)
    gap = abs(closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 1.0
    if gap > MAX_GAP_PCT:
        logger.debug("[0dte_ic] %s: overnight gap=%.2f%% > 0.5%% — skip", symbol, gap * 100)
        return False, 0.0, ""

    rng_5d = range_pct(closes, lookback=5)
    if rng_5d is None or rng_5d > MAX_RANGE_5D:
        logger.debug("[0dte_ic] %s: 5d range=%.1f%% — too wide for 0DTE", symbol, (rng_5d or 0) * 100)
        return False, 0.0, ""

    spot = closes[-1]
    # Tighter range = better 0DTE entry (less theta risk from unexpected move)
    range_bonus = min(0.10, (MAX_RANGE_5D - rng_5d) / MAX_RANGE_5D * 0.10)
    confidence  = round(min(0.80, 0.60 + range_bonus), 4)

    reason = json.dumps({
        "setup":      "zero_dte_iron_condor",
        "spot":       round(spot, 2),
        "gap_pct":    round(gap * 100, 2),
        "range_5d":   round(rng_5d * 100, 1),
        "vix":        round(vix_value, 1),
        "trend":      trend_regime,
        "strikes":    "10-15 delta short, 5-wide wings, 0 DTE (Friday)",
        "manage":     "close at 50% credit by 3 PM ET; allow full expire if < 10% credit",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < 6:
            continue
        enter, conf, reason = _entry_conditions(symbol, closes, regime)
        if not enter:
            continue
        out.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=conf,
            size_hint=BASE_SIZE,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    regime = kwargs.get("regime", {})
    enter, conf, reason = _entry_conditions(symbol, closes, regime)
    if not enter:
        return None
    return Signal(symbol=symbol, side="buy", confidence=conf,
                  size_hint=BASE_SIZE, reason=reason, strategy=STRATEGY_NAME)
