"""
Value-Quality Combo Strategy — AQR QMJ-style.

Based on Asness, Frazzini & Pedersen (2019) "Quality Minus Junk",
Review of Accounting Studies 24(1): 34-112.

Combines:
  - Value proxy: contrarian value — low recent 12M return BUT above 200-day MA
    (low price momentum = cheap, 200d MA filter = not in freefall)
  - Quality proxy: same as quality_factor_zscore — 0.5×momentum_z + 0.5×low-vol_z

Combined z = value_z × 0.5 + quality_z × 0.5
Buy if combined_z > 0.8

size_hint = min(0.9, combined_z / 3.0 + 0.4)

The value proxy deliberately uses INVERSE 12M momentum (contrarian) while
the quality proxy uses DIRECT 12M momentum. The two signals are partially
negatively correlated, which is intentional — QMJ buys cheap-but-quality.

Strategy name: value_quality_combo
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "value_quality_combo"

# Lookbacks
MOMENTUM_LOOKBACK = 252   # 12M
MOMENTUM_SKIP = 21        # skip last month
MA_LOOKBACK = 200         # 200-day moving average
VOL_LOOKBACK = 63         # 3M realized vol

# Entry threshold
COMBINED_Z_THRESHOLD = 0.8

# Max size hint
MAX_SIZE_HINT = 0.9


def _above_200d_ma(closes: list[float]) -> bool:
    """Return True if current price is above 200-day MA."""
    if len(closes) < MA_LOOKBACK:
        return True  # insufficient data → assume filter passes
    ma200 = sum(closes[-MA_LOOKBACK:]) / MA_LOOKBACK
    return closes[-1] > ma200


def _compute_12m_return(closes: list[float]) -> Optional[float]:
    """12-1 month return (value proxy uses INVERSE of this)."""
    required = MOMENTUM_LOOKBACK + MOMENTUM_SKIP + 1
    if len(closes) < required:
        return None
    start = closes[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]
    end = closes[-MOMENTUM_SKIP - 1]
    if start <= 0:
        return None
    return (end - start) / start


def _compute_realized_vol(closes: list[float]) -> Optional[float]:
    """63-day annualized realized vol."""
    if len(closes) < VOL_LOOKBACK + 1:
        if len(closes) < 10:
            return None
        window = closes
    else:
        window = closes[-VOL_LOOKBACK - 1:]

    log_rets = [
        math.log(window[i] / window[i - 1])
        for i in range(1, len(window))
        if window[i - 1] > 0 and window[i] > 0
    ]
    if len(log_rets) < 5:
        return None
    n = len(log_rets)
    mean_r = sum(log_rets) / n
    variance = sum((r - mean_r) ** 2 for r in log_rets) / n
    return math.sqrt(variance) * math.sqrt(252)


def _cross_sectional_zscore(values: list[float]) -> list[float]:
    """Cross-sectional z-score."""
    n = len(values)
    if n < 2:
        return [0.0] * n
    mean_v = sum(values) / n
    variance = sum((v - mean_v) ** 2 for v in values) / n
    std_v = math.sqrt(variance) if variance > 1e-12 else 1.0
    return [(v - mean_v) / std_v for v in values]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Generate value-quality combo buy signals.

    Value proxy (contrarian): inverse of 12M momentum, filtered by 200d MA.
    Quality proxy: same as quality_factor_zscore (momentum + low-vol composite).
    Combined: 0.5×value_z + 0.5×quality_z, buy if combined > 0.8.
    """
    symbol_data: list[dict] = []

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0) or 0) for b in bar_list]
        closes = [c for c in closes if c > 0]
        if not closes:
            continue

        ret_12m = _compute_12m_return(closes)
        vol = _compute_realized_vol(closes)

        if ret_12m is None or vol is None:
            logger.debug("[val_quality] %s: insufficient data — skipping", symbol)
            continue

        # 200d MA filter for value proxy: must be above MA (not in terminal decline)
        above_ma = _above_200d_ma(closes)

        symbol_data.append({
            "symbol": symbol,
            "ret_12m": ret_12m,
            "vol": vol,
            "above_ma": above_ma,
        })

    if len(symbol_data) < 3:
        logger.debug("[val_quality] insufficient universe (need ≥3 symbols with data)")
        return []

    # ── Value z-score: INVERSE of 12M momentum (contrarian, filtered by 200d MA) ─
    # Symbols above 200d MA: value_raw = -ret_12m (cheap = low return)
    # Symbols below 200d MA: value_raw = very negative (penalize falling knives)
    value_raws = [
        -d["ret_12m"] if d["above_ma"] else (-d["ret_12m"] - 2.0)  # penalty for below MA
        for d in symbol_data
    ]
    value_zscores = _cross_sectional_zscore(value_raws)

    # ── Quality z-score: 0.5×momentum_z + 0.5×low-vol_z ─────────────────────
    mom_vals = [d["ret_12m"] for d in symbol_data]
    neg_vol_vals = [-d["vol"] for d in symbol_data]
    mom_zscores = _cross_sectional_zscore(mom_vals)
    low_vol_zscores = _cross_sectional_zscore(neg_vol_vals)
    quality_zscores = [0.5 * m + 0.5 * v for m, v in zip(mom_zscores, low_vol_zscores)]

    # ── Combined z-score ──────────────────────────────────────────────────────
    signals: List[Signal] = []
    for i, d in enumerate(symbol_data):
        vz = value_zscores[i]
        qz = quality_zscores[i]
        combined_z = 0.5 * vz + 0.5 * qz

        if combined_z <= COMBINED_Z_THRESHOLD:
            continue

        size_hint = min(MAX_SIZE_HINT, combined_z / 3.0 + 0.4)
        reason = (
            f"Value-Quality combo z={combined_z:.2f} "
            f"(value_z={vz:.2f} quality_z={qz:.2f}), AQR QMJ-style"
        )

        signals.append(Signal(
            symbol=d["symbol"],
            side="buy",
            confidence=min(0.88, 0.52 + (combined_z - COMBINED_Z_THRESHOLD) * 0.08),
            size_hint=size_hint,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
        logger.debug("[val_quality] %s: combined_z=%.2f (vz=%.2f qz=%.2f) → buy",
                     d["symbol"], combined_z, vz, qz)

    logger.info(
        "[val_quality] %d/%d symbols → %d buy signals (combined_z>%.1f)",
        len(symbol_data), len(bars), len(signals), COMBINED_Z_THRESHOLD,
    )
    return signals
