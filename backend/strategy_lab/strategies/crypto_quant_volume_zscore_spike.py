"""
Crypto Quant Aggressive — S5: Volume Z-Score Spike

Entry: 15m volume z-score > 3.0 vs 24h rolling (96 bars at 15m) → with the price direction
  - If the volume-spike bar is bullish (close > open) → long
  - If the volume-spike bar is bearish (close < open) → short
Exit: tight 1.5% stop; time-stop 2h.

Bars: 15m (profile scan_timeframe=15m).
Z-score computed over last 96 bars (24h ÷ 15m).
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_volume_zscore_spike"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

ZSCORE_PERIOD = 96    # 24h of 15m bars
ZSCORE_THRESHOLD = 2.0   # lowered from 3.0 — 3σ fires <0.1% of bars; 2σ fires ~5%
STOP_PCT = 1.5
HOLD_HOURS = 2


def _volume_zscore(volumes: list[float], period: int = ZSCORE_PERIOD) -> float:
    """Compute z-score of current (last) volume vs rolling window."""
    if len(volumes) < period + 1:
        return 0.0
    window = volumes[-(period + 1):-1]   # prior `period` bars, exclude current
    if not window:
        return 0.0
    mean = sum(window) / len(window)
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    std = math.sqrt(variance)
    if std <= 0:
        return 0.0
    return (volumes[-1] - mean) / std


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate volume z-score spike signals.

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
        if len(symbol_bars) < ZSCORE_PERIOD + 2:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        volumes = [b["v"] for b in symbol_bars]
        opens = [b["o"] for b in symbol_bars]
        closes = [b["c"] for b in symbol_bars]

        current_close = closes[-1]
        current_open = opens[-1]
        if current_close <= 0:
            continue

        zscore = _volume_zscore(volumes)
        if zscore < ZSCORE_THRESHOLD:
            continue

        current_vol = volumes[-1]
        avg_vol = sum(volumes[-(ZSCORE_PERIOD + 1):-1]) / ZSCORE_PERIOD

        # Bar direction determines signal side
        bar_bullish = current_close > current_open
        bar_move_pct = abs(current_close - current_open) / current_open if current_open > 0 else 0

        # Confidence: scales with z-score magnitude and bar body size
        raw_conf = min(0.9, 0.55 + (zscore - ZSCORE_THRESHOLD) * 0.04 + bar_move_pct * 2)
        confidence = min(0.9, raw_conf + conf_bump)
        size_hint = min(1.0, confidence)

        side = "buy" if bar_bullish else "sell"
        direction_str = "bullish" if bar_bullish else "bearish"

        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            size_hint=size_hint,
            reason=(
                f"VOLUME_ZSCORE_SPIKE {direction_str}: vol z-score={zscore:.2f} > {ZSCORE_THRESHOLD} "
                f"(current {current_vol:.0f} vs avg {avg_vol:.0f}), "
                f"bar {'up' if bar_bullish else 'down'} {bar_move_pct * 100:.2f}%, "
                f"tight {STOP_PCT}% stop, time-stop {HOLD_HOURS}h"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    """Evaluate Volume Z-Score Spike conditions for one symbol and return a structured trace."""
    display_name = "Volume Z-Score Spike"

    if len(symbol_bars) < ZSCORE_PERIOD + 2:
        return {
            "name": display_name, "key": STRATEGY_NAME,
            "fired": False, "side": None, "score": 0.0,
            "summary": f"Insufficient bars ({len(symbol_bars)} available, need {ZSCORE_PERIOD + 2})",
            "conditions": [],
        }

    volumes = [b["v"] for b in symbol_bars]
    opens = [b["o"] for b in symbol_bars]
    closes = [b["c"] for b in symbol_bars]
    current_close = closes[-1]
    current_open = opens[-1]
    current_vol = volumes[-1]
    if current_close <= 0:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "Invalid price data", "conditions": []}

    zscore = _volume_zscore(volumes)
    window = volumes[-(ZSCORE_PERIOD + 1):-1]
    avg_vol = sum(window) / len(window) if window else 0
    bar_bullish = current_close > current_open
    bar_move_pct = abs(current_close - current_open) / current_open if current_open > 0 else 0
    ticker = symbol.split("/")[0]

    # ── Condition 1: Volume z-score threshold ─────────────────────────────────
    zscore_passed = zscore >= ZSCORE_THRESHOLD
    if zscore_passed:
        to_pass_z = f"Volume spike confirmed — z-score {zscore:.2f} ≥ {ZSCORE_THRESHOLD} threshold"
    else:
        # Compute how much more volume is needed
        variance = sum((v - avg_vol) ** 2 for v in window) / len(window) if window else 0
        std_v = variance ** 0.5
        vol_needed = avg_vol + ZSCORE_THRESHOLD * std_v
        pct_needed = ((vol_needed - current_vol) / current_vol * 100) if current_vol > 0 else 0
        to_pass_z = (
            f"Volume z-score is {zscore:.2f} (need ≥{ZSCORE_THRESHOLD}). "
            f"Current bar needs ~{pct_needed:.0f}% more volume to hit threshold"
        )

    cond_z = {
        "name": f"Volume z-score vs {ZSCORE_PERIOD}-bar rolling window (24h)",
        "current_value": round(zscore, 3),
        "operator": ">=",
        "required_value": ZSCORE_THRESHOLD,
        "unit": "σ",
        "passed": zscore_passed,
        "to_pass": to_pass_z,
    }

    # ── Condition 2: Bar direction (always passes — picks side) ──────────────
    bar_dir = "bullish" if bar_bullish else "bearish"
    cond_dir = {
        "name": "Current bar direction",
        "current_value": round(bar_move_pct * 100, 3),
        "operator": "!=",
        "required_value": 0,
        "unit": "% body",
        "passed": True,
        "to_pass": (
            f"Bar is {bar_dir} ({bar_move_pct * 100:.2f}% body) "
            f"→ signal side = {'buy' if bar_bullish else 'sell'}"
        ),
    }

    conditions = [cond_z, cond_dir]

    fired = zscore_passed
    side = ("buy" if bar_bullish else "sell") if fired else None

    if fired:
        score = round(min(0.9, 0.55 + (zscore - ZSCORE_THRESHOLD) * 0.04 + bar_move_pct * 2), 4)
        summary = (
            f"Volume spike {bar_dir} confirmed — z-score {zscore:.2f} ≥ {ZSCORE_THRESHOLD}, "
            f"bar {'up' if bar_bullish else 'down'} {bar_move_pct * 100:.2f}%"
        )
    else:
        score = 0.0
        summary = (
            f"Volume z-score too low — {zscore:.2f} (need ≥{ZSCORE_THRESHOLD}). "
            f"Current vol {current_vol:,.0f} vs 24h avg {avg_vol:,.0f}"
        )

    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": side, "score": score,
        "summary": summary, "conditions": conditions,
    }
