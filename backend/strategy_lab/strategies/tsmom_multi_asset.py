"""
Time-Series Momentum — Multi-Asset (TSMOM).

Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum",
Journal of Financial Economics 104(2): 228-250.

Vol targeting per Barroso & Santa-Clara (2015)
"Momentum Has Its Moments", JFE 116(1): 111-120.

Signal logic:
  - Equity/bond/commodity ETFs: 252-day total return skipping last 21 days
    (standard momentum skipping most-recent month)
  - Crypto (BTC/USD, ETH/USD): 63-day return (3-month — crypto moves faster)
  - Return > 0 → LONG signal; ≤ 0 → hold (long-only v1, no shorting)
  - Inverse-vol weighting: weight = 1 / realized_vol_63d, normalized to sum=1
  - size_hint = normalized inv-vol weight, capped at 0.9

Schedule: Friday 5PM ET (weekly rebalance).
"""
from __future__ import annotations

import logging
import math
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "tsmom_multi_asset"

# Crypto symbols use shorter lookback (63d vs 252d)
CRYPTO_SYMBOLS: frozenset[str] = frozenset({"BTC/USD", "ETH/USD"})

# Lookback parameters
EQUITY_LOOKBACK_DAYS = 252
EQUITY_SKIP_DAYS = 21        # skip most recent month (skip-1-month convention)
CRYPTO_LOOKBACK_DAYS = 63
CRYPTO_SKIP_DAYS = 0         # crypto: no skip, full 63d signal

# Vol estimation lookback
VOL_LOOKBACK_DAYS = 63       # 3-month realized vol for inv-vol weighting

# Size cap
MAX_SIZE_HINT = 0.9


def _compute_return(closes: list[float], lookback: int, skip: int) -> float | None:
    """Compute total return over [-(lookback+skip), -skip] window.

    Returns None if insufficient data.
    """
    required = lookback + skip + 1
    if len(closes) < required:
        return None
    start_idx = -(lookback + skip)
    end_idx = -skip if skip > 0 else len(closes)
    start_price = closes[start_idx]
    end_price = closes[end_idx - 1] if skip == 0 else closes[-skip - 1]
    if start_price <= 0:
        return None
    return (end_price - start_price) / start_price


def _compute_realized_vol_63d(closes: list[float]) -> float | None:
    """Compute 63-day annualized realized vol from log returns.

    Returns None if fewer than 10 prices available.
    """
    if len(closes) < VOL_LOOKBACK_DAYS + 1:
        if len(closes) < 10:
            return None
        # Use what we have
        window = closes[-min(VOL_LOOKBACK_DAYS, len(closes)):]
    else:
        window = closes[-VOL_LOOKBACK_DAYS - 1:]

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


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Generate TSMOM signals with inverse-vol weighting.

    Returns a List of Signal objects (buy signals only — long-only v1).
    """
    candidates: list[dict] = []

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue

        closes = [float(b.get("c", 0) or 0) for b in bar_list]
        closes = [c for c in closes if c > 0]
        if not closes:
            continue

        is_crypto = symbol in CRYPTO_SYMBOLS
        lookback = CRYPTO_LOOKBACK_DAYS if is_crypto else EQUITY_LOOKBACK_DAYS
        skip = CRYPTO_SKIP_DAYS if is_crypto else EQUITY_SKIP_DAYS

        total_return = _compute_return(closes, lookback, skip)
        if total_return is None:
            logger.debug(
                "[tsmom] %s: insufficient bars (have %d, need %d) — skipping",
                symbol, len(closes), lookback + skip + 1,
            )
            continue

        realized_vol = _compute_realized_vol_63d(closes)
        if realized_vol is None or realized_vol <= 0:
            logger.debug("[tsmom] %s: cannot compute realized vol — skipping", symbol)
            continue

        candidates.append({
            "symbol": symbol,
            "return": total_return,
            "vol": realized_vol,
            "lookback": lookback,
            "skip": skip,
            "is_crypto": is_crypto,
        })

    if not candidates:
        return []

    # ── Inverse-vol weighting ─────────────────────────────────────────────────
    # Only long-eligible symbols (positive momentum signal)
    long_candidates = [c for c in candidates if c["return"] > 0]

    if not long_candidates:
        logger.debug("[tsmom] no positive momentum signals this cycle")
        return []

    # weight_i = 1 / vol_i  (inverse volatility)
    inv_vols = [1.0 / c["vol"] for c in long_candidates]
    total_inv_vol = sum(inv_vols)
    if total_inv_vol <= 0:
        return []

    signals: List[Signal] = []
    for c, inv_vol in zip(long_candidates, inv_vols):
        normalized_weight = inv_vol / total_inv_vol
        size_hint = min(MAX_SIZE_HINT, normalized_weight)

        reason = (
            f"TSMOM long {c['symbol']}: "
            f"{c['lookback']}d-{c['skip']}d return {c['return']:+.1%}, "
            f"inv-vol weight {normalized_weight:.0%}, "
            f"realized_vol {c['vol']:.1%}"
        )

        signals.append(Signal(
            symbol=c["symbol"],
            side="buy",
            confidence=min(0.95, 0.50 + abs(c["return"]) * 2),  # scale with magnitude
            size_hint=size_hint,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
        logger.debug("[tsmom] %s: %s", c["symbol"], reason)

    logger.info(
        "[tsmom] %d/%d symbols → %d LONG signals (inv-vol weighted)",
        len(long_candidates), len(candidates), len(signals),
    )
    return signals
