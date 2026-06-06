from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TTL = 60.0  # 1-minute cache for live price updates

_caches: dict[str, dict[str, Any]] = {
    "top_coins":    {"data": None, "ts": 0.0},
    "fear_greed":   {"data": None, "ts": 0.0},
    "global_market":{"data": None, "ts": 0.0},
    "trending":     {"data": None, "ts": 0.0},
}
_lock = threading.Lock()

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FNG_BASE = "https://api.alternative.me"

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BMGCapital/1.0",
}


def _get_cached(key: str) -> Any | None:
    with _lock:
        c = _caches[key]
        if c["data"] is not None and time.time() - c["ts"] < _TTL:
            return c["data"]
    return None


def _set_cached(key: str, data: Any) -> None:
    with _lock:
        _caches[key]["data"] = data
        _caches[key]["ts"] = time.time()


def get_top_coins(limit: int = 100) -> list[dict]:
    cached = _get_cached("top_coins")
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(
                f"{COINGECKO_BASE}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": limit,
                    "page": 1,
                    "sparkline": "true",
                    "price_change_percentage": "1h,24h,7d",
                },
                headers=_HEADERS,
            )
            r.raise_for_status()
            raw = r.json()
    except Exception as e:
        logger.warning(f"CoinGecko top_coins failed: {e}")
        return []

    result = []
    for c in raw:
        sp = c.get("sparkline_in_7d") or {}
        sparkline = sp.get("price") or []
        result.append({
            "id":              c.get("id"),
            "symbol":          (c.get("symbol") or "").upper(),
            "name":            c.get("name"),
            "image":           c.get("image"),
            "current_price":   c.get("current_price"),
            "market_cap":      c.get("market_cap") or 0,
            "market_cap_rank": c.get("market_cap_rank"),
            "total_volume":    c.get("total_volume") or 0,
            "pct_1h":          c.get("price_change_percentage_1h_in_currency"),
            "pct_24h":         c.get("price_change_percentage_24h"),
            "pct_7d":          c.get("price_change_percentage_7d_in_currency"),
            "high_24h":    c.get("high_24h"),
            "low_24h":     c.get("low_24h"),
            "ath":         c.get("ath"),
            "ath_change_percentage": c.get("ath_change_percentage"),
            "sparkline":       sparkline[-168:] if sparkline else [],
        })

    _set_cached("top_coins", result)
    return result


def get_fear_greed() -> dict:
    cached = _get_cached("fear_greed")
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{FNG_BASE}/fng/?limit=1", headers=_HEADERS)
            r.raise_for_status()
            entry = r.json()["data"][0]
            result = {
                "value": int(entry["value"]),
                "label": entry["value_classification"],
                "timestamp": entry.get("timestamp"),
            }
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")
        result = {"value": 50, "label": "Neutral", "timestamp": None}

    _set_cached("fear_greed", result)
    return result


def get_global_market() -> dict:
    cached = _get_cached("global_market")
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{COINGECKO_BASE}/global", headers=_HEADERS)
            r.raise_for_status()
            d = r.json()["data"]
            result = {
                "total_market_cap_usd":    d.get("total_market_cap", {}).get("usd", 0),
                "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd", 0),
                "btc_dominance":            d.get("market_cap_percentage", {}).get("btc", 0),
                "active_coins":             d.get("active_cryptocurrencies", 0),
            }
    except Exception as e:
        logger.warning(f"CoinGecko global failed: {e}")
        result = {
            "total_market_cap_usd": 0,
            "market_cap_change_24h_pct": 0,
            "btc_dominance": 0,
            "active_coins": 0,
        }

    _set_cached("global_market", result)
    return result


def get_trending() -> list[dict]:
    cached = _get_cached("trending")
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{COINGECKO_BASE}/search/trending", headers=_HEADERS)
            r.raise_for_status()
            items = r.json().get("coins", [])
    except Exception as e:
        logger.warning(f"CoinGecko trending failed: {e}")
        items = []

    base_result = []
    coin_ids = []
    for item in items:
        coin = item.get("item", {})
        data = coin.get("data", {})
        pct_obj = data.get("price_change_percentage_24h") or {}
        pct_24h = pct_obj.get("usd") if isinstance(pct_obj, dict) else None
        cid = coin.get("id")
        if cid:
            coin_ids.append(cid)
        base_result.append({
            "id":              cid,
            "symbol":          (coin.get("symbol") or "").upper(),
            "name":            coin.get("name"),
            "image":           coin.get("large") or coin.get("small"),
            "market_cap_rank": coin.get("market_cap_rank"),
            "pct_24h":         pct_24h,
            "sparkline_url":   data.get("sparkline"),
            "current_price":   data.get("price"),
            "market_cap":      0,
            "total_volume":    0,
            "pct_1h":          None,
            "pct_7d":          None,
            "sparkline":       [],
            "high_24h":        None,
            "low_24h":         None,
            "ath":             None,
            "ath_change_percentage": None,
        })

    # Enrich with market data for the trending coin IDs
    market_by_id: dict[str, dict] = {}
    if coin_ids:
        try:
            with httpx.Client(timeout=15) as client:
                mr = client.get(
                    f"{COINGECKO_BASE}/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "ids": ",".join(coin_ids),
                        "sparkline": "true",
                        "price_change_percentage": "1h,24h,7d",
                    },
                    headers=_HEADERS,
                )
                mr.raise_for_status()
                for m in mr.json():
                    market_by_id[m["id"]] = m
        except Exception as e:
            logger.warning(f"CoinGecko trending market enrichment failed: {e}")

    result = []
    for entry in base_result:
        m = market_by_id.get(entry["id"] or "")
        if m:
            sp = (m.get("sparkline_in_7d") or {}).get("price") or []
            entry.update({
                "current_price":          m.get("current_price"),
                "market_cap":             m.get("market_cap") or 0,
                "total_volume":           m.get("total_volume") or 0,
                "pct_1h":                 m.get("price_change_percentage_1h_in_currency"),
                "pct_24h":                m.get("price_change_percentage_24h") or entry["pct_24h"],
                "pct_7d":                 m.get("price_change_percentage_7d_in_currency"),
                "sparkline":              sp[-168:] if sp else [],
                "high_24h":               m.get("high_24h"),
                "low_24h":                m.get("low_24h"),
                "ath":                    m.get("ath"),
                "ath_change_percentage":  m.get("ath_change_percentage"),
            })
        result.append(entry)

    _set_cached("trending", result)
    return result


def invalidate_all() -> None:
    with _lock:
        for key in _caches:
            _caches[key]["ts"] = 0.0
