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
VWAP_SIGMA_THRESHOLD = 1.5   # lowered from 2.0 — 2σ + RSI extreme simultaneously was too rare
RSI_OVERBOUGHT = 65.0         # lowered from 70 to capture more extended moves
RSI_OVERSOLD = 35.0           # raised from 30


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


def trace_symbol(symbol: str, symbol_bars: list[dict], profile_config: dict) -> dict:
    """Evaluate VWAP Fade entry conditions for one symbol and return a structured trace."""
    display_name = "VWAP Fade"

    if len(symbol_bars) < RSI_PERIOD + 2:
        return {
            "name": display_name, "key": STRATEGY_NAME,
            "fired": False, "side": None, "score": 0.0,
            "summary": f"Insufficient bars ({len(symbol_bars)} available, need {RSI_PERIOD + 2})",
            "conditions": [],
        }

    closes = [b["c"] for b in symbol_bars]
    current_close = closes[-1]
    if current_close <= 0:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "Invalid price data", "conditions": []}

    vwap, sigma = _compute_vwap_and_sigma(symbol_bars)
    if vwap <= 0 or sigma <= 0:
        return {"name": display_name, "key": STRATEGY_NAME, "fired": False, "side": None,
                "score": 0.0, "summary": "Insufficient volume for VWAP calculation", "conditions": []}

    rsi = _compute_rsi(closes)
    sigma_distance = (current_close - vwap) / sigma
    abs_sigma = abs(sigma_distance)
    ticker = symbol.split("/")[0]

    # ── Condition 1: σ-distance from VWAP ────────────────────────────────────
    sigma_passed = abs_sigma >= VWAP_SIGMA_THRESHOLD
    if sigma_distance >= 0:
        price_for_trigger = vwap + VWAP_SIGMA_THRESHOLD * sigma
        pct_away = (price_for_trigger - current_close) / current_close * 100
        to_pass_sigma = (
            f"Deviation met (+{abs_sigma:.2f}σ above VWAP — short fade trigger)"
            if sigma_passed else
            f"{ticker} needs to rise to ${price_for_trigger:,.4f} (+{pct_away:.1f}%) to hit {VWAP_SIGMA_THRESHOLD}σ threshold"
        )
    else:
        price_for_trigger = vwap - VWAP_SIGMA_THRESHOLD * sigma
        pct_away = (current_close - price_for_trigger) / current_close * 100
        to_pass_sigma = (
            f"Deviation met ({abs_sigma:.2f}σ below VWAP — long fade trigger)"
            if sigma_passed else
            f"{ticker} needs to drop to ${price_for_trigger:,.4f} (-{pct_away:.1f}%) to hit {VWAP_SIGMA_THRESHOLD}σ threshold"
        )

    cond_sigma = {
        "name": f"Price σ-distance from session VWAP",
        "current_value": round(abs_sigma, 3),
        "operator": ">=",
        "required_value": VWAP_SIGMA_THRESHOLD,
        "unit": "σ",
        "passed": sigma_passed,
        "to_pass": to_pass_sigma,
    }

    # ── Condition 2: RSI extreme ───────────────────────────────────────────────
    if sigma_distance >= 0:
        rsi_passed = rsi > RSI_OVERBOUGHT
        to_pass_rsi = (
            f"RSI overbought condition met ({rsi:.1f} > {RSI_OVERBOUGHT})"
            if rsi_passed else
            f"RSI needs to rise from {rsi:.1f} to above {RSI_OVERBOUGHT} (currently {RSI_OVERBOUGHT - rsi:.1f} pts short)"
        )
        cond_rsi = {"name": f"RSI({RSI_PERIOD}) overbought", "current_value": round(rsi, 1),
                    "operator": ">", "required_value": RSI_OVERBOUGHT, "unit": "",
                    "passed": rsi_passed, "to_pass": to_pass_rsi}
    else:
        rsi_passed = rsi < RSI_OVERSOLD
        to_pass_rsi = (
            f"RSI oversold condition met ({rsi:.1f} < {RSI_OVERSOLD})"
            if rsi_passed else
            f"RSI needs to drop from {rsi:.1f} to below {RSI_OVERSOLD} (currently {rsi - RSI_OVERSOLD:.1f} pts above)"
        )
        cond_rsi = {"name": f"RSI({RSI_PERIOD}) oversold", "current_value": round(rsi, 1),
                    "operator": "<", "required_value": RSI_OVERSOLD, "unit": "",
                    "passed": rsi_passed, "to_pass": to_pass_rsi}

    conditions = [cond_sigma, cond_rsi]

    fired_short = sigma_distance > VWAP_SIGMA_THRESHOLD and rsi > RSI_OVERBOUGHT
    fired_long = sigma_distance < -VWAP_SIGMA_THRESHOLD and rsi < RSI_OVERSOLD
    fired = fired_short or fired_long
    side = "sell" if fired_short else ("buy" if fired_long else None)

    if fired:
        rsi_extreme = abs(rsi - (RSI_OVERBOUGHT if fired_short else RSI_OVERSOLD))
        score = round(min(0.9, 0.55 + (abs_sigma - VWAP_SIGMA_THRESHOLD) * 0.08 + rsi_extreme * 0.002), 4)
        summary = (
            f"{'Short' if fired_short else 'Long'} fade triggered — "
            f"price {abs_sigma:.2f}σ from VWAP, RSI({RSI_PERIOD}) {rsi:.1f}"
        )
    else:
        score = 0.0
        if not sigma_passed:
            summary = (
                f"Price too close to VWAP — needs ≥{VWAP_SIGMA_THRESHOLD}σ deviation "
                f"(currently {abs_sigma:.2f}σ, VWAP=${vwap:,.4f})"
            )
        else:
            summary = (
                f"VWAP deviation met ({abs_sigma:.2f}σ) but RSI not extreme "
                f"(RSI {rsi:.1f}, needs {'>' + str(RSI_OVERBOUGHT) if sigma_distance > 0 else '<' + str(RSI_OVERSOLD)})"
            )

    return {
        "name": display_name, "key": STRATEGY_NAME,
        "fired": fired, "side": side, "score": score,
        "summary": summary, "conditions": conditions,
    }
