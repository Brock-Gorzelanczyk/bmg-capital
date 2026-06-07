"""
Crypto Quant Aggressive — S1: VWAP Fade

Entry: price > 2σ from session VWAP AND RSI(14) > 70 → short (fade above)
       price < 2σ from session VWAP AND RSI(14) < 30 → long (fade below)
Exit: price returns to VWAP
Time-stop: 4h (profile enforces via hold_max_hours; signal declares hold_hours=4)

Bars: 15m (profile scan_timeframe=15m). Session VWAP is computed from all
available bars (up to 500 lookback from crypto_quant_aggressive profile).
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_vwap_fade"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

RSI_PERIOD = 14
VWAP_SIGMA_THRESHOLD = 2.0
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0


def _compute_vwap_and_sigma(bars: list[dict]) -> tuple[float, float]:
    """Compute session VWAP and standard deviation of (close - VWAP) from bars."""
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        v = b["v"]
        cum_tp_vol += tp * v
        cum_vol += v
    if cum_vol <= 0:
        return 0.0, 0.0
    vwap = cum_tp_vol / cum_vol

    # std dev of (typical_price - vwap) weighted by volume
    sq_sum = 0.0
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        sq_sum += (tp - vwap) ** 2
    sigma = math.sqrt(sq_sum / len(bars)) if bars else 0.0
    return vwap, sigma


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float:
    """Compute RSI(period) from a list of closes (oldest-first)."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [abs(d) for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate VWAP fade signals.

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

    # Weekend confidence bump from profile
    import datetime as _dt
    is_weekend = _dt.datetime.utcnow().weekday() >= 5
    conf_bump = float(profile_config.get("risk_overlay", {}).get("weekend_confidence_boost", 0.05)) if is_weekend else 0.0

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < RSI_PERIOD + 2:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        current_close = closes[-1]
        if current_close <= 0:
            continue

        vwap, sigma = _compute_vwap_and_sigma(symbol_bars)
        if vwap <= 0 or sigma <= 0:
            continue

        rsi = _compute_rsi(closes)
        deviation = current_close - vwap
        sigma_distance = deviation / sigma  # positive = above VWAP

        # Fade short: price > 2σ above VWAP and RSI overbought
        if sigma_distance > VWAP_SIGMA_THRESHOLD and rsi > RSI_OVERBOUGHT:
            raw_conf = min(0.9, 0.55 + (sigma_distance - VWAP_SIGMA_THRESHOLD) * 0.08 + (rsi - RSI_OVERBOUGHT) * 0.002)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"VWAP_FADE short: price {current_close:.4f} is +{sigma_distance:.2f}σ above "
                    f"VWAP {vwap:.4f} (2σ={sigma * VWAP_SIGMA_THRESHOLD:.4f}), "
                    f"RSI(14)={rsi:.1f} > 70, fade to VWAP, time-stop 4h"
                ),
                strategy=STRATEGY_NAME,
            ))

        # Fade long: price < 2σ below VWAP and RSI oversold
        elif sigma_distance < -VWAP_SIGMA_THRESHOLD and rsi < RSI_OVERSOLD:
            raw_conf = min(0.9, 0.55 + (abs(sigma_distance) - VWAP_SIGMA_THRESHOLD) * 0.08 + (RSI_OVERSOLD - rsi) * 0.002)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"VWAP_FADE long: price {current_close:.4f} is {sigma_distance:.2f}σ below "
                    f"VWAP {vwap:.4f} (2σ={sigma * VWAP_SIGMA_THRESHOLD:.4f}), "
                    f"RSI(14)={rsi:.1f} < 30, fade to VWAP, time-stop 4h"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
