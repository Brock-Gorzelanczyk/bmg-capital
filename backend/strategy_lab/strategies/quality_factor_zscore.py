"""
Quality Factor Z-Score Strategy.

Novy-Marx (2013) "The Other Side of Value: The Gross Profitability Premium",
Journal of Financial Economics 108(1): 1-28.

NOTE: This is a proxy implementation using price/return data until a
fundamental data feed (FMP, XBRL, or Alpaca fundamentals) is wired.

Proxy quality signal:
  - Quality = 0.5 × (12-1M momentum z-score) + 0.5 × (low-vol factor z-score)
  - Low-vol factor: inverse of realized vol over lookback period (lower vol = higher quality proxy)
  - Z-score computed cross-sectionally across the full universe in this scan

Entry: z_score > 1.0 (top ~16% of universe)
size_hint: min(0.9, (z_score - 1.0) / 3.0 + 0.5)

Replace with FMP/XBRL feed for production. Fields to use:
  GP/A = (revenue - COGS) / total_assets
  ROE = net_income / book_equity
  D/E = total_debt / book_equity  (low D/E = quality)

Strategy name: quality_factor_zscore
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "quality_factor_zscore"

# NOTE: Proxy for GP/A + ROE until fundamental data feed wired.
# Replace with FMP/XBRL feed for production.
PROXY_NOTE = "Quality proxy via momentum + low-vol composite (replace with GP/A+ROE for prod)"

# Lookback for momentum (12 months ≈ 252 days, skip 1 month ≈ 21 days)
MOMENTUM_LOOKBACK = 252
MOMENTUM_SKIP = 21

# Lookback for realized vol (used as low-vol proxy)
VOL_LOOKBACK = 63

# Entry threshold
Z_THRESHOLD = 1.0

# Max size hint
MAX_SIZE_HINT = 0.9


def _compute_momentum_score(closes: list[float]) -> Optional[float]:
    """12-1 month momentum: return over [-(252+21), -21] window."""
    required = MOMENTUM_LOOKBACK + MOMENTUM_SKIP + 1
    if len(closes) < required:
        return None
    start = closes[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]
    end = closes[-MOMENTUM_SKIP - 1]
    if start <= 0:
        return None
    return (end - start) / start


def _compute_vol_score(closes: list[float]) -> Optional[float]:
    """63-day realized vol (annualized). Returns None if insufficient data."""
    if len(closes) < VOL_LOOKBACK + 1:
        if len(closes) < 10:
            return None
        window = closes[-len(closes):]
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
    """Compute cross-sectional z-score for a list of raw values."""
    n = len(values)
    if n < 2:
        return [0.0] * n
    mean_v = sum(values) / n
    variance = sum((v - mean_v) ** 2 for v in values) / n
    std_v = math.sqrt(variance) if variance > 1e-12 else 1.0
    return [(v - mean_v) / std_v for v in values]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Generate quality factor buy signals using cross-sectional z-scores.

    Uses a proxy quality composite until a fundamental data feed is available:
      quality = 0.5 × momentum_z + 0.5 × low_vol_z

    Note: low_vol_z uses inverse vol so higher quality = lower vol.
    """
    # Compute raw scores for each symbol
    symbol_data: list[dict] = []

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0) or 0) for b in bar_list]
        closes = [c for c in closes if c > 0]
        if not closes:
            continue

        mom_score = _compute_momentum_score(closes)
        vol_score = _compute_vol_score(closes)

        if mom_score is None or vol_score is None:
            logger.debug("[quality_z] %s: insufficient data — skipping", symbol)
            continue

        symbol_data.append({
            "symbol": symbol,
            "momentum": mom_score,
            "vol": vol_score,  # lower is better → will invert for z-score
        })

    if len(symbol_data) < 3:
        logger.debug("[quality_z] insufficient universe (need ≥3 symbols with data)")
        return []

    # Cross-sectional z-scores
    mom_vals = [d["momentum"] for d in symbol_data]
    # Invert vol: lower vol = higher quality → negative vol gets high z-score
    neg_vol_vals = [-d["vol"] for d in symbol_data]

    mom_zscores = _cross_sectional_zscore(mom_vals)
    vol_zscores = _cross_sectional_zscore(neg_vol_vals)

    # Composite quality z-score
    signals: List[Signal] = []
    for i, d in enumerate(symbol_data):
        composite_z = 0.5 * mom_zscores[i] + 0.5 * vol_zscores[i]

        if composite_z <= Z_THRESHOLD:
            continue

        size_hint = min(MAX_SIZE_HINT, (composite_z - Z_THRESHOLD) / 3.0 + 0.5)
        reason = (
            f"Quality z-score {composite_z:.2f} (top quintile proxy via "
            f"momentum + low-vol composite)"
        )

        signals.append(Signal(
            symbol=d["symbol"],
            side="buy",
            confidence=min(0.90, 0.55 + (composite_z - Z_THRESHOLD) * 0.1),
            size_hint=size_hint,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
        logger.debug("[quality_z] %s: composite_z=%.2f → buy", d["symbol"], composite_z)

    logger.info(
        "[quality_z] %d/%d symbols → %d buy signals (z>%.1f)",
        len(symbol_data), len(bars), len(signals), Z_THRESHOLD,
    )
    return signals
