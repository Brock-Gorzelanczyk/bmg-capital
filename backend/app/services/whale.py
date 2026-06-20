from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TTL = 3600.0  # 1-hour cache
_cache: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

COINMETRICS_BASE = "https://community-api.coinmetrics.io/v4"
_HEADERS = {"Accept": "application/json", "User-Agent": "BMGCapital/1.0"}

_ASSET_MAP = {
    "BTC/USDT": "btc",
    "ETH/USDT": "eth",
    "BTC-USD":  "btc",
    "ETH-USD":  "eth",
}


def _get_cached(key: str) -> Any | None:
    with _lock:
        c = _cache.get(key)
        if c and c.get("data") is not None and time.time() - c.get("ts", 0) < _TTL:
            return c["data"]
    return None


def _set_cached(key: str, data: Any) -> None:
    with _lock:
        _cache[key] = {"data": data, "ts": time.time()}


def get_large_holder_signal(symbol: str) -> dict:
    """
    Returns large wallet holder count change for BTC or ETH.
    Uses AdrBal1in1MCnt (addresses with >= $1M balance).
    Signal: accumulating (count rising >1%), distributing (falling >1%), neutral.
    """
    asset = _ASSET_MAP.get(symbol)
    if not asset:
        return {"ok": False, "signal": "neutral", "large_holder_count": 0, "change_pct": 0.0}

    cache_key = f"whale_{asset}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        # CoinMetrics v4 uses start_time/end_time for range and page_size for count.
        # `limit` is not a valid param and returns 400.
        start_time = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with httpx.Client(timeout=15) as client:
            r = client.get(
                f"{COINMETRICS_BASE}/timeseries/asset-metrics",
                params={
                    "assets": asset,
                    "metrics": "AdrBal1in1MCnt",
                    "frequency": "1d",
                    "start_time": start_time,
                    "page_size": 14,
                    "pretty": "false",
                },
                headers=_HEADERS,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("[whale] CoinMetrics request failed for %s: %s", asset, e)
        result = {"ok": False, "signal": "neutral", "large_holder_count": 0, "change_pct": 0.0}
        _set_cached(cache_key, result)
        return result

    try:
        series = data.get("data", [])
        if len(series) < 7:
            logger.warning("[whale] CoinMetrics returned only %d rows for %s (need 7)", len(series), asset)
            raise ValueError("Not enough data points")

        # Most recent value vs 7 days ago
        recent_val = float(series[-1].get("AdrBal1in1MCnt") or 0)
        week_ago_val = float(series[-7].get("AdrBal1in1MCnt") or 0)

        if week_ago_val <= 0:
            change_pct = 0.0
        else:
            change_pct = (recent_val - week_ago_val) / week_ago_val * 100

        if change_pct > 1.0:
            signal = "accumulating"
        elif change_pct < -1.0:
            signal = "distributing"
        else:
            signal = "neutral"

        result = {
            "ok": True,
            "signal": signal,
            "large_holder_count": int(recent_val),
            "prev_count": int(week_ago_val),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        logger.warning("[whale] CoinMetrics parse failed for %s: %s", asset, e)
        result = {"ok": False, "signal": "neutral", "large_holder_count": 0, "change_pct": 0.0}

    _set_cached(cache_key, result)
    return result


def prefetch_whale(symbols: list[str]) -> None:
    for sym in symbols:
        try:
            get_large_holder_signal(sym)
        except Exception:
            pass
