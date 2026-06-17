"""
Regime detector — classifies market regime from VIX, SPY trend, BTC dominance,
and BTC perp funding rate. Caches results in-memory for 15 minutes.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── In-memory cache ───────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 900  # 15 minutes

_cache: dict = {
    "regime": None,
    "fetched_at": 0.0,
}

_SAFE_DEFAULTS: dict = {
    "vix_regime": "mid",
    "trend_regime": "chop",
    "vol_pctile": 50.0,
    "btc_dominance": 50.0,
    "btc_funding_rate": 0.0,
    "spy_price": None,
    "vix_value": None,
}

# VIX thresholds
_VIX_LOW = 15.0
_VIX_MID = 23.0
_VIX_HIGH = 30.0


def _vix_to_regime(vix: float) -> str:
    if vix < _VIX_LOW:
        return "low"
    if vix < _VIX_MID:
        return "mid"
    if vix < _VIX_HIGH:
        return "high"
    return "panic"


def _vix_to_percentile(vix: float, history: list[float]) -> float:
    """Return 0-100 percentile of current VIX vs 252-day history."""
    if not history:
        return 50.0
    below = sum(1 for v in history if v <= vix)
    return round((below / len(history)) * 100, 1)


def _fetch_alpaca_bars(symbol: str, limit: int = 252, timeframe: str = "1Day") -> list[dict]:
    """Fetch daily bars from Alpaca. Returns list of bar dicts with c (close) key."""
    base_url = os.getenv("ALPACA_BASE_URL", "https://data.alpaca.markets")
    api_key = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_SECRET_KEY", "")

    if not api_key:
        logger.debug("No ALPACA_API_KEY; skipping bar fetch for %s", symbol)
        return []

    url = f"{base_url}/v2/stocks/{symbol}/bars"
    params = {
        "timeframe": timeframe,
        "limit": limit,
        "adjustment": "raw",
        "feed": "iex",
    }
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning("Alpaca bars %s returned %d", symbol, resp.status_code)
            return []
        data = resp.json()
        return data.get("bars") or []
    except Exception as exc:
        logger.warning("Alpaca bars fetch failed for %s: %s", symbol, exc)
        return []


def _compute_adx(closes: list[float], period: int = 14) -> float:
    """Simplified ADX proxy using average of absolute 1d returns."""
    if len(closes) < period + 1:
        return 0.0
    returns = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    recent = returns[-period:]
    return sum(recent) / len(recent) * 100  # scale to ADX-like range


def _compute_trend_regime(bars: list[dict]) -> tuple[str, Optional[float]]:
    """
    Returns (trend_regime, spy_price).
    bull if 200d slope > 0 and ADX > 25, bear if slope < 0 and ADX > 25, else chop.
    """
    if not bars or len(bars) < 201:
        return "chop", None

    closes = [b["c"] for b in bars]
    current_price = closes[-1]

    # 200-day slope: compare mean of last 10 bars vs mean of bars 200-190
    recent_mean = sum(closes[-10:]) / 10
    past_mean = sum(closes[-200:-190]) / 10
    slope_positive = recent_mean > past_mean

    adx = _compute_adx(closes[-30:])

    if adx > 25 and slope_positive:
        return "bull", current_price
    if adx > 25 and not slope_positive:
        return "bear", current_price
    return "chop", current_price


def _fetch_btc_dominance() -> Optional[float]:
    """Fetch BTC dominance from CoinGecko public API."""
    url = "https://api.coingecko.com/api/v3/global"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        market_cap_pct = data.get("data", {}).get("market_cap_percentage", {})
        btc_dom = market_cap_pct.get("btc")
        return round(float(btc_dom), 2) if btc_dom is not None else None
    except Exception as exc:
        logger.warning("CoinGecko dominance fetch failed: %s", exc)
        return None


def _fetch_btc_funding_rate() -> Optional[float]:
    """Fetch latest BTC perp funding rate from Binance public API."""
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {"symbol": "BTCUSDT", "limit": 1}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            return float(data[0].get("fundingRate", 0.0))
        return None
    except Exception as exc:
        logger.warning("Binance funding rate fetch failed: %s", exc)
        return None


def _persist_snapshot(regime: dict, db=None) -> None:
    """Persist a RegimeSnapshot to DB if >15 minutes since the last one."""
    if db is None:
        return
    try:
        from app.db.models.bots import RegimeSnapshot
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        last = (
            db.query(RegimeSnapshot)
            .order_by(RegimeSnapshot.ts.desc())
            .first()
        )
        if last and last.ts.replace(tzinfo=timezone.utc) > cutoff:
            return  # too soon
        snap = RegimeSnapshot(
            ts=datetime.now(timezone.utc),
            vix_regime=regime.get("vix_regime", "mid"),
            trend_regime=regime.get("trend_regime", "chop"),
            vol_pctile=regime.get("vol_pctile"),
            btc_dominance=regime.get("btc_dominance"),
            btc_funding_rate=regime.get("btc_funding_rate"),
            spy_price=regime.get("spy_price"),
            vix_value=regime.get("vix_value"),
        )
        db.add(snap)
        db.commit()
        logger.debug("RegimeSnapshot persisted: %s / %s", regime["vix_regime"], regime["trend_regime"])
    except Exception as exc:
        logger.warning("Failed to persist RegimeSnapshot: %s", exc)


def get_regime(db=None) -> dict:
    """
    Return current market regime dict. Uses 15-minute in-memory cache.
    Falls back to last cached value (or safe defaults) on any API error.
    """
    now_ts = time.monotonic()

    # Return cached value if fresh
    if _cache["regime"] is not None and (now_ts - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["regime"]

    last_cached = _cache["regime"]

    try:
        regime = _fetch_regime()
        _cache["regime"] = regime
        _cache["fetched_at"] = now_ts
        _persist_snapshot(regime, db)
        return regime
    except Exception as exc:
        logger.error("Regime detection failed: %s — using cache/defaults", exc)
        return last_cached if last_cached is not None else dict(_SAFE_DEFAULTS)


def _fetch_regime() -> dict:
    """Core fetch logic — calls external APIs and computes regime."""

    # ── VIX via VIXY proxy ────────────────────────────────────────────────────
    vixy_bars = _fetch_alpaca_bars("VIXY", limit=252)
    vix_value: Optional[float] = None
    vix_history: list[float] = []
    vix_regime = "mid"
    vol_pctile = 50.0

    if vixy_bars:
        vix_history = [b["c"] for b in vixy_bars]
        vix_value = vix_history[-1] if vix_history else None
        if vix_value is not None:
            vix_regime = _vix_to_regime(vix_value)
            vol_pctile = _vix_to_percentile(vix_value, vix_history[:-1])

    # ── SPY trend ────────────────────────────────────────────────────────────
    spy_bars = _fetch_alpaca_bars("SPY", limit=252)
    trend_regime, spy_price = _compute_trend_regime(spy_bars)

    # ── BTC dominance ────────────────────────────────────────────────────────
    btc_dominance = _fetch_btc_dominance()

    # ── BTC funding rate ─────────────────────────────────────────────────────
    btc_funding_rate = _fetch_btc_funding_rate()

    regime = {
        "vix_regime": vix_regime,
        "trend_regime": trend_regime,
        "vol_pctile": vol_pctile,
        "btc_dominance": btc_dominance if btc_dominance is not None else _SAFE_DEFAULTS["btc_dominance"],
        "btc_funding_rate": btc_funding_rate if btc_funding_rate is not None else _SAFE_DEFAULTS["btc_funding_rate"],
        "spy_price": spy_price,
        "vix_value": vix_value,
    }

    logger.info(
        "Regime: vix=%s (%.1f) trend=%s btc_dom=%.1f funding=%.4f",
        vix_regime,
        vix_value or 0.0,
        trend_regime,
        regime["btc_dominance"],
        regime["btc_funding_rate"],
    )

    return regime


# ── Shim: detect_regime ───────────────────────────────────────────────────────
# All three call sites (runner.py ×2, scan_and_execute.py) import this name
# but it was never defined here — only get_regime() existed.  The ImportError
# was silently swallowed and every scan ran with regime={}, meaning strategies
# never received real VIX/trend data.
#
# This thin wrapper accepts the (profile_name, profile) signature used by
# callers and delegates to get_regime(), then applies a neutral fallback shim
# so that API failures never leave regime empty.

_NEUTRAL_REGIME: dict = {
    "vix_regime": "mid",
    "trend_regime": "chop",
    "vol_pctile": 50.0,
    "btc_dominance": 50.0,
    "btc_funding_rate": 0.0,
    "spy_price": None,
    "vix_value": None,
}


def detect_regime(profile_name: str = "", profile: dict | None = None, db=None) -> dict:
    """
    Public entry point used by runner.py and scan_and_execute.py.

    Calls get_regime() and, if the result is empty for any reason, returns a
    neutral/permissive regime dict so that strategy scanners are never gated
    out by a missing regime.
    """
    try:
        regime = get_regime(db=db) or {}
    except Exception as exc:
        logger.warning("[detect_regime:%s] get_regime() raised: %s — using neutral shim", profile_name, exc)
        regime = {}

    # Shim: if regime is empty (e.g. all API calls failed before cache was
    # populated), default to neutral so strategies still run.
    if not regime:
        logger.warning(
            "[detect_regime:%s] regime is empty — applying neutral shim",
            profile_name,
        )
        regime = dict(_NEUTRAL_REGIME)

    return regime
