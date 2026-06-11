"""
Crypto on-chain regime detector — standalone cycle classifier for BTC/alt markets.

Does NOT replace regime_detector.py. Produces a cycle-aware regime dict with
crypto-specific keys (cycle_phase, btc_dominance, fear_greed, funding, altcoin_season).
Results are cached in-memory for 60 minutes (called every 5min by quant_aggressive).

Data sources (all fail-gracefully to neutral defaults):
  - BTC dominance: CoinGecko /global
  - Fear & Greed:  alternative.me /fng
  - Funding rate:  Coinglass (COINGLASS_API_KEY) → Binance futures fallback
  - MVRV Z-score:  CoinMetrics community API (best-effort)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 3600  # 60 minutes

_cache: dict = {
    "regime": None,
    "fetched_at": 0.0,
}

_SAFE_DEFAULTS: dict = {
    "vix_regime": "low",
    "trend_regime": "chop",
    "cycle_phase": "mid_bull",
    "btc_dominance": 50.0,
    "btc_dom_trend": "neutral",
    "mvrv_z_score": None,
    "fear_greed_value": 50,
    "fear_greed_class": "Neutral",
    "funding_rate_8h": 0.0,
    "funding_signal": "normal",
    "altcoin_season": False,
    "rotation_stage": 2,
    "position_size_multiplier": 1.0,
    "cycle_confidence": 0.5,
}

# ── Sub-caches for individual data sources ────────────────────────────────────

_dom_cache: dict = {"value": None, "fetched_at": 0.0, "ttl": 3600}
_fg_cache: dict = {"values": None, "fetched_at": 0.0, "ttl": 3600}
_funding_cache: dict = {"value": None, "fetched_at": 0.0, "ttl": 900}
_mvrv_cache: dict = {"value": None, "fetched_at": 0.0, "ttl": 3600}


def _fetch_btc_dominance() -> Optional[float]:
    """Fetch BTC dominance from CoinGecko. Cached 1 hour."""
    now = time.monotonic()
    if _dom_cache["value"] is not None and (now - _dom_cache["fetched_at"]) < _dom_cache["ttl"]:
        return _dom_cache["value"]
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("[crypto_cycle] CoinGecko /global returned %d", resp.status_code)
            return _dom_cache["value"]
        data = resp.json()
        btc_pct = data.get("data", {}).get("market_cap_percentage", {}).get("btc")
        if btc_pct is None:
            return _dom_cache["value"]
        value = round(float(btc_pct), 2)
        _dom_cache["value"] = value
        _dom_cache["fetched_at"] = now
        return value
    except Exception as exc:
        logger.warning("[crypto_cycle] BTC dominance fetch failed: %s", exc)
        return _dom_cache["value"]


def _fetch_fear_greed(limit: int = 7) -> list[dict]:
    """Fetch last `limit` days of Fear & Greed index. Cached 1 hour."""
    now = time.monotonic()
    if _fg_cache["values"] is not None and (now - _fg_cache["fetched_at"]) < _fg_cache["ttl"]:
        return _fg_cache["values"]
    try:
        resp = requests.get(
            f"https://api.alternative.me/fng/?limit={limit}&format=json",
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("[crypto_cycle] Fear&Greed returned %d", resp.status_code)
            return _fg_cache["values"] or []
        entries = resp.json().get("data", [])
        _fg_cache["values"] = entries
        _fg_cache["fetched_at"] = now
        return entries
    except Exception as exc:
        logger.warning("[crypto_cycle] Fear&Greed fetch failed: %s", exc)
        return _fg_cache["values"] or []


def _fetch_funding_rate_coinglass() -> Optional[float]:
    """
    Fetch BTC 8h funding rate from Coinglass.
    Uses COINGLASS_API_KEY env var (same pattern as ortex_squeeze_signals).
    """
    try:
        api_key = os.getenv("COINGLASS_API_KEY", "")
        if not api_key:
            return None
        url = "https://open-api.coinglass.com/public/v2/funding"
        headers = {"coinglassSecret": api_key}
        params = {"symbol": "BTC"}
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code != 200:
            logger.warning("[crypto_cycle] Coinglass funding returned %d", resp.status_code)
            return None
        data = resp.json()
        # data.data is a list; pick the Binance row for BTCUSDT
        rows = data.get("data", [])
        for row in rows:
            if row.get("exchangeName", "").lower() == "binance":
                rate = row.get("rate")
                if rate is not None:
                    return float(rate)
        # Fallback to first available row
        if rows and rows[0].get("rate") is not None:
            return float(rows[0]["rate"])
        return None
    except Exception as exc:
        logger.debug("[crypto_cycle] Coinglass funding error: %s", exc)
        return None


def _fetch_funding_rate_binance() -> Optional[float]:
    """Fallback: fetch BTC funding rate from Binance futures public API."""
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": "BTCUSDT", "limit": 3},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("[crypto_cycle] Binance fundingRate returned %d", resp.status_code)
            return None
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            return float(data[-1].get("fundingRate", 0.0))
        return None
    except Exception as exc:
        logger.warning("[crypto_cycle] Binance funding rate fetch failed: %s", exc)
        return None


def _fetch_funding_rate() -> float:
    """Fetch BTC 8h funding rate. Coinglass → Binance fallback. Cached 15 min."""
    now = time.monotonic()
    if _funding_cache["value"] is not None and (now - _funding_cache["fetched_at"]) < _funding_cache["ttl"]:
        return _funding_cache["value"]
    value = _fetch_funding_rate_coinglass()
    if value is None:
        value = _fetch_funding_rate_binance()
    if value is None:
        value = _funding_cache["value"] if _funding_cache["value"] is not None else 0.0
    _funding_cache["value"] = value
    _funding_cache["fetched_at"] = now
    return value


def _fetch_mvrv_z_score() -> Optional[float]:
    """
    Fetch BTC MVRV Z-Score from CoinMetrics community API.
    Best-effort: returns None on any failure.
    Cached 1 hour.
    """
    now = time.monotonic()
    if _mvrv_cache["fetched_at"] > 0 and (now - _mvrv_cache["fetched_at"]) < _mvrv_cache["ttl"]:
        return _mvrv_cache["value"]
    try:
        url = (
            "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
            "?assets=btc&metrics=CapMVRVCur&frequency=1d&limit=2"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.warning("[crypto_cycle] CoinMetrics MVRV returned %d", resp.status_code)
            _mvrv_cache["fetched_at"] = now
            return None
        data = resp.json()
        series = data.get("data", [])
        if not series:
            _mvrv_cache["fetched_at"] = now
            return None
        # CapMVRVCur is the raw MVRV ratio; CoinMetrics community doesn't expose
        # the true Z-score, so we treat the ratio as a proxy.
        latest = series[-1]
        raw = latest.get("CapMVRVCur")
        if raw is None:
            _mvrv_cache["fetched_at"] = now
            return None
        value = round(float(raw), 4)
        _mvrv_cache["value"] = value
        _mvrv_cache["fetched_at"] = now
        return value
    except Exception as exc:
        logger.warning("[crypto_cycle] MVRV fetch failed: %s", exc)
        _mvrv_cache["fetched_at"] = now
        return _mvrv_cache.get("value")


# ── Scoring & classification helpers ─────────────────────────────────────────

def _classify_cycle_phase(
    fear_greed: int,
    btc_dominance: float,
    funding_rate_8h: float,
    mvrv_z_score: Optional[float],
) -> tuple[str, float]:
    """
    Score-based cycle phase classification.
    Returns (cycle_phase, cycle_confidence).
    """
    score = 0

    if fear_greed < 20:
        score -= 2
    elif fear_greed > 80:
        score += 2

    if btc_dominance > 58:
        score -= 1
    elif btc_dominance < 45:
        score += 1

    if funding_rate_8h > 0.08:
        score += 2
    elif funding_rate_8h < 0:
        score -= 1

    if mvrv_z_score is not None:
        if mvrv_z_score < 1.0:
            score -= 2
        elif mvrv_z_score > 5.0:
            score += 3

    if score <= -3:
        phase = "accumulation"
    elif score <= -1:
        phase = "early_bull"
    elif score <= 1:
        phase = "mid_bull"
    elif score <= 3:
        phase = "parabolic"
    else:
        phase = "distribution"

    # Confidence: how strongly the signals agree
    max_possible_score = 8  # sum of all positive contributions
    confidence = min(1.0, abs(score) / max(1, max_possible_score / 2))
    confidence = round(confidence, 3)

    return phase, confidence


def _rotation_stage(btc_dominance: float) -> int:
    if btc_dominance > 55:
        return 1
    if btc_dominance > 50:
        return 2
    if btc_dominance > 46:
        return 3
    if btc_dominance > 42:
        return 4
    return 5


def _size_multiplier(cycle_phase: str) -> float:
    mapping = {
        "accumulation": 1.3,
        "early_bull": 1.2,
        "mid_bull": 1.0,
        "parabolic": 0.8,
        "distribution": 0.4,
        "bear": 0.3,
    }
    return mapping.get(cycle_phase, 1.0)


def _trend_regime_from_phase(cycle_phase: str) -> str:
    if cycle_phase in ("early_bull", "mid_bull", "parabolic"):
        return "bull"
    if cycle_phase in ("distribution", "bear"):
        return "bear"
    return "chop"


def _btc_dom_trend(fg_history: list[dict]) -> str:
    """Estimate BTC dominance trend from Fear & Greed momentum proxy.
    Proper implementation would track dominance time-series; here we use
    a simplified proxy from the last 7 days of F&G direction."""
    if len(fg_history) < 4:
        return "neutral"
    try:
        recent = int(fg_history[0].get("value", 50))
        older = int(fg_history[-1].get("value", 50))
        delta = recent - older
        if delta > 10:
            return "falling"  # high greed → alt season → BTC dom falling
        if delta < -10:
            return "rising"   # fear returning → BTC dom rising
        return "neutral"
    except Exception:
        return "neutral"


# ── Main entry point ──────────────────────────────────────────────────────────

def detect_crypto_regime(profile_config: dict = None) -> dict:
    """
    Return crypto market regime dict. Uses 60-minute in-memory cache.
    Falls back to last cached value (or safe defaults) on any API error.

    Returns
    -------
    dict with keys: vix_regime, trend_regime, cycle_phase, btc_dominance,
    btc_dom_trend, mvrv_z_score, fear_greed_value, fear_greed_class,
    funding_rate_8h, funding_signal, altcoin_season, rotation_stage,
    position_size_multiplier, cycle_confidence.
    """
    now_ts = time.monotonic()

    if _cache["regime"] is not None and (now_ts - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["regime"]

    last_cached = _cache["regime"]

    try:
        regime = _build_regime()
        _cache["regime"] = regime
        _cache["fetched_at"] = now_ts
        logger.info(
            "[crypto_cycle] phase=%s stage=%d fg=%d dom=%.1f funding=%.4f conf=%.2f",
            regime["cycle_phase"],
            regime["rotation_stage"],
            regime["fear_greed_value"],
            regime["btc_dominance"],
            regime["funding_rate_8h"],
            regime["cycle_confidence"],
        )
        return regime
    except Exception as exc:
        logger.error("[crypto_cycle] regime build failed: %s — using cache/defaults", exc)
        return last_cached if last_cached is not None else dict(_SAFE_DEFAULTS)


def _build_regime() -> dict:
    """Core fetch + classification logic."""

    # ── Fetch ─────────────────────────────────────────────────────────────────
    btc_dominance = _fetch_btc_dominance()
    if btc_dominance is None:
        btc_dominance = _SAFE_DEFAULTS["btc_dominance"]

    fg_entries = _fetch_fear_greed(limit=7)
    if fg_entries:
        fear_greed_value = int(fg_entries[0].get("value", 50))
        fear_greed_class = fg_entries[0].get("value_classification", "Neutral")
    else:
        fear_greed_value = _SAFE_DEFAULTS["fear_greed_value"]
        fear_greed_class = _SAFE_DEFAULTS["fear_greed_class"]

    funding_rate_8h = _fetch_funding_rate()

    mvrv_z_score = _fetch_mvrv_z_score()

    # ── Classify ─────────────────────────────────────────────────────────────
    cycle_phase, cycle_confidence = _classify_cycle_phase(
        fear_greed_value, btc_dominance, funding_rate_8h, mvrv_z_score
    )

    dom_trend = _btc_dom_trend(fg_entries)
    stage = _rotation_stage(btc_dominance)
    altcoin_season = btc_dominance < 50 and dom_trend == "falling"
    position_size_multiplier = _size_multiplier(cycle_phase)
    trend_regime = _trend_regime_from_phase(cycle_phase)

    if funding_rate_8h > 0.08:
        funding_signal = "overheated"
    elif funding_rate_8h < 0:
        funding_signal = "bearish_sentiment"
    else:
        funding_signal = "normal"

    return {
        "vix_regime": "low",  # No VIX equivalent in crypto
        "trend_regime": trend_regime,
        "cycle_phase": cycle_phase,
        "btc_dominance": btc_dominance,
        "btc_dom_trend": dom_trend,
        "mvrv_z_score": mvrv_z_score,
        "fear_greed_value": fear_greed_value,
        "fear_greed_class": fear_greed_class,
        "funding_rate_8h": funding_rate_8h,
        "funding_signal": funding_signal,
        "altcoin_season": altcoin_season,
        "rotation_stage": stage,
        "position_size_multiplier": position_size_multiplier,
        "cycle_confidence": cycle_confidence,
    }
