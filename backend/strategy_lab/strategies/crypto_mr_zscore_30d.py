"""
Crypto Mean Reversion — 30-Day Z-Score.

21-63 day mean reversion strategy for top-20 crypto assets.

Signal logic:
  - Compute 30-day z-score: z = (price - mean_30d) / std_30d
  - Enter LONG when z < -2.0 (price more than 2 std devs below 30d mean)
  - Exit / SELL signal when z > -0.5 (price recovered toward mean)
  - Falling-knife filter: skip LONG if 21-day return < -30%
    (don't catch a falling knife — structural breakdown, not mean reversion)

size_hint scales with z-score severity:
  size_hint = min(0.9, (abs(z_score) - 2.0) / 2.0 + 0.55)

Cadence: every 4 hours (per crypto_meanrev_2163.yaml profile).

Strategy name: crypto_mr_zscore_30d
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_mr_zscore_30d"

# Z-score windows
ZSCORE_WINDOW = 30      # 30-day mean and std
FALLING_KNIFE_WINDOW = 21  # 21-day return check
FALLING_KNIFE_THRESHOLD = -0.30  # -30% → skip

# Entry / exit thresholds
ENTRY_Z_THRESHOLD = -2.0   # enter long when z < -2.0
EXIT_Z_THRESHOLD = -0.5    # exit (sell signal) when z > -0.5

# Size hint bounds
MIN_ENTRY_SIZE = 0.55
MAX_SIZE_HINT = 0.9


def _compute_zscore(closes: list[float], window: int) -> Optional[tuple[float, float, float]]:
    """Compute z-score of latest price against window-day mean/std.

    Returns (z_score, mean, std) or None if insufficient data.
    """
    if len(closes) < window + 1:
        return None
    window_closes = closes[-window:]
    n = len(window_closes)
    mean_p = sum(window_closes) / n
    variance = sum((p - mean_p) ** 2 for p in window_closes) / n
    std_p = math.sqrt(variance) if variance > 1e-12 else 1.0
    current_price = closes[-1]
    z = (current_price - mean_p) / std_p
    return z, mean_p, std_p


def _compute_21d_return(closes: list[float]) -> Optional[float]:
    """21-day price return for falling-knife filter."""
    if len(closes) < FALLING_KNIFE_WINDOW + 1:
        return None
    start = closes[-(FALLING_KNIFE_WINDOW + 1)]
    end = closes[-1]
    if start <= 0:
        return None
    return (end - start) / start


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Generate crypto mean reversion signals with z-score entry and falling-knife filter."""
    signals: List[Signal] = []

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue

        closes = [float(b.get("c", 0) or 0) for b in bar_list]
        closes = [c for c in closes if c > 0]
        if not closes:
            continue

        zscore_result = _compute_zscore(closes, ZSCORE_WINDOW)
        if zscore_result is None:
            logger.debug("[crypto_mr] %s: insufficient data (need %d, have %d)",
                         symbol, ZSCORE_WINDOW + 1, len(closes))
            continue

        z, mean_p, std_p = zscore_result
        ret_21d = _compute_21d_return(closes)

        # ── Exit / Sell signal: z recovered above -0.5 ───────────────────────
        # This is a closing signal — we're telling the execution layer
        # "this symbol has mean-reverted, time to exit a long position"
        if z > EXIT_Z_THRESHOLD:
            reason = (
                f"Crypto MR 30d: z-score recovered to {z:.2f} > {EXIT_Z_THRESHOLD}, "
                f"exit long {symbol}"
            )
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=min(0.85, 0.60 + (z + EXIT_Z_THRESHOLD) * 0.05),
                size_hint=1.0,  # close full position
                reason=reason,
                strategy=STRATEGY_NAME,
            ))
            logger.debug("[crypto_mr] %s: z=%.2f → SELL (exit long)", symbol, z)
            continue

        # ── Entry / Buy signal: z < -2.0 ─────────────────────────────────────
        if z >= ENTRY_Z_THRESHOLD:
            # z is between EXIT_Z and ENTRY_Z — no action
            continue

        # Falling-knife filter: don't enter if 21d trend < -30%
        if ret_21d is not None and ret_21d < FALLING_KNIFE_THRESHOLD:
            logger.debug(
                "[crypto_mr] %s: z=%.2f meets entry but 21d ret=%.1%% < %.0%% falling-knife, skip",
                symbol, z, ret_21d, FALLING_KNIFE_THRESHOLD,
            )
            reason_skip = (
                f"Crypto MR 30d: z={z:.2f} on {symbol}, 30d mean {mean_p:.2f}, "
                f"std {std_p:.2f}. Falling-knife check: 21d ret {ret_21d:+.1%} "
                f"< {FALLING_KNIFE_THRESHOLD:.0%} threshold — SKIP"
            )
            logger.info("[crypto_mr] %s: falling-knife filter triggered — no signal", symbol)
            continue

        # Size hint scales with severity of z-score
        size_hint = min(MAX_SIZE_HINT, (abs(z) - abs(ENTRY_Z_THRESHOLD)) / 2.0 + MIN_ENTRY_SIZE)

        ret_21d_str = f"{ret_21d:+.1%}" if ret_21d is not None else "N/A"
        reason = (
            f"Crypto MR 30d: z={z:.2f} on {symbol}, "
            f"30d mean {mean_p:.2f}, std {std_p:.2f}. "
            f"Falling-knife check: 21d ret {ret_21d_str}"
        )

        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=min(0.88, 0.55 + (abs(z) - abs(ENTRY_Z_THRESHOLD)) * 0.08),
            size_hint=size_hint,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
        logger.debug("[crypto_mr] %s: z=%.2f → BUY (size_hint=%.2f)", symbol, z, size_hint)

    logger.info(
        "[crypto_mr_zscore_30d] %d signals from %d symbols",
        len(signals), len(bars),
    )
    return signals
