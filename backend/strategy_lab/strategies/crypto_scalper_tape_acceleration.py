"""
Crypto Quant Scalper — S3: Tape Acceleration (1m)

Detects when volume is accelerating alongside price momentum — a sign that
a short-term move is gaining traction rather than fading.

Conditions:
  1. Last 3 bars all close in the same direction (all > open for long, all < open for short)
  2. Each consecutive bar has higher volume than the prior (volume acceleration)
  3. The 3-bar price move exceeds MIN_MOVE_BPS

When tape accelerates, scalp in the direction of acceleration.
Target: 1% (profile take_profit). Stop: 0.5%.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_scalper_tape_acceleration"

LOOKBACK = 3
MIN_MOVE_BPS = 8    # 8bps minimum 3-bar move to qualify
MIN_BARS = LOOKBACK + 1

UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "AVAX/USD"]


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
        cur = window[-1]["c"]
        start = window[0]["o"]
        if cur <= 0 or start <= 0:
            continue

        # Direction consistency
        all_bull = all(b["c"] > b["o"] for b in window)
        all_bear = all(b["c"] < b["o"] for b in window)
        if not (all_bull or all_bear):
            continue

        # Volume acceleration
        vols = [b["v"] for b in window]
        vol_accel = all(vols[i] > vols[i - 1] for i in range(1, LOOKBACK))
        if not vol_accel:
            continue

        move_bps = abs(cur - start) / start * 10_000
        if move_bps < MIN_MOVE_BPS:
            continue

        final_vol = vols[-1]
        first_vol = vols[0]
        accel_ratio = final_vol / first_vol if first_vol > 0 else 1.0
        conf = round(min(0.83, 0.50 + move_bps * 0.003 + min(accel_ratio - 1.0, 1.0) * 0.06), 3)
        side = "buy" if all_bull else "sell"
        signals.append(Signal(
            symbol=symbol, side=side, confidence=conf, size_hint=min(1.0, conf),
            reason=f"TAPE_ACCEL {side.upper()}: 3 consecutive {'bull' if all_bull else 'bear'} bars "
                   f"with vol accel {accel_ratio:.1f}x, move {move_bps:.1f}bps",
            strategy=STRATEGY_NAME,
        ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Tape Acceleration"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    window = symbol_bars[-LOOKBACK:]
    all_bull = all(b["c"] > b["o"] for b in window)
    all_bear = all(b["c"] < b["o"] for b in window)
    vols = [b["v"] for b in window]
    vol_accel = all(vols[i] > vols[i - 1] for i in range(1, LOOKBACK))
    cur = window[-1]["c"]
    start = window[0]["o"]
    move_bps = abs(cur - start) / start * 10_000 if start > 0 else 0
    fired = (all_bull or all_bear) and vol_accel and move_bps >= MIN_MOVE_BPS
    accel_ratio = vols[-1] / vols[0] if vols[0] > 0 else 1.0
    score = round(min(0.83, 0.50 + move_bps * 0.003 + min(accel_ratio - 1.0, 1.0) * 0.06), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if (fired and all_bull) else ("sell" if fired else None),
        "score": score,
        "summary": (
            f"Tape accelerating {'up' if all_bull else 'down'} — {move_bps:.1f}bps, vol {accel_ratio:.1f}x"
            if fired else
            f"No clean acceleration — dir={'bull' if all_bull else 'bear' if all_bear else 'mixed'}, "
            f"vol_accel={vol_accel}, move={move_bps:.1f}bps"
        ),
        "conditions": [],
    }
