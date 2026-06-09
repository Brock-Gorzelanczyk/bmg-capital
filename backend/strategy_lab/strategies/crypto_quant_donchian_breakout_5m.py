"""
Crypto Quant Aggressive — S8: Donchian Breakout (5m)

Classic Donchian channel breakout adapted for 5m intraday quant cadence.

Entry:
  • 5m close > highest high of prior N bars → long  (fresh N-bar high)
  • 5m close < lowest  low  of prior N bars → short (fresh N-bar low)

Volume confirmation: current bar volume > VOL_MULT × N-bar avg volume.

Confidence scales with:
  - How far price extended past the channel (breakout excess)
  - Volume surge magnitude
  - Recent momentum (price above/below midpoint of channel)

Exit: profile trailing stop + hold_max_hours time-stop.
Bars: 5m.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_donchian_breakout_5m"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

DONCHIAN_PERIOD = 20   # 20 × 5m = 100 minutes ≈ 1.5 hours
VOL_MULT = 1.3         # 30% above average volume required
MIN_BARS = DONCHIAN_PERIOD + 3


def _donchian(bars: list[dict], period: int) -> tuple[float, float]:
    """Return (highest_high, lowest_low) of the prior `period` bars (excludes current bar)."""
    window = bars[-(period + 1):-1]
    if not window:
        return 0.0, 0.0
    highest = max(b["h"] for b in window)
    lowest  = min(b["l"] for b in window)
    return highest, lowest


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    signals: list[Signal] = []
    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", UNIVERSE) if isinstance(universe, dict) else UNIVERSE

    import datetime as _dt
    is_weekend = _dt.datetime.utcnow().weekday() >= 5
    conf_bump = float(profile_config.get("risk_overlay", {}).get("weekend_confidence_boost", 0.05)) if is_weekend else 0.0

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < MIN_BARS:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes  = [b["c"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]
        current_close = closes[-1]
        current_vol   = volumes[-1]
        if current_close <= 0:
            continue

        upper, lower = _donchian(symbol_bars, DONCHIAN_PERIOD)
        if upper <= 0 or lower <= 0:
            continue

        avg_vol = sum(volumes[-(DONCHIAN_PERIOD + 1):-1]) / DONCHIAN_PERIOD
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0.0
        volume_ok = vol_ratio >= VOL_MULT

        if not volume_ok:
            continue

        channel_width = max(upper - lower, current_close * 1e-6)
        midpoint = (upper + lower) / 2.0

        if current_close > upper:
            excess = (current_close - upper) / channel_width
            momentum_bonus = max(0.0, (current_close - midpoint) / channel_width * 0.05)
            vol_bonus = min(0.05, (vol_ratio - VOL_MULT) * 0.02)
            raw_conf = min(0.90, 0.52 + excess * 1.2 + momentum_bonus + vol_bonus)
            confidence = min(0.90, raw_conf + conf_bump)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=min(1.0, confidence),
                reason=(
                    f"DONCHIAN_BREAK long: 5m close {current_close:.4f} > "
                    f"{DONCHIAN_PERIOD}-bar high {upper:.4f}, "
                    f"vol {vol_ratio:.1f}x avg, excess {excess:.3f} of channel"
                ),
                strategy=STRATEGY_NAME,
            ))

        elif current_close < lower:
            excess = (lower - current_close) / channel_width
            momentum_bonus = max(0.0, (midpoint - current_close) / channel_width * 0.05)
            vol_bonus = min(0.05, (vol_ratio - VOL_MULT) * 0.02)
            raw_conf = min(0.90, 0.52 + excess * 1.2 + momentum_bonus + vol_bonus)
            confidence = min(0.90, raw_conf + conf_bump)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=round(confidence, 3),
                size_hint=min(1.0, confidence),
                reason=(
                    f"DONCHIAN_BREAK short: 5m close {current_close:.4f} < "
                    f"{DONCHIAN_PERIOD}-bar low {lower:.4f}, "
                    f"vol {vol_ratio:.1f}x avg, excess {excess:.3f} of channel"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    display_name = "Donchian Breakout (5m)"

    if len(symbol_bars) < MIN_BARS:
        return {
            "name": display_name, "key": STRATEGY_NAME,
            "fired": False, "side": None, "score": 0.0,
            "summary": f"Insufficient bars ({len(symbol_bars)}, need {MIN_BARS})",
            "conditions": [],
        }

    closes  = [b["c"] for b in symbol_bars]
    volumes = [b["v"] for b in symbol_bars]
    current_close = closes[-1]
    current_vol   = volumes[-1]
    upper, lower  = _donchian(symbol_bars, DONCHIAN_PERIOD)
    if upper <= 0 or lower <= 0:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "Insufficient data for Donchian", "conditions": []}

    avg_vol = sum(volumes[-(DONCHIAN_PERIOD + 1):-1]) / DONCHIAN_PERIOD
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0.0
    volume_ok = vol_ratio >= VOL_MULT
    above = current_close > upper
    below = current_close < lower
    price_ok = above or below
    channel_width = max(upper - lower, current_close * 1e-6)
    ticker = symbol.split("/")[0]

    cond_price = {
        "name": f"{DONCHIAN_PERIOD}-bar Donchian channel",
        "current_value": round(current_close, 4),
        "operator": "outside_channel",
        "required_value": [round(lower, 4), round(upper, 4)],
        "unit": "",
        "passed": price_ok,
        "to_pass": (
            f"Breakout {'long' if above else 'short'} met"
            if price_ok else
            f"{ticker} at ${current_close:,.4f} inside channel [${lower:,.4f}–${upper:,.4f}]"
        ),
    }
    cond_vol = {
        "name": "Volume vs avg",
        "current_value": round(vol_ratio, 3),
        "operator": ">=",
        "required_value": VOL_MULT,
        "unit": "x",
        "passed": volume_ok,
        "to_pass": (
            f"Volume confirmed ({vol_ratio:.2f}x ≥ {VOL_MULT}x)"
            if volume_ok else
            f"Need {VOL_MULT}x avg — currently {vol_ratio:.2f}x"
        ),
    }

    fired_long  = above and volume_ok
    fired_short = below and volume_ok
    fired = fired_long or fired_short
    side = "buy" if fired_long else ("sell" if fired_short else None)
    score = 0.0
    if fired_long:
        excess = (current_close - upper) / channel_width
        score = round(min(0.90, 0.52 + excess * 1.2), 4)
    elif fired_short:
        excess = (lower - current_close) / channel_width
        score = round(min(0.90, 0.52 + excess * 1.2), 4)

    summary = (
        f"Donchian breakout {'long' if fired_long else 'short'} — "
        f"price {'above' if fired_long else 'below'} {DONCHIAN_PERIOD}-bar channel, vol {vol_ratio:.1f}x"
        if fired else
        f"Price inside Donchian channel [${lower:,.4f}–${upper:,.4f}]"
        + ("" if not price_ok else f" (volume insufficient {vol_ratio:.2f}x)")
    )

    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": side, "score": score,
        "summary": summary, "conditions": [cond_price, cond_vol],
    }
