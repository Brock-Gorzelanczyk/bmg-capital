"""
Crypto Mean Reversion — S3: RSI Overbought Short (5m)

RSI(14) > 75 on 5m bars = deeply overbought. Short the fade.

Entry:
  RSI(14) > 75 → sell (mean revert down)
  Confirmation: last close < prior close (rollover beginning)

Target: reversion to RSI ~50 (approx 2.5% down). Stop: 2%.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_rsi_overbought_short"

RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MIN_BARS = RSI_PERIOD + 3

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD",
    "LINK/USD", "DOT/USD", "ADA/USD", "NEAR/USD", "ATOM/USD",
]


def _rsi(closes: list[float], period: int) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d for d in deltas[-period:] if d > 0]
    losses = [abs(d) for d in deltas[-period:] if d < 0]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    # 2026-06-30 regime gate: mean reversion is structurally weak in trending
    # regimes (bull/bear). Trade only in chop or when regime data is unavailable.
    trend = (regime or {}).get("trend_regime", "").lower()
    if trend in ("bull", "bear"):
        return []
    signals: list[Signal] = []
    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", UNIVERSE) if isinstance(universe, dict) else UNIVERSE

    for symbol in symbols:
        sb = bars.get(symbol, [])
        if len(sb) < MIN_BARS:
            continue
        closes = [b["c"] for b in sb]
        cur = closes[-1]
        if cur <= 0:
            continue
        rsi = _rsi(closes, RSI_PERIOD)
        if rsi <= RSI_OVERBOUGHT:
            continue
        rollover = closes[-1] < closes[-2]
        if not rollover:
            continue
        excess = rsi - RSI_OVERBOUGHT
        conf = round(min(0.83, 0.52 + excess * 0.012), 3)
        signals.append(Signal(
            symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
            reason=f"MR_RSI_OVERBOUGHT short: RSI(14)={rsi:.1f} > {RSI_OVERBOUGHT}, "
                   f"rollover confirmed, excess={excess:.1f}pts",
            strategy=STRATEGY_NAME,
        ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "RSI Overbought Short"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes = [b["c"] for b in symbol_bars]
    rsi = _rsi(closes, RSI_PERIOD)
    rollover = closes[-1] < closes[-2]
    fired = rsi > RSI_OVERBOUGHT and rollover
    excess = rsi - RSI_OVERBOUGHT
    score = round(min(0.83, 0.52 + excess * 0.012), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "sell" if fired else None, "score": score,
        "summary": f"RSI overbought short: RSI={rsi:.1f}, rollover={'yes' if rollover else 'no'}",
        "conditions": [
            {"name": f"RSI({RSI_PERIOD})", "current_value": round(rsi, 2), "operator": ">",
             "required_value": RSI_OVERBOUGHT, "unit": "", "passed": rsi > RSI_OVERBOUGHT, "to_pass": ""},
            {"name": "Rollover (last close < prior)", "current_value": int(rollover), "operator": "==",
             "required_value": 1, "unit": "", "passed": rollover, "to_pass": ""},
        ],
    }
