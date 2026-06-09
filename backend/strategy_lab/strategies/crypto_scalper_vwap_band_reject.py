"""
Crypto Quant Scalper — S4: VWAP Band Reject (1m)

Price approaches the 1σ VWAP band and gets rejected (wick + close back inside).

Entry: price wick exceeded 1σ band but CLOSED back inside (rejection candle).
  - Upper band wick → short (buyers exhausted)
  - Lower band wick → long  (sellers exhausted)

This is a scalp-grade fade — take 1% quickly after the rejection.
Uses 1m bars so the rejection signal is fresh (within 1 minute of exhaustion).
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_scalper_vwap_band_reject"

VWAP_LOOKBACK = 60    # 60 × 1m = 1 hour session VWAP
SIGMA_BAND = 1.0      # 1σ rejection (tighter than vwap_fade's 1.5σ)
MIN_WICK_BPS = 4      # wick must exceed band by at least 4bps
MIN_BARS = VWAP_LOOKBACK + 2

UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "AVAX/USD"]


def _vwap_sigma(bars: list[dict], lookback: int) -> tuple[float, float]:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for b in window:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        cum_tp_vol += tp * b["v"]
        cum_vol += b["v"]
    if cum_vol <= 0:
        return 0.0, 0.0
    vwap = cum_tp_vol / cum_vol
    sq_sum = sum(((b["h"] + b["l"] + b["c"]) / 3.0 - vwap) ** 2 for b in window)
    sigma = math.sqrt(sq_sum / len(window))
    return vwap, sigma


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
        vwap, sigma = _vwap_sigma(sb, VWAP_LOOKBACK)
        if vwap <= 0 or sigma <= 0:
            continue
        upper = vwap + SIGMA_BAND * sigma
        lower = vwap - SIGMA_BAND * sigma
        bar = sb[-1]
        close_ = bar["c"]
        high_  = bar["h"]
        low_   = bar["l"]
        if close_ <= 0:
            continue

        # Upper band wick rejection → short
        wick_up = (high_ - upper) / upper * 10_000 if high_ > upper else 0
        if high_ > upper and close_ < upper and wick_up >= MIN_WICK_BPS:
            conf = round(min(0.80, 0.50 + wick_up * 0.005), 3)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
                reason=f"VWAP_REJECT short: wick {wick_up:.1f}bps past upper band {upper:.4f}, "
                       f"closed back at {close_:.4f}",
                strategy=STRATEGY_NAME,
            ))
        # Lower band wick rejection → long
        wick_dn = (lower - low_) / lower * 10_000 if low_ < lower else 0
        if low_ < lower and close_ > lower and wick_dn >= MIN_WICK_BPS:
            conf = round(min(0.80, 0.50 + wick_dn * 0.005), 3)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
                reason=f"VWAP_REJECT long: wick {wick_dn:.1f}bps below lower band {lower:.4f}, "
                       f"closed back at {close_:.4f}",
                strategy=STRATEGY_NAME,
            ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "VWAP Band Reject"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    vwap, sigma = _vwap_sigma(symbol_bars, VWAP_LOOKBACK)
    upper = vwap + SIGMA_BAND * sigma
    lower = vwap - SIGMA_BAND * sigma
    bar = symbol_bars[-1]
    wick_up = (bar["h"] - upper) / upper * 10_000 if bar["h"] > upper else 0
    wick_dn = (lower - bar["l"]) / lower * 10_000 if bar["l"] < lower else 0
    fired_short = bar["h"] > upper and bar["c"] < upper and wick_up >= MIN_WICK_BPS
    fired_long  = bar["l"] < lower and bar["c"] > lower and wick_dn >= MIN_WICK_BPS
    fired = fired_short or fired_long
    score = round(min(0.80, 0.50 + max(wick_up, wick_dn) * 0.005), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "sell" if fired_short else ("buy" if fired_long else None),
        "score": score,
        "summary": (
            f"VWAP rejection {'short' if fired_short else 'long'} — "
            f"wick {max(wick_up, wick_dn):.1f}bps past band"
            if fired else
            f"No wick rejection — VWAP bands: [{lower:.4f}, {upper:.4f}]"
        ),
        "conditions": [],
    }
