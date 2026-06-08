"""
Crypto Quant Aggressive — S3: Momentum Trigger

Entry (long):  15m close > prior 4h high AND volume > 2.0x avg → long
Entry (short): 15m close < prior 4h low  AND volume > 2.0x avg → short
Exit: trailing 2% stop; time-stop 8h.

Bars: 15m (profile scan_timeframe=15m).
Prior 4h high/low = highest high / lowest low across the preceding 16 bars (4h ÷ 15m).
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_momentum_trigger"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

LOOKBACK_BARS_4H = 16      # 16 x 15m = 4h
VOLUME_MULT = 1.3          # lowered from 2.0 — 2x was too strict for regular crypto markets
TRAILING_STOP_PCT = 2.0    # 2% trailing stop


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate momentum trigger signals.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first, 15m bars.
        profile_config: Profile YAML dict.
        regime: Regime context dict.

    Returns:
        List of Signal objects.
    """
    signals: list[Signal] = []
    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", UNIVERSE) if isinstance(universe, dict) else UNIVERSE

    import datetime as _dt
    is_weekend = _dt.datetime.utcnow().weekday() >= 5
    conf_bump = float(profile_config.get("risk_overlay", {}).get("weekend_confidence_boost", 0.05)) if is_weekend else 0.0

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        # Need at least LOOKBACK_BARS_4H + 1 bars (the lookback window + current bar)
        if len(symbol_bars) < LOOKBACK_BARS_4H + 2:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        highs = [b["h"] for b in symbol_bars]
        lows = [b["l"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]

        current_close = closes[-1]
        if current_close <= 0:
            continue

        # Prior 4h window: bars[-LOOKBACK_BARS_4H-1 : -1] (excludes current bar)
        prior_window_highs = highs[-(LOOKBACK_BARS_4H + 1):-1]
        prior_window_lows = lows[-(LOOKBACK_BARS_4H + 1):-1]
        if not prior_window_highs:
            continue

        prior_4h_high = max(prior_window_highs)
        prior_4h_low = min(prior_window_lows)

        # Volume: current vs average of prior 20 bars
        vol_period = min(20, len(volumes) - 1)
        avg_vol = sum(volumes[-(vol_period + 1):-1]) / vol_period if vol_period > 0 else 0
        current_vol = volumes[-1]
        volume_ok = avg_vol > 0 and current_vol >= VOLUME_MULT * avg_vol
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

        if not volume_ok:
            continue

        # Momentum long: close breaks above prior 4h high
        if current_close > prior_4h_high:
            breakout_pct = (current_close - prior_4h_high) / prior_4h_high
            raw_conf = min(0.9, 0.60 + breakout_pct * 10 + (vol_ratio - VOLUME_MULT) * 0.02)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"MOMENTUM_TRIGGER long: close {current_close:.4f} > 4h high {prior_4h_high:.4f} "
                    f"(+{breakout_pct * 100:.2f}%), vol {vol_ratio:.1f}x avg, "
                    f"trail-stop {TRAILING_STOP_PCT}%, time-stop 8h"
                ),
                strategy=STRATEGY_NAME,
            ))

        # Momentum short: close breaks below prior 4h low
        elif current_close < prior_4h_low:
            breakdown_pct = (prior_4h_low - current_close) / prior_4h_low
            raw_conf = min(0.9, 0.60 + breakdown_pct * 10 + (vol_ratio - VOLUME_MULT) * 0.02)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"MOMENTUM_TRIGGER short: close {current_close:.4f} < 4h low {prior_4h_low:.4f} "
                    f"(-{breakdown_pct * 100:.2f}%), vol {vol_ratio:.1f}x avg, "
                    f"trail-stop {TRAILING_STOP_PCT}%, time-stop 8h"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    """Evaluate Momentum Trigger conditions for one symbol and return a structured trace."""
    display_name = "Momentum Trigger"

    if len(symbol_bars) < LOOKBACK_BARS_4H + 2:
        return {
            "name": display_name, "key": STRATEGY_NAME,
            "fired": False, "side": None, "score": 0.0,
            "summary": f"Insufficient bars ({len(symbol_bars)} available, need {LOOKBACK_BARS_4H + 2})",
            "conditions": [],
        }

    closes = [b["c"] for b in symbol_bars]
    highs = [b["h"] for b in symbol_bars]
    lows = [b["l"] for b in symbol_bars]
    volumes = [b["v"] for b in symbol_bars]
    current_close = closes[-1]
    if current_close <= 0:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "Invalid price data", "conditions": []}

    prior_window_highs = highs[-(LOOKBACK_BARS_4H + 1):-1]
    prior_window_lows = lows[-(LOOKBACK_BARS_4H + 1):-1]
    prior_4h_high = max(prior_window_highs)
    prior_4h_low = min(prior_window_lows)

    vol_period = min(20, len(volumes) - 1)
    avg_vol = sum(volumes[-(vol_period + 1):-1]) / vol_period if vol_period > 0 else 0
    current_vol = volumes[-1]
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0
    volume_ok = avg_vol > 0 and current_vol >= VOLUME_MULT * avg_vol
    ticker = symbol.split("/")[0]

    # ── Condition 1: Price vs 4h high/low ────────────────────────────────────
    above_high = current_close > prior_4h_high
    below_low = current_close < prior_4h_low
    price_ok = above_high or below_low

    if above_high:
        to_pass_price = f"Upside breakout confirmed (${current_close:,.4f} > 4h high ${prior_4h_high:,.4f})"
    elif below_low:
        to_pass_price = f"Downside breakout confirmed (${current_close:,.4f} < 4h low ${prior_4h_low:,.4f})"
    else:
        gap_to_high = prior_4h_high - current_close
        gap_to_low = current_close - prior_4h_low
        if gap_to_high <= gap_to_low:
            pct = gap_to_high / current_close * 100
            to_pass_price = (
                f"{ticker} needs to close above 4h high ${prior_4h_high:,.4f} (+{pct:.1f}% from ${current_close:,.4f})"
            )
        else:
            pct = gap_to_low / current_close * 100
            to_pass_price = (
                f"{ticker} needs to close below 4h low ${prior_4h_low:,.4f} (-{pct:.1f}% from ${current_close:,.4f})"
            )

    cond_price = {
        "name": f"15m close vs prior 4h high/low ({LOOKBACK_BARS_4H} bars = 4h)",
        "current_value": round(current_close, 4),
        "operator": "outside_range",
        "required_value": [round(prior_4h_low, 4), round(prior_4h_high, 4)],
        "unit": "",
        "passed": price_ok,
        "to_pass": to_pass_price,
    }

    # ── Condition 2: Volume surge ─────────────────────────────────────────────
    if volume_ok:
        to_pass_vol = f"Volume surge confirmed ({vol_ratio:.2f}x ≥ {VOLUME_MULT}x required)"
    else:
        pct_short = ((VOLUME_MULT * avg_vol - current_vol) / (VOLUME_MULT * avg_vol) * 100) if avg_vol > 0 else 0
        to_pass_vol = (
            f"Volume needs {VOLUME_MULT}x the 20-bar avg — currently {vol_ratio:.2f}x "
            f"(need {pct_short:.0f}% more on current bar)"
        )

    cond_vol = {
        "name": "Volume vs 20-bar average",
        "current_value": round(vol_ratio, 3),
        "operator": ">=",
        "required_value": VOLUME_MULT,
        "unit": "x",
        "passed": volume_ok,
        "to_pass": to_pass_vol,
    }

    conditions = [cond_price, cond_vol]

    fired_long = above_high and volume_ok
    fired_short = below_low and volume_ok
    fired = fired_long or fired_short
    side = "buy" if fired_long else ("sell" if fired_short else None)

    if fired:
        bp = ((current_close - prior_4h_high) / prior_4h_high) if fired_long else ((prior_4h_low - current_close) / prior_4h_low)
        score = round(min(0.9, 0.60 + bp * 10 + (vol_ratio - VOLUME_MULT) * 0.02), 4)
        summary = (
            f"Momentum {'long' if fired_long else 'short'} triggered — "
            f"close {'above' if fired_long else 'below'} 4h range by {bp * 100:.2f}%, "
            f"vol {vol_ratio:.1f}x avg"
        )
    else:
        score = 0.0
        range_pct = ((prior_4h_high - prior_4h_low) / prior_4h_low * 100) if prior_4h_low > 0 else 0
        if not price_ok:
            summary = (
                f"Price inside 4h range (${prior_4h_low:,.4f}–${prior_4h_high:,.4f}, "
                f"{range_pct:.1f}% wide)"
            )
        elif not volume_ok:
            summary = f"Price broke 4h range but volume insufficient ({vol_ratio:.2f}x avg, need {VOLUME_MULT}x)"
        else:
            summary = "No breakout conditions met"

    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": side, "score": score,
        "summary": summary, "conditions": conditions,
    }
