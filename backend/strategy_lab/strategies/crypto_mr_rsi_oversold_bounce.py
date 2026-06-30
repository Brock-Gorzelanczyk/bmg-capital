"""
Crypto Mean Reversion — S2: RSI Oversold Bounce (5m)

RSI(14) < 25 on 5m bars = deeply oversold. Buy the bounce.

Entry:
  RSI(14) < 25 → long
  Confirmation: price must NOT still be making new lows (last close > prior close)
  — this filters capitulation from genuine bounce initiation.

Target: mean reversion back to RSI 50 territory (approx 2.5% up).
Stop: 2%.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_rsi_oversold_bounce"

RSI_PERIOD = 14
RSI_OVERSOLD = 25.0
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
        if rsi >= RSI_OVERSOLD:
            continue
        bounce_ok = closes[-1] > closes[-2]  # last bar closed up (bounce initiation)
        if not bounce_ok:
            continue
        depth = RSI_OVERSOLD - rsi
        conf = round(min(0.83, 0.52 + depth * 0.012), 3)
        signals.append(Signal(
            symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
            reason=f"MR_RSI_OVERSOLD long: RSI(14)={rsi:.1f} < {RSI_OVERSOLD}, "
                   f"bounce confirmed, depth={depth:.1f}pts",
            strategy=STRATEGY_NAME,
        ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "RSI Oversold Bounce"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes = [b["c"] for b in symbol_bars]
    rsi = _rsi(closes, RSI_PERIOD)
    bounce_ok = closes[-1] > closes[-2]
    fired = rsi < RSI_OVERSOLD and bounce_ok
    depth = RSI_OVERSOLD - rsi
    score = round(min(0.83, 0.52 + depth * 0.012), 4) if fired else 0.0
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if fired else None, "score": score,
        "summary": (
            f"RSI oversold bounce: RSI={rsi:.1f}, bounce={'yes' if bounce_ok else 'no'}"
        ),
        "conditions": [
            {"name": f"RSI({RSI_PERIOD})", "current_value": round(rsi, 2), "operator": "<",
             "required_value": RSI_OVERSOLD, "unit": "", "passed": rsi < RSI_OVERSOLD, "to_pass": ""},
            {"name": "Bounce confirmed (last close > prior)", "current_value": int(bounce_ok), "operator": "==",
             "required_value": 1, "unit": "", "passed": bounce_ok, "to_pass": ""},
        ],
    }
