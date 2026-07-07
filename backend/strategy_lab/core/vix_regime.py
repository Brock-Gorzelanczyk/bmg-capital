"""VIX / VIX3M term-structure regime gate.

Contango (VIX < VIX3M, ratio < 0.95): normal market, short-vol strategies
   have positive expected value. All options short-vol bots ENABLED.

Backwardation (VIX > VIX3M, ratio > 1.0): stress regime, short-vol
   strategies get run over. All short-vol bots DISABLED. Long-vol tail
   hedges take priority.

Neutral (0.95 <= ratio <= 1.0): no strong signal. Bots continue at
   reduced size (0.5x).

Reference: Simon & Campasano 2014; Bakshi-Crosby-Gao SSRN 3930703.
Documented to ~2x Sharpe of unfiltered short-vol strategies.

Usage:
    from strategy_lab.core.vix_regime import get_vix_regime_multiplier
    mult = get_vix_regime_multiplier()  # 1.0, 0.5, or 0.0
    if mult == 0.0:
        # backwardation — skip short-vol entries
        return
    size_hint *= mult
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE: dict = {"ts": None, "multiplier": 1.0, "ratio": None}
_CACHE_TTL_SECONDS = 900  # 15 min


def _fetch_ratio() -> Optional[float]:
    """Return VIX / VIX3M ratio from yfinance. None on any failure."""
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[vix_regime] yfinance import failed: %s", exc)
        return None

    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        vix = yf.Ticker("^VIX").history(start=start, end=end, interval="1d")
        vix3m = yf.Ticker("^VIX3M").history(start=start, end=end, interval="1d")
        if vix is None or vix3m is None or vix.empty or vix3m.empty:
            return None
        vix_last = float(vix["Close"].iloc[-1])
        vix3m_last = float(vix3m["Close"].iloc[-1])
        if vix3m_last <= 0:
            return None
        return vix_last / vix3m_last
    except Exception as exc:
        logger.warning("[vix_regime] fetch failed: %s", exc)
        return None


def get_vix_regime_multiplier(force_refresh: bool = False) -> float:
    """Return size multiplier for short-vol options entries.

    Returns:
      1.0 — contango (ratio < 0.95); short-vol favored
      0.5 — neutral (0.95 <= ratio <= 1.0); half size
      0.0 — backwardation (ratio > 1.0); skip entries entirely

    Cached 15 min. Returns 1.0 on any fetch failure (fail-open).
    """
    now = datetime.now(timezone.utc)
    if (not force_refresh
        and _CACHE["ts"] is not None
        and (now - _CACHE["ts"]).total_seconds() < _CACHE_TTL_SECONDS):
        return _CACHE["multiplier"]

    ratio = _fetch_ratio()
    if ratio is None:
        logger.warning("[vix_regime] ratio fetch failed — defaulting to 1.0")
        _CACHE["ts"] = now
        _CACHE["multiplier"] = 1.0
        _CACHE["ratio"] = None
        return 1.0

    if ratio < 0.95:
        mult = 1.0
        regime = "contango"
    elif ratio > 1.00:
        mult = 0.0
        regime = "backwardation"
    else:
        mult = 0.5
        regime = "neutral"

    logger.warning(
        "[vix_regime] VIX/VIX3M=%.3f -> %s regime -> size multiplier=%.2f",
        ratio, regime, mult,
    )
    _CACHE["ts"] = now
    _CACHE["multiplier"] = mult
    _CACHE["ratio"] = ratio
    return mult
