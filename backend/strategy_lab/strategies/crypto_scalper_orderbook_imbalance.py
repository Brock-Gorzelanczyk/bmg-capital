"""
Crypto Quant Scalper — S2: Orderbook Imbalance (1m bars proxy)

Without real L2 orderbook data, estimates buy/sell pressure from 1m bar
internals: (close − open) / (high − low) × volume = signed bar delta.

Sustained imbalance over N bars: if last 6 bars all show positive delta
AND cumulative delta > threshold × total volume → momentum continuation long.
Same logic inverted for short.

This approximates the "orderbook imbalance" signal used by HFT desks without
requiring direct order flow data.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_scalper_orderbook_imbalance"

LOOKBACK = 6           # bars of sustained imbalance required
IMBALANCE_THRESH = 0.35  # 35% of total volume on one side
REQUIRE_ALL_SAME = 4   # at least 4/6 bars must agree on direction

UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "AVAX/USD"]
MIN_BARS = LOOKBACK + 2


def _bar_delta(b: dict) -> float:
    body = b["c"] - b["o"]
    range_ = max(b["h"] - b["l"], b["c"] * 1e-6)
    return (body / range_) * b["v"]


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
        window = sb[-LOOKBACK:]
        deltas = [_bar_delta(b) for b in window]
        total_vol = sum(b["v"] for b in window)
        cum_delta = sum(deltas)
        cur = sb[-1]["c"]
        if cur <= 0 or total_vol <= 0:
            continue

        imbalance = cum_delta / total_vol
        bull_bars = sum(1 for d in deltas if d > 0)
        bear_bars = LOOKBACK - bull_bars

        if imbalance > IMBALANCE_THRESH and bull_bars >= REQUIRE_ALL_SAME:
            conf = round(min(0.82, 0.48 + (imbalance - IMBALANCE_THRESH) * 1.5
                             + (bull_bars - REQUIRE_ALL_SAME) * 0.03), 3)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
                reason=f"OB_IMBALANCE long: {imbalance:+.3f} ratio, {bull_bars}/{LOOKBACK} bull bars at ${cur:.4f}",
                strategy=STRATEGY_NAME,
            ))
        elif imbalance < -IMBALANCE_THRESH and bear_bars >= REQUIRE_ALL_SAME:
            conf = round(min(0.82, 0.48 + (abs(imbalance) - IMBALANCE_THRESH) * 1.5
                             + (bear_bars - REQUIRE_ALL_SAME) * 0.03), 3)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
                reason=f"OB_IMBALANCE short: {imbalance:+.3f} ratio, {bear_bars}/{LOOKBACK} bear bars at ${cur:.4f}",
                strategy=STRATEGY_NAME,
            ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Orderbook Imbalance"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    window = symbol_bars[-LOOKBACK:]
    deltas = [_bar_delta(b) for b in window]
    total_vol = sum(b["v"] for b in window)
    cum_delta = sum(deltas)
    imbalance = cum_delta / total_vol if total_vol > 0 else 0.0
    bull_bars = sum(1 for d in deltas if d > 0)
    fired_long  = imbalance > IMBALANCE_THRESH and bull_bars >= REQUIRE_ALL_SAME
    fired_short = imbalance < -IMBALANCE_THRESH and (LOOKBACK - bull_bars) >= REQUIRE_ALL_SAME
    fired = fired_long or fired_short
    score = round(min(0.82, 0.48 + max(0, abs(imbalance) - IMBALANCE_THRESH) * 1.5), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if fired_long else ("sell" if fired_short else None),
        "score": score,
        "summary": f"Imbalance {imbalance:+.3f}, {bull_bars}/{LOOKBACK} bull bars — {'FIRED' if fired else 'waiting'}",
        "conditions": [
            {"name": "Cumulative delta ratio", "current_value": round(imbalance, 4),
             "operator": f">= {IMBALANCE_THRESH} or <= -{IMBALANCE_THRESH}", "required_value": IMBALANCE_THRESH,
             "unit": "", "passed": abs(imbalance) >= IMBALANCE_THRESH, "to_pass": ""},
        ],
    }
