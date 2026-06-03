"""
Reduce position size if highly correlated assets already held.

For each open position across all bots: compute rolling 20-day
price correlation. If any existing position has corr > 0.7 with
the new signal: reduce new position size by 50%.
If 2+ correlated positions exist: reduce by 75%.

Uses simple daily return correlation over available bars.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def _daily_returns(bars: list[dict]) -> list[float]:
    """Compute daily returns from a bar list."""
    closes = []
    for b in bars:
        c = b.get("c") or b.get("close")
        if c is not None:
            try:
                closes.append(float(c))
            except (TypeError, ValueError):
                pass
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] != 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
    return returns


def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Compute Pearson correlation coefficient between two series."""
    n = min(len(x), len(y))
    if n < 5:
        return None

    x = x[-n:]
    y = y[-n:]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    std_x = math.sqrt(sum((v - mean_x) ** 2 for v in x))
    std_y = math.sqrt(sum((v - mean_y) ** 2 for v in y))

    if std_x == 0 or std_y == 0:
        return None

    return cov / (std_x * std_y)


def adjust_size_for_correlation(
    symbol: str,
    intended_pct: float,
    open_symbols: list[str],  # all symbols currently held across all bots
    bars: dict[str, list[dict]],  # bars for symbol + open_symbols
    threshold: float = 0.7,
) -> float:
    """Returns adjusted size_pct."""
    if not open_symbols or symbol not in bars:
        return intended_pct

    symbol_bars = bars.get(symbol, [])
    if not symbol_bars:
        return intended_pct

    # Use last 20 bars for correlation window
    sym_returns = _daily_returns(symbol_bars[-21:] if len(symbol_bars) >= 21 else symbol_bars)
    if not sym_returns:
        return intended_pct

    correlated_count = 0
    for held_symbol in open_symbols:
        if held_symbol == symbol:
            continue
        held_bars = bars.get(held_symbol, [])
        if not held_bars:
            continue
        held_returns = _daily_returns(held_bars[-21:] if len(held_bars) >= 21 else held_bars)
        if not held_returns:
            continue

        corr = _pearson_correlation(sym_returns, held_returns)
        if corr is not None and abs(corr) > threshold:
            correlated_count += 1
            logger.debug(
                "[corr_sizer:%s] correlated with %s: corr=%.3f (threshold=%.2f)",
                symbol, held_symbol, corr, threshold,
            )

    if correlated_count == 0:
        return intended_pct
    elif correlated_count == 1:
        adjusted = intended_pct * 0.5
        logger.info(
            "[corr_sizer:%s] 1 correlated position → 50%% reduction: %.4f → %.4f",
            symbol, intended_pct, adjusted,
        )
        return adjusted
    else:  # 2+
        adjusted = intended_pct * 0.25
        logger.info(
            "[corr_sizer:%s] %d correlated positions → 75%% reduction: %.4f → %.4f",
            symbol, correlated_count, intended_pct, adjusted,
        )
        return adjusted
