"""
Crypto Quant Scalper — S1: Micro Breakout (1m)

5-bar high/low breakout on 1m bars with volume surge confirmation.
Tight entry: close must exceed the 5-bar channel by at least MIN_EXCESS_BPS.

Entry:
  close > 5-bar high AND volume > 1.5x 5-bar avg → long
  close < 5-bar low  AND volume > 1.5x 5-bar avg → short

Target: 1% from entry (profile take_profit_pct). Stop: 0.5%.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_scalper_micro_breakout"

CHANNEL_BARS = 5
VOL_MULT = 1.5
MIN_EXCESS_BPS = 5    # 5bps minimum breakout past channel to avoid false signals
MIN_BARS = CHANNEL_BARS + 2

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

        closes  = [b["c"] for b in sb]
        volumes = [b["v"] for b in sb]
        highs   = [b["h"] for b in sb]
        lows    = [b["l"] for b in sb]
        cur = closes[-1]
        if cur <= 0:
            continue

        window_high = max(highs[-(CHANNEL_BARS + 1):-1])
        window_low  = min(lows[-(CHANNEL_BARS + 1):-1])
        avg_vol = sum(volumes[-(CHANNEL_BARS + 1):-1]) / CHANNEL_BARS
        cur_vol = volumes[-1]
        vol_ok  = avg_vol > 0 and cur_vol >= VOL_MULT * avg_vol
        if not vol_ok:
            continue

        excess_bps_up   = (cur - window_high) / window_high * 10_000 if cur > window_high else 0
        excess_bps_down = (window_low - cur)  / window_low  * 10_000 if cur < window_low  else 0

        if excess_bps_up >= MIN_EXCESS_BPS:
            vol_ratio = cur_vol / avg_vol
            conf = round(min(0.85, 0.48 + excess_bps_up * 0.004 + (vol_ratio - VOL_MULT) * 0.02), 3)
            signals.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MICRO_BREAK long: close {cur:.4f} > 5-bar high {window_high:.4f} "
                       f"(+{excess_bps_up:.1f}bps), vol {vol_ratio:.1f}x",
                strategy=STRATEGY_NAME,
            ))
        elif excess_bps_down >= MIN_EXCESS_BPS:
            vol_ratio = cur_vol / avg_vol
            conf = round(min(0.85, 0.48 + excess_bps_down * 0.004 + (vol_ratio - VOL_MULT) * 0.02), 3)
            signals.append(Signal(
                symbol=symbol, side="sell", confidence=conf, size_hint=min(1.0, conf),
                reason=f"MICRO_BREAK short: close {cur:.4f} < 5-bar low {window_low:.4f} "
                       f"(-{excess_bps_down:.1f}bps), vol {vol_ratio:.1f}x",
                strategy=STRATEGY_NAME,
            ))
    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Micro Breakout"
    if len(symbol_bars) < MIN_BARS:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": f"Need {MIN_BARS} bars", "conditions": []}
    closes  = [b["c"] for b in symbol_bars]
    volumes = [b["v"] for b in symbol_bars]
    highs   = [b["h"] for b in symbol_bars]
    lows    = [b["l"] for b in symbol_bars]
    cur = closes[-1]
    window_high = max(highs[-(CHANNEL_BARS + 1):-1])
    window_low  = min(lows[-(CHANNEL_BARS + 1):-1])
    avg_vol = sum(volumes[-(CHANNEL_BARS + 1):-1]) / CHANNEL_BARS
    cur_vol = volumes[-1]
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
    vol_ok = vol_ratio >= VOL_MULT
    fired_long  = cur > window_high and (cur - window_high) / window_high * 10_000 >= MIN_EXCESS_BPS and vol_ok
    fired_short = cur < window_low  and (window_low - cur)  / window_low  * 10_000 >= MIN_EXCESS_BPS and vol_ok
    fired = fired_long or fired_short
    score = 0.0
    if fired_long:
        score = round(min(0.85, 0.48 + (cur - window_high) / window_high * 10_000 * 0.004), 4)
    elif fired_short:
        score = round(min(0.85, 0.48 + (window_low - cur) / window_low * 10_000 * 0.004), 4)
    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": "buy" if fired_long else ("sell" if fired_short else None),
        "score": score,
        "summary": f"{'Long breakout' if fired_long else 'Short breakout' if fired_short else 'Inside channel'} — vol {vol_ratio:.2f}x",
        "conditions": [
            {"name": "5-bar channel break", "current_value": round(cur, 4),
             "operator": "outside", "required_value": [round(window_low, 4), round(window_high, 4)],
             "unit": "", "passed": cur > window_high or cur < window_low, "to_pass": ""},
            {"name": "Volume", "current_value": round(vol_ratio, 3), "operator": ">=",
             "required_value": VOL_MULT, "unit": "x", "passed": vol_ok, "to_pass": ""},
        ],
    }
