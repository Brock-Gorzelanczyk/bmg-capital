"""
Google Trends / SVI Signal — Weekend 8, Module 24.

Search Volume Index (SVI) from Google Trends predicts short-term price pressure.
Da, Engelberg & Gao (2011) J. Finance: retail investor attention drives prices up
over 2 weeks then reverses.

Algorithm:
  1. Fetch weekly SVI for ticker symbol from pytrends
  2. Normalize to ASVI: (SVI_this_week - SVI_prior_8_weeks_avg) / SVI_prior_8_weeks_avg
  3. ASVI > 0.5σ → entry signal (momentum, 14-day hold)
  4. ASVI > 1.5σ → approaching reversal zone (reduce/exit existing)

Predictive edge: active in small/mid-cap only.
Large-cap (SPY, AAPL, MSFT): already priced in by HFT.
Filter: only apply to stocks with market cap < $5B.

Reference: Da, Engelberg & Gao (2011), "In Search of Attention",
           Journal of Finance 66(5):1461-1499.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

ASVI_ENTRY_THRESHOLD = 0.50      # entry: attention spike > 0.5 std
ASVI_REVERSAL_THRESHOLD = 1.50   # reversal: attention too high > 1.5 std
LOOKBACK_WEEKS = 8               # baseline window
HOLD_DAYS = 14                   # typical holding period

# Rate limiting: pytrends is free but rate-limited
_LAST_REQUEST_TS = 0.0
_MIN_REQUEST_INTERVAL = 2.0      # seconds between requests


@dataclass
class SVISignal:
    symbol: str
    svi_current: float
    svi_baseline_avg: float
    asvi: float                  # abnormal SVI (z-score)
    signal: str                  # "entry" | "reversal" | "neutral" | "exit_watch"
    confidence: str              # "high" | "medium" | "low"
    hold_days: int
    source: str


def _fetch_pytrends(symbol: str, weeks: int = LOOKBACK_WEEKS + 2) -> Optional[list[float]]:
    """
    Fetch Google Trends SVI using pytrends library.
    Rate-limited — uses global cooldown.
    """
    global _LAST_REQUEST_TS
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.debug("[svi] pytrends not installed")
        return None

    elapsed = time.time() - _LAST_REQUEST_TS
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    try:
        pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25), retries=2)
        pt.build_payload(
            kw_list=[f"{symbol} stock"],
            cat=7,              # category: Finance
            timeframe=f"today {weeks}-w",
            geo="US",
        )
        df = pt.interest_over_time()
        _LAST_REQUEST_TS = time.time()

        if df.empty:
            return None

        col = f"{symbol} stock"
        if col not in df.columns:
            col = df.columns[0]

        values = df[col].tolist()
        return [float(v) for v in values]
    except Exception as exc:
        logger.debug("[svi] pytrends error for %s: %s", symbol, exc)
        return None


def compute_asvi(svi_series: list[float], lookback: int = LOOKBACK_WEEKS) -> float:
    """
    Compute Abnormal SVI: (current - baseline_mean) / baseline_std.

    Returns z-score. Positive = attention spike above normal.
    """
    if len(svi_series) < lookback + 1:
        return 0.0

    current = svi_series[-1]
    baseline = svi_series[-(lookback + 1):-1]
    baseline_mean = float(np.mean(baseline))
    baseline_std = float(np.std(baseline))

    if baseline_std < 1e-6:
        return 0.0

    return round((current - baseline_mean) / baseline_std, 3)


def get_svi_signal(
    symbol: str,
    market_cap_usd: Optional[float] = None,
) -> SVISignal:
    """
    Get SVI-based attention signal for a symbol.

    Parameters
    ----------
    symbol : ticker (best for small/mid cap)
    market_cap_usd : if provided, skips analysis for stocks > $5B (alpha decayed)

    Returns
    -------
    SVISignal
    """
    # Skip large-cap — alpha decayed for AAPL, MSFT, etc.
    if market_cap_usd is not None and market_cap_usd > 5_000_000_000:
        return SVISignal(
            symbol=symbol,
            svi_current=0.0,
            svi_baseline_avg=0.0,
            asvi=0.0,
            signal="neutral",
            confidence="low",
            hold_days=HOLD_DAYS,
            source="skipped_large_cap",
        )

    svi_series = _fetch_pytrends(symbol)
    if svi_series is None or len(svi_series) < LOOKBACK_WEEKS + 1:
        return SVISignal(
            symbol=symbol,
            svi_current=0.0,
            svi_baseline_avg=0.0,
            asvi=0.0,
            signal="neutral",
            confidence="low",
            hold_days=HOLD_DAYS,
            source="no_data",
        )

    asvi = compute_asvi(svi_series)
    current = svi_series[-1]
    baseline = float(np.mean(svi_series[-(LOOKBACK_WEEKS + 1):-1]))

    if asvi >= ASVI_REVERSAL_THRESHOLD:
        signal = "exit_watch"       # attention bubble — prepare to exit / fade
        confidence = "high"
    elif asvi >= ASVI_ENTRY_THRESHOLD:
        signal = "entry"            # attention rising — potential 2-week momentum
        confidence = "medium" if asvi < 1.0 else "high"
    elif asvi <= -ASVI_ENTRY_THRESHOLD:
        signal = "fading"           # attention below baseline — sentiment cooling
        confidence = "low"
    else:
        signal = "neutral"
        confidence = "low"

    logger.info(
        "[svi] %s ASVI=%.3f current=%.0f baseline=%.0f signal=%s",
        symbol, asvi, current, baseline, signal,
    )

    return SVISignal(
        symbol=symbol,
        svi_current=round(current, 1),
        svi_baseline_avg=round(baseline, 1),
        asvi=asvi,
        signal=signal,
        confidence=confidence,
        hold_days=HOLD_DAYS,
        source="google_trends",
    )


def batch_scan(
    symbols: list[str],
    market_caps: Optional[dict[str, float]] = None,
    min_asvi: float = ASVI_ENTRY_THRESHOLD,
) -> list[SVISignal]:
    """
    Scan multiple symbols and return those with significant ASVI.
    Rate-limited: plan for ~2s per symbol.
    """
    signals = []
    for symbol in symbols:
        mc = (market_caps or {}).get(symbol)
        sig = get_svi_signal(symbol, mc)
        if abs(sig.asvi) >= min_asvi:
            signals.append(sig)
    return signals
