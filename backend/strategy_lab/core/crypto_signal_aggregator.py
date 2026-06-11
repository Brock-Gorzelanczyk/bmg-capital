"""
Crypto Signal Aggregator — single import for all crypto candidate strategies.

Combines:
  - Cycle phase + position_size_multiplier from crypto_cycle_detector
  - ETF flow size multiplier from altdata.btc_etf_flow
  - Stablecoin dominance size multiplier from altdata.stablecoin_flow

Produces a `combined_size_multiplier` clamped to [0.3, 1.5].

This is the SINGLE module that new crypto candidate strategies import for
their regime snapshot. Do NOT import the sub-modules directly in candidates.

Cache TTL: 60 minutes (aligned with sub-module caches).
"""
from __future__ import annotations

import logging
import time

from strategy_lab.core.crypto_cycle_detector import detect_crypto_regime
from strategy_lab.core.altdata.btc_etf_flow import get_btc_etf_flow_signal
from strategy_lab.core.altdata.stablecoin_flow import get_stablecoin_dominance

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600  # 60 minutes

_cache: dict = {
    "snapshot": None,
    "fetched_at": 0.0,
}

_COMBINED_MULTIPLIER_MIN = 0.3
_COMBINED_MULTIPLIER_MAX = 1.5


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def get_crypto_regime_snapshot(force_refresh: bool = False) -> dict:
    """
    Return a merged crypto regime snapshot combining cycle, ETF flow,
    and stablecoin dominance signals.

    Parameters
    ----------
    force_refresh : bool
        Bypass the in-memory cache and re-fetch all sub-signals.

    Returns
    -------
    dict — all keys from detect_crypto_regime() PLUS:
        etf_flow_signal         : str  (e.g. "bullish")
        etf_flow_size_mult      : float
        stablecoin_regime       : str  (e.g. "risk_off")
        stablecoin_size_mult    : float
        combined_size_multiplier: float  (clamped to [0.3, 1.5])

    On sub-module failure: falls back to neutral multiplier (1.0) for that source.
    """
    now_ts = time.monotonic()

    if (
        not force_refresh
        and _cache["snapshot"] is not None
        and (now_ts - _cache["fetched_at"]) < _CACHE_TTL_SECONDS
    ):
        return _cache["snapshot"]

    # ── Cycle regime (primary) ────────────────────────────────────────────────
    try:
        cycle = detect_crypto_regime()
    except Exception as exc:
        logger.warning("[crypto_aggregator] detect_crypto_regime failed: %s", exc)
        from strategy_lab.core.crypto_cycle_detector import _SAFE_DEFAULTS
        cycle = dict(_SAFE_DEFAULTS)

    cycle_multiplier = float(cycle.get("position_size_multiplier", 1.0))

    # ── ETF flow ──────────────────────────────────────────────────────────────
    try:
        etf_data = get_btc_etf_flow_signal()
        etf_signal = etf_data.get("signal", "neutral")
        etf_multiplier = float(etf_data.get("size_multiplier", 1.0))
    except Exception as exc:
        logger.warning("[crypto_aggregator] btc_etf_flow failed: %s", exc)
        etf_signal = "neutral"
        etf_multiplier = 1.0

    # ── Stablecoin dominance ──────────────────────────────────────────────────
    try:
        stable_data = get_stablecoin_dominance()
        stable_regime = stable_data.get("regime", "neutral")
        stable_multiplier = float(stable_data.get("size_multiplier", 1.0))
    except Exception as exc:
        logger.warning("[crypto_aggregator] stablecoin_dominance failed: %s", exc)
        stable_regime = "neutral"
        stable_multiplier = 1.0

    # ── Combine ───────────────────────────────────────────────────────────────
    raw_combined = cycle_multiplier * etf_multiplier * stable_multiplier
    combined = round(_clamp(raw_combined, _COMBINED_MULTIPLIER_MIN, _COMBINED_MULTIPLIER_MAX), 4)

    snapshot = {
        **cycle,
        "etf_flow_signal": etf_signal,
        "etf_flow_size_mult": etf_multiplier,
        "stablecoin_regime": stable_regime,
        "stablecoin_size_mult": stable_multiplier,
        "combined_size_multiplier": combined,
    }

    _cache["snapshot"] = snapshot
    _cache["fetched_at"] = now_ts

    logger.info(
        "[crypto_aggregator] phase=%s cycle_mult=%.2f etf_mult=%.2f "
        "stable_mult=%.2f combined=%.2f",
        snapshot.get("cycle_phase", "?"),
        cycle_multiplier,
        etf_multiplier,
        stable_multiplier,
        combined,
    )

    return snapshot
