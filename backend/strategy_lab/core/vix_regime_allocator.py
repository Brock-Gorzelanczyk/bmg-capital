"""
VIX Regime Allocator — scales position size_hints based on VIX level.

When VIX > 25:
  - momentum bots: multiply size_hint by 0.50 (reduce exposure in panic)
  - mean_reversion bots: multiply size_hint by 1.50 (capped at 1.0 — MR thrives in volatility)

When VIX <= 25: baselines restored (multiplier = 1.0)

Bot strategy_type classification:
  momentum: stock_swing, stock_day, crypto_swing, crypto_day, crypto_quant_aggressive,
            crypto_quant_scalper, tsmom_multi_asset
  mean_reversion: crypto_quant_mean_reversion, stock_lt, crypto_meanrev_2163
  carry_income: options_income, options_directional
  other: crypto_lt, crypto_onchain, quality_factor, value_quality, earnings_nlp

Reference: Moskowitz, Ooi & Pedersen (2012) TSMOM vol-scaling appendix;
           Barroso & Santa-Clara (2015) "Momentum Has Its Moments".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

# ── Strategy-type classification ───────────────────────────────────────────────
_MOMENTUM_PROFILES: frozenset[str] = frozenset({
    "stock_swing",
    "stock_day",
    "crypto_swing",
    "crypto_day",
    "crypto_quant_aggressive",
    "crypto_quant_scalper",
    "tsmom_multi_asset",
})

_MEAN_REVERSION_PROFILES: frozenset[str] = frozenset({
    "crypto_quant_mean_reversion",
    "stock_lt",
    "crypto_meanrev_2163",
})

_CARRY_INCOME_PROFILES: frozenset[str] = frozenset({
    "options_income",
    "options_directional",
})

# VIX threshold that triggers regime scaling
VIX_HIGH_THRESHOLD = 25.0

# Multipliers when VIX > threshold
MOMENTUM_HIGH_VIX_MULT = 0.50
MEAN_REVERSION_HIGH_VIX_MULT = 1.50


def _get_strategy_type(profile_name: str) -> str:
    """Classify a profile into a strategy_type bucket."""
    if profile_name in _MOMENTUM_PROFILES:
        return "momentum"
    if profile_name in _MEAN_REVERSION_PROFILES:
        return "mean_reversion"
    if profile_name in _CARRY_INCOME_PROFILES:
        return "carry_income"
    return "other"


def _get_vix(regime: dict) -> Optional[float]:
    """Extract VIX value from regime dict. Returns None if unavailable."""
    vix = regime.get("vix") or regime.get("vix_value")
    if vix is None:
        return None
    try:
        return float(vix)
    except (TypeError, ValueError):
        return None


def _scale_signal(sig: Signal, multiplier: float) -> Signal:
    """Return a new Signal with size_hint scaled by multiplier, capped at 1.0."""
    new_size = min(1.0, max(0.0, (sig.size_hint or 0.0) * multiplier))
    return Signal(
        symbol=sig.symbol,
        side=sig.side,
        confidence=sig.confidence,
        size_hint=new_size,
        reason=sig.reason,
        strategy=sig.strategy,
        ts=getattr(sig, "ts", None),
    )


def apply_vix_scaling(
    signals: list[Signal],
    profile_name: str,
    regime: dict,
) -> tuple[list[Signal], float]:
    """Scale signal size_hints based on VIX regime.

    Args:
        signals:      List of Signal objects from strategy generate_signals().
        profile_name: Bot profile key — determines momentum vs mean_reversion.
        regime:       Regime dict from detect_regime(); must contain 'vix' or 'vix_value'.

    Returns:
        (scaled_signals, multiplier_applied)
        multiplier_applied is 1.0 when no scaling occurs.
    """
    if not signals:
        return signals, 1.0

    vix = _get_vix(regime)
    strategy_type = _get_strategy_type(profile_name)

    # No VIX data available — pass through unchanged
    if vix is None:
        logger.debug("[vix-alloc] %s: no VIX in regime dict — no scaling", profile_name)
        return signals, 1.0

    # VIX below threshold — no scaling
    if vix <= VIX_HIGH_THRESHOLD:
        logger.debug(
            "[vix-alloc] %s: VIX=%.1f <= %.0f — no scaling (type=%s)",
            profile_name, vix, VIX_HIGH_THRESHOLD, strategy_type,
        )
        return signals, 1.0

    # VIX above threshold — determine multiplier
    if strategy_type == "momentum":
        multiplier = MOMENTUM_HIGH_VIX_MULT
    elif strategy_type == "mean_reversion":
        multiplier = MEAN_REVERSION_HIGH_VIX_MULT
    else:
        # carry_income and other — no VIX-based size scaling
        logger.debug(
            "[vix-alloc] %s: VIX=%.1f HIGH but type=%s — no scaling",
            profile_name, vix, strategy_type,
        )
        return signals, 1.0

    scaled = [_scale_signal(s, multiplier) for s in signals]

    logger.warning(
        "[vix-alloc] %s: VIX=%.1f > %.0f, type=%s — scaling %d signals by %.2fx "
        "(size_hints: %s → %s)",
        profile_name,
        vix,
        VIX_HIGH_THRESHOLD,
        strategy_type,
        len(signals),
        multiplier,
        [round(s.size_hint or 0, 3) for s in signals[:4]],
        [round(s.size_hint or 0, 3) for s in scaled[:4]],
    )

    return scaled, multiplier
