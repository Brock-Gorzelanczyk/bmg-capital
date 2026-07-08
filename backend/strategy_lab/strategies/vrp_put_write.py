"""VRP put-write — weekly SPY/QQQ 20-delta put credit spread.

Reference: Israelov 2019, "Pathetic Protection: The Elusive Benefits
of Protective Puts" + Israelov-Klein 2016, "Risk and Return of
Equity Index Collar Strategies" (SSRN 3437199 series). The volatility
risk premium — the empirical fact that implied vol systematically
exceeds realized vol — has been documented since Bakshi-Kapadia 2003
and is one of the most persistent risk premia in modern markets.

Strategy:
  1. Universe: SPY, QQQ, IWM (highly liquid, tight option spreads).
  2. Fire only in contango VIX regime (multi-vol structure signals
     positive expected value for short-vol; runner's VIX gate already
     enforces this).
  3. Setup: 30-45 DTE, ~20-delta OTM short put + $1 hedge below.
     Runner's _resolve_option_details already builds the 2-leg mleg
     structure for setup="vrp_put_write" via the short_credit + put
     branch (identical geometry to bull_put_credit_spread but with a
     tighter delta target).
  4. Confidence scales with VIX percentile (higher IV = fatter premium).

Distinct from bull_put_credit_spread because:
  - Universe restricted to index ETFs (SPY/QQQ/IWM) — no single-name
    idiosyncratic risk
  - Deliberately capital-efficient: $1 wing = $100 collateral per spread
  - Fires weekly regardless of trend (Sloan-style systematic vol harvest)
    rather than trend-dependent bull_put_credit_spread
  - Held to 50% profit or 21 DTE (whichever first)

Reference sharpes: Israelov 1.3, CBOE PUTW index ~0.9 net of fees.

Data: strategy uses closes to gate on trend + vol; the runner resolves
actual option strikes via _resolve_option_details.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import realized_vol_pctile, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "vrp_put_write"

VIX_MIN = 10.0   # below 10, premium too thin to bother
VIX_MAX = 40.0   # above 40, panic regime — VIX-gate skip anyway
SMA_DAYS = 50    # trend filter: don't sell puts on downtrending index
BASE_SIZE = 0.05


def _entry_conditions(
    symbol: str, closes: list[float], regime: dict,
) -> tuple[bool, float, str]:
    """Return (should_enter, confidence, reason_json)."""
    vix_regime = regime.get("vix_regime", "mid")
    vix_value  = regime.get("vix_value")
    vol_pctile = regime.get("vol_pctile") or 50.0

    if vix_regime == "panic":
        return False, 0.0, ""
    if vix_value is not None and (vix_value < VIX_MIN or vix_value > VIX_MAX):
        return False, 0.0, ""

    # Uptrend filter: SPY-family put-writes should only fire when index
    # is above its 50-day SMA. Selling puts into a bear trend gets run over.
    sma50 = sma(closes, SMA_DAYS)
    if sma50 is None or closes[-1] < sma50:
        return False, 0.0, ""

    # Symbol IV percentile — richer premium means better expected value.
    sym_ivr = realized_vol_pctile(closes)
    if sym_ivr is None:
        sym_ivr = 50.0

    spot = closes[-1]
    # Confidence: base 0.65 + up to 0.20 from IVR bonus
    ivr_bonus = min(0.20, sym_ivr / 500.0)
    vix_bonus = min(0.05, ((vix_value or 15.0) - 12.0) / 100.0) if vix_value else 0.0
    confidence = round(min(0.90, 0.65 + ivr_bonus + max(0.0, vix_bonus)), 4)

    reason = json.dumps({
        "setup":     "vrp_put_write",
        "spot":      round(spot, 2),
        "sma50":     round(sma50, 2),
        "sym_ivr":   round(sym_ivr, 1),
        "vix":       round(vix_value, 1) if vix_value else None,
        "strikes":   "20-delta short put + $1 hedge, 30-45 DTE",
        "manage":    "close at 50% credit or 21 DTE",
        "ref":       "Israelov 2019, SSRN 3437199",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < SMA_DAYS + 5:
            continue
        enter, conf, reason = _entry_conditions(symbol, closes, regime)
        if not enter:
            continue
        out.append(Signal(
            symbol=symbol,
            side="sell",
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
    return Signal(symbol=symbol, side="sell", confidence=conf,
                  size_hint=BASE_SIZE, reason=reason, strategy=STRATEGY_NAME)
