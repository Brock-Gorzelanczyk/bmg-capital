"""Iron Condor 45 DTE — sell OTM put spread + OTM call spread for net credit.

Entry conditions (all required):
  1. Market IVR proxy (vol_pctile from regime) >= 40 — IV must be elevated
  2. Per-symbol realized vol pctile >= 35 — symbol-level IV elevated
  3. 20-day price range < 12% of spot — market is range-bound (not trending)
  4. Regime trend is neutral/chop — skip bull or bear trending regimes
  5. VIX between 13 and 35 — below 13 = not enough premium; above 35 = wing risk too high
  6. Not panic VIX regime

Reference: Tastytrade mechanics — 16-delta short strikes, 5-wide wings, target 1/3 credit.
Profit target: 50% of max credit (close at 21 DTE). Max loss: spread width minus credit.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import realized_vol_pctile, range_pct

logger = logging.getLogger(__name__)
STRATEGY_NAME = "iron_condor_45dte"

# Thresholds
MARKET_IVR_MIN  = 10    # 2026-07-01 Brock aggressive: 40 → 10
SYMBOL_IVR_MIN  = 10    # 35 → 10
MAX_RANGE_PCT   = 0.25  # 0.12 → 0.25 — tolerate wider intra-month range
VIX_MIN         = 10.0  # 13 → 10 (sell condors even in low IV)
VIX_MAX         = 40.0  # 35 → 40
BASE_SIZE       = 0.05


def _entry_conditions(
    symbol: str,
    closes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    """
    Returns (should_enter, confidence, reason_json).
    """
    vix_regime   = regime.get("vix_regime", "mid")
    trend_regime = regime.get("trend_regime", "chop")
    vol_pctile   = regime.get("vol_pctile") or 50.0
    vix_value    = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if trend_regime in ("bull", "bear"):
        return False, 0.0, ""
    if vix_value is not None and (vix_value < VIX_MIN or vix_value > VIX_MAX):
        return False, 0.0, ""
    if vol_pctile < MARKET_IVR_MIN:
        logger.debug("[iron_condor] %s: market IVR proxy=%.0f < %d — skip", symbol, vol_pctile, MARKET_IVR_MIN)
        return False, 0.0, ""

    sym_ivr = realized_vol_pctile(closes)
    if sym_ivr is None or sym_ivr < SYMBOL_IVR_MIN:
        logger.debug("[iron_condor] %s: symbol IVR proxy=%s — skip", symbol, sym_ivr)
        return False, 0.0, ""

    rng = range_pct(closes, lookback=20)
    if rng is None or rng > MAX_RANGE_PCT:
        logger.debug("[iron_condor] %s: 20d range=%.2f%% > %.0f%% — directional, skip",
                     symbol, (rng or 0) * 100, MAX_RANGE_PCT * 100)
        return False, 0.0, ""

    spot = closes[-1]
    # Confidence: base + bonus for higher IVR + bonus for tighter range
    ivr_bonus  = min(0.15, (sym_ivr - SYMBOL_IVR_MIN) / 200.0)
    range_bonus = min(0.10, (MAX_RANGE_PCT - rng) / MAX_RANGE_PCT * 0.10)
    confidence  = round(min(0.88, 0.63 + ivr_bonus + range_bonus), 4)

    reason = json.dumps({
        "setup":       "iron_condor_45dte",
        "spot":        round(spot, 2),
        "sym_ivr":     round(sym_ivr, 1),
        "mkt_ivr":     round(vol_pctile, 1),
        "range_20d":   round(rng * 100, 1),
        "vix":         round(vix_value, 1) if vix_value else None,
        "trend":       trend_regime,
        "strikes":     "16-delta short, 5-wide wings, 45 DTE",
        "manage":      "close at 50% credit or 21 DTE, stop at 2x credit",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < 22:
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
